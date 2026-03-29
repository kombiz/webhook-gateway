"""SQLite database layer for webhook gateway."""
import json
import uuid
from datetime import datetime, timezone
import aiosqlite
from .models import EndpointCreate, EndpointResponse, WebhookLogEntry

SCHEMA = """
CREATE TABLE IF NOT EXISTS endpoints (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    secret TEXT,
    forward_url TEXT NOT NULL,
    enabled INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS webhook_log (
    id TEXT PRIMARY KEY,
    endpoint_id TEXT REFERENCES endpoints(id) ON DELETE SET NULL,
    source_type TEXT NOT NULL,
    received_at TEXT NOT NULL,
    headers TEXT,
    payload TEXT,
    forward_status INTEGER,
    forward_response TEXT,
    processing_ms INTEGER
);
CREATE INDEX IF NOT EXISTS idx_webhook_log_received ON webhook_log(received_at DESC);
CREATE INDEX IF NOT EXISTS idx_webhook_log_endpoint ON webhook_log(endpoint_id);
"""

class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def init(self):
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self):
        if self._conn:
            await self._conn.close()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    async def create_endpoint(self, ep: EndpointCreate) -> EndpointResponse:
        now = self._now()
        ep_id = uuid.uuid4().hex[:12]
        await self._conn.execute(
            "INSERT INTO endpoints (id, name, source_type, secret, forward_url, enabled, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (ep_id, ep.name, ep.source_type, ep.secret, ep.forward_url, int(ep.enabled), now, now),
        )
        await self._conn.commit()
        return EndpointResponse(
            id=ep_id, name=ep.name, source_type=ep.source_type,
            secret=ep.secret, forward_url=ep.forward_url,
            enabled=ep.enabled, created_at=now, updated_at=now,
        )

    async def get_endpoint(self, ep_id: str) -> EndpointResponse | None:
        cursor = await self._conn.execute("SELECT * FROM endpoints WHERE id = ?", (ep_id,))
        row = await cursor.fetchone()
        if not row:
            return None
        return self._row_to_endpoint(row)

    async def get_endpoint_by_source(self, source_type: str) -> EndpointResponse | None:
        cursor = await self._conn.execute(
            "SELECT * FROM endpoints WHERE source_type = ? AND enabled = 1 LIMIT 1",
            (source_type,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return self._row_to_endpoint(row)

    async def list_endpoints(self) -> list[EndpointResponse]:
        cursor = await self._conn.execute("SELECT * FROM endpoints ORDER BY created_at DESC")
        rows = await cursor.fetchall()
        return [self._row_to_endpoint(r) for r in rows]

    async def update_endpoint(self, ep_id: str, **kwargs) -> EndpointResponse | None:
        allowed = {"name", "secret", "forward_url", "enabled"}
        updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if not updates:
            return await self.get_endpoint(ep_id)
        if "enabled" in updates:
            updates["enabled"] = int(updates["enabled"])
        updates["updated_at"] = self._now()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [ep_id]
        await self._conn.execute(f"UPDATE endpoints SET {set_clause} WHERE id = ?", values)
        await self._conn.commit()
        return await self.get_endpoint(ep_id)

    async def delete_endpoint(self, ep_id: str):
        await self._conn.execute("DELETE FROM endpoints WHERE id = ?", (ep_id,))
        await self._conn.commit()

    async def log_webhook(
        self, endpoint_id: str | None, source_type: str,
        headers: dict, payload: dict,
        forward_status: int | None, forward_response: str | None,
        processing_ms: int | None,
    ) -> WebhookLogEntry:
        log_id = uuid.uuid4().hex[:16]
        now = self._now()
        await self._conn.execute(
            "INSERT INTO webhook_log (id, endpoint_id, source_type, received_at, headers, payload, forward_status, forward_response, processing_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (log_id, endpoint_id, source_type, now, json.dumps(headers), json.dumps(payload),
             forward_status, forward_response, processing_ms),
        )
        await self._conn.commit()
        return WebhookLogEntry(
            id=log_id, endpoint_id=endpoint_id, source_type=source_type,
            received_at=now, headers=headers, payload=payload,
            forward_status=forward_status, forward_response=forward_response,
            processing_ms=processing_ms,
        )

    async def list_webhooks(self, limit: int = 50, offset: int = 0) -> list[WebhookLogEntry]:
        cursor = await self._conn.execute(
            "SELECT * FROM webhook_log ORDER BY received_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        rows = await cursor.fetchall()
        return [self._row_to_log(r) for r in rows]

    async def count_webhooks(self) -> int:
        cursor = await self._conn.execute("SELECT COUNT(*) FROM webhook_log")
        row = await cursor.fetchone()
        return row[0]

    def _row_to_endpoint(self, row) -> EndpointResponse:
        return EndpointResponse(
            id=row["id"], name=row["name"], source_type=row["source_type"],
            secret=row["secret"], forward_url=row["forward_url"],
            enabled=bool(row["enabled"]),
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    def _row_to_log(self, row) -> WebhookLogEntry:
        return WebhookLogEntry(
            id=row["id"], endpoint_id=row["endpoint_id"],
            source_type=row["source_type"], received_at=row["received_at"],
            headers=json.loads(row["headers"]) if row["headers"] else None,
            payload=json.loads(row["payload"]) if row["payload"] else None,
            forward_status=row["forward_status"],
            forward_response=row["forward_response"],
            processing_ms=row["processing_ms"],
        )
