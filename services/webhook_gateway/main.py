"""Webhook Gateway — receives, logs, persists, and forwards webhooks to Alerta and Mattermost."""

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
from .forwarder import Forwarder
from .signatures import (
    verify_github_signature,
    verify_generic_token,
    verify_meltwater_signature,
    verify_slack_signature,
)

DB_PATH = os.environ.get("WEBHOOK_DB_PATH", "/data/webhook-gateway.db")
ALERTA_URL = os.environ.get("ALERTA_URL", "http://localhost:4000")
ALERTA_TOKEN = os.environ.get("ALERTA_TOKEN", "")
GATEWAY_TOKEN = os.environ.get("GATEWAY_TOKEN", "")
MATTERMOST_WEBHOOK_URL = os.environ.get("MATTERMOST_WEBHOOK_URL", "")
MATTERMOST_CHANNEL = os.environ.get("MATTERMOST_CHANNEL", "")

_db: Database | None = None
_forwarder: Forwarder | None = None

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _db, _forwarder
    _db = Database(DB_PATH)
    await _db.init()
    _forwarder = Forwarder(
        alerta_url=ALERTA_URL,
        alerta_token=ALERTA_TOKEN,
        mattermost_webhook_url=MATTERMOST_WEBHOOK_URL,
        mattermost_channel=MATTERMOST_CHANNEL,
    )
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
    return {
        "status": "ok",
        "service": "webhook-gateway",
        "alerta": bool(ALERTA_TOKEN),
        "mattermost": bool(MATTERMOST_WEBHOOK_URL),
    }


# ── Web UI ──────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    db = get_db()
    webhooks = [wh.model_dump() for wh in await db.list_webhooks(limit=50)]
    total = await db.count_webhooks()
    endpoints = [ep.model_dump() for ep in await db.list_endpoints()]
    if templates:
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            context={
                "webhooks": webhooks,
                "total": total,
                "endpoints": endpoints,
            },
        )
    return HTMLResponse(
        "<html><body><h1>Webhook Gateway</h1><p>Templates not loaded.</p></body></html>"
    )


@app.get("/endpoints", response_class=HTMLResponse)
async def endpoints_page(request: Request):
    db = get_db()
    endpoints = [ep.model_dump() for ep in await db.list_endpoints()]
    if templates:
        return templates.TemplateResponse(
            request,
            "endpoints.html",
            context={
                "endpoints": endpoints,
                "source_types": [s.value for s in SourceType],
            },
        )
    return HTMLResponse(
        "<html><body><h1>Endpoints</h1><p>Templates not loaded.</p></body></html>"
    )


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
        ok = _validate_signature(source, body, headers, endpoint.secret)
        if not ok:
            raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        result = await _forwarder.forward(source, headers, payload, db=db)
    except Exception as e:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        await db.log_webhook(
            endpoint_id=endpoint.id if endpoint else None,
            source_type=source,
            headers=headers,
            payload=payload,
            forward_status=502,
            forward_response=str(e),
            processing_ms=elapsed_ms,
        )
        return JSONResponse(
            status_code=502,
            content={"status": "forward_error", "detail": str(e)},
        )

    elapsed_ms = int((time.monotonic() - start) * 1000)
    forward_status = result.alerta_status or result.mattermost_status
    forward_response = (result.alerta_body or "") + (result.mattermost_body or "")

    await db.log_webhook(
        endpoint_id=endpoint.id if endpoint else None,
        source_type=source,
        headers=headers,
        payload=payload,
        forward_status=forward_status,
        forward_response=forward_response,
        processing_ms=elapsed_ms,
    )

    if not result.ok:
        return JSONResponse(
            status_code=502,
            content={
                "status": "forward_error",
                "alerta_status": result.alerta_status,
                "mattermost_status": result.mattermost_status,
                "meltwater_persisted": result.meltwater_persisted,
            },
        )
    return {
        "status": "ok",
        "alerta_status": result.alerta_status,
        "mattermost_status": result.mattermost_status,
        "meltwater_persisted": result.meltwater_persisted,
        "processing_ms": elapsed_ms,
    }


def _validate_signature(source: str, body: bytes, headers: dict, secret: str) -> bool:
    if source == "github":
        sig = headers.get("x-hub-signature-256")
        return verify_github_signature(body, sig, secret)
    if source == "meltwater":
        sig = headers.get("x-meltwater-signature")
        return verify_meltwater_signature(body, sig, secret)
    if source == "slack":
        return verify_slack_signature(body, headers, secret)
    auth = headers.get("authorization")
    return verify_generic_token(auth, secret)


# ── Endpoint CRUD API ──────────────────────────────────


@app.get("/api/endpoints")
async def list_endpoints_api(request: Request, _=Depends(require_auth)):
    db = get_db()
    endpoints = await db.list_endpoints()
    return [ep.model_dump() for ep in endpoints]


@app.post("/api/endpoints", status_code=201)
async def create_endpoint(
    ep: EndpointCreate, request: Request, _=Depends(require_auth)
):
    db = get_db()
    created = await db.create_endpoint(ep)
    return created.model_dump()


@app.put("/api/endpoints/{ep_id}")
async def update_endpoint(
    ep_id: str, ep: EndpointUpdate, request: Request, _=Depends(require_auth)
):
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
async def list_webhooks_api(
    request: Request, limit: int = 50, offset: int = 0, _=Depends(require_auth)
):
    db = get_db()
    logs = await db.list_webhooks(limit=limit, offset=offset)
    return [log.model_dump() for log in logs]


# ── Meltwater inbox ────────────────────────────────────


@app.get("/api/meltwater/inbox")
async def meltwater_inbox(
    request: Request,
    limit: int = 50,
    unprocessed_only: bool = True,
    _=Depends(require_auth),
):
    db = get_db()
    return await db.list_meltwater_inbox(limit=limit, unprocessed_only=unprocessed_only)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=4100)
