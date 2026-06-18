"""Tests for webhook gateway API routes."""

import pytest
from fastapi.testclient import TestClient
import os

os.environ.setdefault("WEBHOOK_DB_PATH", ":memory:")
os.environ.setdefault("ALERTA_URL", "http://localhost:4000")
os.environ.setdefault("ALERTA_TOKEN", "test_token")
os.environ.setdefault("GATEWAY_TOKEN", "gw_test_token")

from services.webhook_gateway.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "webhook-gateway"


def test_create_endpoint(client):
    resp = client.post(
        "/api/endpoints",
        json={"name": "Test EP", "source_type": "github"},
        headers={"Authorization": "Bearer gw_test_token"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Test EP"
    assert data["source_type"] == "github"
    assert "id" in data


def test_create_endpoint_unauthorized(client):
    resp = client.post(
        "/api/endpoints",
        json={"name": "Test EP", "source_type": "github"},
    )
    assert resp.status_code == 401


def test_list_endpoints(client):
    client.post(
        "/api/endpoints",
        json={"name": "EP1", "source_type": "github"},
        headers={"Authorization": "Bearer gw_test_token"},
    )
    resp = client.get(
        "/api/endpoints",
        headers={"Authorization": "Bearer gw_test_token"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1


def test_delete_endpoint(client):
    resp = client.post(
        "/api/endpoints",
        json={"name": "ToDelete", "source_type": "generic"},
        headers={"Authorization": "Bearer gw_test_token"},
    )
    ep_id = resp.json()["id"]
    del_resp = client.delete(
        f"/api/endpoints/{ep_id}",
        headers={"Authorization": "Bearer gw_test_token"},
    )
    assert del_resp.status_code == 204


def test_receive_generic_webhook(client):
    client.post(
        "/api/endpoints",
        json={"name": "Generic", "source_type": "generic"},
        headers={"Authorization": "Bearer gw_test_token"},
    )
    resp = client.post(
        "/webhook/generic",
        json={"title": "Test event", "body": "Hello", "severity": "info"},
    )
    assert resp.status_code in (200, 502)


def test_list_webhooks_api(client):
    resp = client.get(
        "/api/webhooks",
        headers={"Authorization": "Bearer gw_test_token"},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
