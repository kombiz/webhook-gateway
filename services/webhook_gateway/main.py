"""Webhook Gateway — receives, logs, and forwards webhooks to Alerta."""
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .db import Database
from .models import EndpointCreate, EndpointUpdate, SourceType
from .forwarder import AlertaForwarder
from .signatures import verify_github_signature, verify_generic_token

DB_PATH = os.environ.get("WEBHOOK_DB_PATH", "/data/webhook-gateway.db")
ALERTA_URL = os.environ.get("ALERTA_URL", "http://localhost:4000")
ALERTA_TOKEN = os.environ.get("ALERTA_TOKEN", "")
GATEWAY_TOKEN = os.environ.get("GATEWAY_TOKEN", "")

_db: Database | None = None
_forwarder: AlertaForwarder | None = None

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _db, _forwarder
    _db = Database(DB_PATH)
    await _db.init()
    _forwarder = AlertaForwarder(ALERTA_URL, ALERTA_TOKEN)
    yield
    await _db.close()


app = FastAPI(title="Webhook Gateway", lifespan=lifespan)

templates = None
if TEMPLATES_DIR.exists():
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def get_db() -> Database:
    return _db


def require_auth(request: Request):
    if not GATEWAY_TOKEN:
        return
    auth = request.headers.get("Authorization", "")
    if not verify_generic_token(auth, GATEWAY_TOKEN):
        raise HTTPException(status_code=401, detail="Unauthorized")


# ── Health ──────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "webhook-gateway"}


# ── Web UI ──────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    db = get_db()
    webhooks = [wh.model_dump() for wh in await db.list_webhooks(limit=50)]
    total = await db.count_webhooks()
    endpoints = [ep.model_dump() for ep in await db.list_endpoints()]
    if templates:
        return templates.TemplateResponse(request, "dashboard.html", context={
            "webhooks": webhooks, "total": total, "endpoints": endpoints,
        })
    return HTMLResponse("<html><body><h1>Webhook Gateway</h1><p>Templates not loaded.</p></body></html>")


@app.get("/endpoints", response_class=HTMLResponse)
async def endpoints_page(request: Request):
    db = get_db()
    endpoints = [ep.model_dump() for ep in await db.list_endpoints()]
    if templates:
        return templates.TemplateResponse(request, "endpoints.html", context={
            "endpoints": endpoints, "source_types": [s.value for s in SourceType],
        })
    return HTMLResponse("<html><body><h1>Endpoints</h1><p>Templates not loaded.</p></body></html>")


# ── Webhook Receive ────────────────────────────────────

@app.post("/webhook/{source}")
async def receive_webhook(source: str, request: Request):
    db = get_db()
    body = await request.body()
    headers = dict(request.headers)
    start = time.monotonic()

    try:
        payload = await request.json()
    except Exception:
        payload = {"raw": body.decode("utf-8", errors="replace")}

    endpoint = await db.get_endpoint_by_source(source)

    if endpoint and endpoint.secret:
        if source == "github":
            sig = headers.get("x-hub-signature-256")
            if not verify_github_signature(body, sig, endpoint.secret):
                raise HTTPException(status_code=403, detail="Invalid signature")
        else:
            auth = headers.get("authorization")
            if not verify_generic_token(auth, endpoint.secret):
                raise HTTPException(status_code=403, detail="Invalid token")

    forward_status = None
    forward_response = None
    try:
        event = _forwarder.normalize(source, headers, payload)
        forward_status, forward_response = await _forwarder.forward(event)
    except Exception as e:
        forward_status = 502
        forward_response = str(e)

    elapsed_ms = int((time.monotonic() - start) * 1000)

    await db.log_webhook(
        endpoint_id=endpoint.id if endpoint else None,
        source_type=source, headers=headers, payload=payload,
        forward_status=forward_status, forward_response=forward_response,
        processing_ms=elapsed_ms,
    )

    if forward_status and forward_status >= 400:
        return JSONResponse(
            status_code=502,
            content={"status": "forward_error", "forward_status": forward_status},
        )
    return {"status": "ok", "forward_status": forward_status, "processing_ms": elapsed_ms}


# ── Endpoint CRUD API ──────────────────────────────────

@app.get("/api/endpoints")
async def list_endpoints_api(request: Request, _=Depends(require_auth)):
    db = get_db()
    endpoints = await db.list_endpoints()
    return [ep.model_dump() for ep in endpoints]


@app.post("/api/endpoints", status_code=201)
async def create_endpoint(ep: EndpointCreate, request: Request, _=Depends(require_auth)):
    db = get_db()
    created = await db.create_endpoint(ep)
    return created.model_dump()


@app.put("/api/endpoints/{ep_id}")
async def update_endpoint(ep_id: str, ep: EndpointUpdate, request: Request, _=Depends(require_auth)):
    db = get_db()
    updated = await db.update_endpoint(ep_id, **ep.model_dump(exclude_none=True))
    if not updated:
        raise HTTPException(status_code=404, detail="Endpoint not found")
    return updated.model_dump()


@app.delete("/api/endpoints/{ep_id}", status_code=204)
async def delete_endpoint_api(ep_id: str, request: Request, _=Depends(require_auth)):
    db = get_db()
    await db.delete_endpoint(ep_id)
    return Response(status_code=204)


@app.get("/api/webhooks")
async def list_webhooks_api(request: Request, limit: int = 50, offset: int = 0, _=Depends(require_auth)):
    db = get_db()
    logs = await db.list_webhooks(limit=limit, offset=offset)
    return [log.model_dump() for log in logs]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=4100)
