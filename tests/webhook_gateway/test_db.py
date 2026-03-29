"""Tests for webhook gateway database layer."""
import pytest
import pytest_asyncio
from services.webhook_gateway.db import Database
from services.webhook_gateway.models import EndpointCreate, SourceType

@pytest_asyncio.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.init()
    yield database
    await database.close()

@pytest.mark.asyncio
async def test_create_and_get_endpoint(db):
    ep = EndpointCreate(name="GitHub CI", source_type=SourceType.GITHUB, secret="s3cret")
    created = await db.create_endpoint(ep)
    assert created.name == "GitHub CI"
    assert created.source_type == "github"
    assert created.id is not None
    fetched = await db.get_endpoint(created.id)
    assert fetched is not None
    assert fetched.name == "GitHub CI"

@pytest.mark.asyncio
async def test_list_endpoints(db):
    await db.create_endpoint(EndpointCreate(name="EP1", source_type=SourceType.GITHUB))
    await db.create_endpoint(EndpointCreate(name="EP2", source_type=SourceType.SLACK))
    endpoints = await db.list_endpoints()
    assert len(endpoints) == 2

@pytest.mark.asyncio
async def test_update_endpoint(db):
    ep = await db.create_endpoint(EndpointCreate(name="Old", source_type=SourceType.GENERIC))
    updated = await db.update_endpoint(ep.id, name="New", enabled=False)
    assert updated.name == "New"
    assert updated.enabled is False

@pytest.mark.asyncio
async def test_delete_endpoint(db):
    ep = await db.create_endpoint(EndpointCreate(name="ToDelete", source_type=SourceType.GENERIC))
    await db.delete_endpoint(ep.id)
    assert await db.get_endpoint(ep.id) is None

@pytest.mark.asyncio
async def test_log_webhook_and_list(db):
    ep = await db.create_endpoint(EndpointCreate(name="EP", source_type=SourceType.GITHUB))
    await db.log_webhook(
        endpoint_id=ep.id, source_type="github",
        headers={"x-github-event": "push"}, payload={"ref": "refs/heads/main"},
        forward_status=200, forward_response="ok", processing_ms=15,
    )
    logs = await db.list_webhooks(limit=10)
    assert len(logs) == 1
    assert logs[0].source_type == "github"
    assert logs[0].forward_status == 200

@pytest.mark.asyncio
async def test_list_webhooks_pagination(db):
    ep = await db.create_endpoint(EndpointCreate(name="EP", source_type=SourceType.GENERIC))
    for i in range(5):
        await db.log_webhook(
            endpoint_id=ep.id, source_type="generic",
            headers={}, payload={"i": i},
            forward_status=200, forward_response="ok", processing_ms=1,
        )
    page = await db.list_webhooks(limit=3)
    assert len(page) == 3
    assert page[0].payload["i"] == 4
