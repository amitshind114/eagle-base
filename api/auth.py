"""FastAPI authentication dependency — X-API-Key header guard.

Usage (in main.py)::

    from api.auth import require_api_key
    from fastapi import Depends

    app.include_router(
        live_router.router,
        prefix="/api/live",
        tags=["Live Trading"],
        dependencies=[Depends(require_api_key)],
    )

The key is read from Settings.api_key (env var: API_KEY).
If API_KEY is not set the app starts in WARNING mode and all
requests are allowed — this keeps local dev friction-free while
enforcing auth in any deployment where API_KEY is configured.

Generate a key::

    python -c "import secrets; print(secrets.token_hex(32))"
"""

from __future__ import annotations

import logging

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from core.config import settings

log = logging.getLogger("api.auth")

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

# Warn once at import time if key is not configured
if not settings.api_key:
    log.warning(
        "[auth] API_KEY is not set — /api/live and /api/paper are UNPROTECTED. "
        "Set API_KEY in .env before deploying to production."
    )


def require_api_key(key: str | None = Security(_API_KEY_HEADER)) -> str:
    """FastAPI dependency — enforce X-API-Key on sensitive routes.

    - If API_KEY env var is empty (dev mode): always passes through.
    - If API_KEY is set: key must match exactly or 401 is returned.

    Returns the validated key string (can be ignored by the endpoint).
    """
    if not settings.api_key:
        # Dev / CI mode — no key configured, allow all
        return ""

    if key and key == settings.api_key:
        return key

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing X-API-Key header.",
        headers={"WWW-Authenticate": "ApiKey"},
    )
