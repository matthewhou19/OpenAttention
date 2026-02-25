"""Optional bearer token authentication for AttentionOS API.

If ATTENTIONOS_TOKEN is set in the environment, all API routes require
Authorization: Bearer <token>. If unset or empty, the API is open (dev mode).
"""

import hmac
import os

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer_scheme = HTTPBearer(auto_error=False)


async def verify_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> None:
    """FastAPI dependency that enforces optional bearer auth."""
    token = os.environ.get("ATTENTIONOS_TOKEN", "").strip()
    if not token:
        # Dev mode — no token configured, allow all requests
        return

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    if not hmac.compare_digest(credentials.credentials, token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
