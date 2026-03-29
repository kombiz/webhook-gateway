"""Webhook signature validation for different source types."""
import hashlib
import hmac

def verify_github_signature(body: bytes, signature: str | None, secret: str) -> bool:
    """Validate GitHub webhook HMAC-SHA256 signature."""
    if not signature or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)

def verify_generic_token(auth_header: str | None, expected_token: str) -> bool:
    """Validate a simple Bearer token."""
    if not auth_header:
        return False
    parts = auth_header.split(" ", 1)
    if len(parts) != 2 or parts[0] != "Bearer":
        return False
    return hmac.compare_digest(parts[1], expected_token)
