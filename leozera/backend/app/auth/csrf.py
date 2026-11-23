from urllib.parse import urlparse

from fastapi import Request

from app.core.config import get_settings


def request_origin(request: Request) -> str | None:
    origin = request.headers.get("origin")
    if origin:
        return origin.strip()
    referer = request.headers.get("referer")
    if not referer:
        return None
    parsed = urlparse(referer.strip())
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def origin_is_allowed(request: Request) -> bool:
    candidate = request_origin(request)
    return candidate is not None and candidate in get_settings().allowed_origins
