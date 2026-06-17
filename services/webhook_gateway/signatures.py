"""Webhook signature validation for different source types."""
import hashlib
import hmac

def verify_github_signature(body: bytes, signature: str | None, secret: str) -> bool:
    """Validate GitHub webhook HMAC-SHA256 signature."""
    if not signature or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)

def verify_meltwater_signature(body: bytes, signature: str | None, secret: str) -> bool:
    """Validate Meltwater webhook HMAC-SHA256 signature.

    Meltwater signs the raw request body with a shared secret and ships
    the hex digest in the ``X-Meltwater-Signature`` header. Some
    installations prefix the digest with ``sha256=``; both forms are
    accepted.
    """
    if not signature:
        return False
    raw = signature[7:] if signature.startswith("sha256=") else signature
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(raw, expected)

def verify_slack_signature(body: bytes, headers: dict, secret: str) -> bool:
    """Validate Slack webhook signature (v0 scheme)."""
    timestamp = headers.get("x-slack-request-timestamp")
    signature = headers.get("x-slack-signature")
    if not timestamp or not signature or not signature.startswith("v0="):
        return False
    base = f"v0:{timestamp}:".encode() + body
    expected = "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)

def verify_generic_token(auth_header: str | None, expected_token: str) -> bool:
    """Validate a simple Bearer token."""
    if not auth_header:
        return False
    parts = auth_header.split(" ", 1)
    if len(parts) != 2 or parts[0] != "Bearer":
        return False
    return hmac.compare_digest(parts[1], expected_token)
