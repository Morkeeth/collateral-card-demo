"""Refuse any write path that is not loopback."""
from urllib.parse import urlparse


class NotLocalRPC(ValueError):
    """Raised when a URL is not exactly local loopback."""


def require_local(url: str) -> str:
    """Allow only http(s)://127.0.0.1 or http(s)://localhost with no userinfo."""
    if not url or not isinstance(url, str):
        raise NotLocalRPC("empty rpc url")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise NotLocalRPC(f"not local rpc: {url}")
    if parsed.username is not None or parsed.password is not None:
        raise NotLocalRPC(f"not local rpc: {url}")
    # Exact hostname only — reject 127.0.0.1.evil.example and userinfo forms.
    if parsed.hostname not in ("127.0.0.1", "localhost"):
        raise NotLocalRPC(f"not local rpc: {url}")
    return url
