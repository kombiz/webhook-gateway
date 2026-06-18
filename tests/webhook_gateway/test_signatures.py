"""Tests for webhook signature validation."""

import hashlib
import hmac
import json
from services.webhook_gateway.signatures import (
    verify_github_signature,
    verify_generic_token,
)


def test_github_signature_valid():
    secret = "mysecret"
    payload = json.dumps({"action": "opened"}).encode()
    sig = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    assert verify_github_signature(payload, sig, secret) is True


def test_github_signature_invalid():
    assert verify_github_signature(b"body", "sha256=bad", "secret") is False


def test_github_signature_wrong_prefix():
    assert verify_github_signature(b"body", "sha1=abc", "secret") is False


def test_github_signature_none():
    assert verify_github_signature(b"body", None, "secret") is False


def test_generic_token_valid():
    assert verify_generic_token("Bearer mytoken", "mytoken") is True


def test_generic_token_invalid():
    assert verify_generic_token("Bearer wrong", "mytoken") is False


def test_generic_token_none():
    assert verify_generic_token(None, "mytoken") is False
