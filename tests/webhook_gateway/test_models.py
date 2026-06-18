"""Tests for webhook gateway data models."""

from services.webhook_gateway.models import (
    EndpointCreate,
    EndpointResponse,
    WebhookLogEntry,
    SourceType,
)


def test_endpoint_create_defaults():
    ep = EndpointCreate(name="GitHub CI", source_type=SourceType.GITHUB)
    assert ep.forward_url == "http://localhost:4000/api/events"
    assert ep.enabled is True
    assert ep.secret is None


def test_endpoint_create_custom_forward():
    ep = EndpointCreate(
        name="Custom",
        source_type=SourceType.GENERIC,
        forward_url="http://example.com/hook",
        secret="mysecret",
    )
    assert ep.forward_url == "http://example.com/hook"
    assert ep.secret == "mysecret"


def test_source_type_values():
    assert SourceType.GITHUB == "github"
    assert SourceType.SLACK == "slack"
    assert SourceType.PROMETHEUS == "prometheus"
    assert SourceType.GENERIC == "generic"


def test_endpoint_response_has_id_and_timestamps():
    ep = EndpointResponse(
        id="abc123",
        name="Test",
        source_type=SourceType.GENERIC,
        forward_url="http://localhost:4000/api/events",
        enabled=True,
        created_at="2026-03-28T00:00:00Z",
        updated_at="2026-03-28T00:00:00Z",
    )
    assert ep.id == "abc123"


def test_webhook_log_entry():
    entry = WebhookLogEntry(
        id="log1",
        endpoint_id="ep1",
        source_type="github",
        received_at="2026-03-28T00:00:00Z",
        headers={"content-type": "application/json"},
        payload={"action": "opened"},
        forward_status=200,
        forward_response="ok",
        processing_ms=42,
    )
    assert entry.forward_status == 200
    assert entry.processing_ms == 42
