"""Tests for Alerta forwarder."""

import pytest
from services.webhook_gateway.forwarder import AlertaForwarder


@pytest.fixture
def forwarder():
    return AlertaForwarder(base_url="http://localhost:4000", token="alrt_test_token")


def test_normalize_github_push():
    forwarder = AlertaForwarder("http://localhost:4000", "token")
    payload = {
        "ref": "refs/heads/main",
        "pusher": {"name": "kombiz"},
        "repository": {"full_name": "kombiz/alerta"},
        "head_commit": {"message": "fix: thing"},
    }
    event = forwarder.normalize("github", {"x-github-event": "push"}, payload)
    assert event["title"] == "Push to kombiz/alerta"
    assert event["source"] == "github"
    assert event["severity"] == "info"
    assert "kombiz" in event["body"]


def test_normalize_github_issues():
    forwarder = AlertaForwarder("http://localhost:4000", "token")
    payload = {
        "action": "opened",
        "issue": {
            "title": "Bug",
            "number": 42,
            "html_url": "https://github.com/x/y/issues/42",
        },
        "repository": {"full_name": "kombiz/repo"},
    }
    event = forwarder.normalize("github", {"x-github-event": "issues"}, payload)
    assert "Bug" in event["title"]
    assert event["severity"] == "warning"


def test_normalize_github_workflow_run():
    forwarder = AlertaForwarder("http://localhost:4000", "token")
    payload = {
        "action": "completed",
        "workflow_run": {
            "name": "CI",
            "conclusion": "failure",
            "html_url": "https://github.com/x/y/actions/runs/1",
        },
        "repository": {"full_name": "kombiz/repo"},
    }
    event = forwarder.normalize("github", {"x-github-event": "workflow_run"}, payload)
    assert event["severity"] == "critical"
    assert "CI" in event["title"]


def test_normalize_generic():
    forwarder = AlertaForwarder("http://localhost:4000", "token")
    payload = {"title": "Test", "body": "Hello", "severity": "warning"}
    event = forwarder.normalize("generic", {}, payload)
    assert event["title"] == "Test"
    assert event["severity"] == "warning"


def test_normalize_prometheus():
    forwarder = AlertaForwarder("http://localhost:4000", "token")
    payload = {
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "HighCPU", "instance": "web-1"},
                "annotations": {"summary": "CPU above 90%"},
            }
        ],
    }
    event = forwarder.normalize("prometheus", {}, payload)
    assert "HighCPU" in event["title"]
    assert event["severity"] == "warning"
