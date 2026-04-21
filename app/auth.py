"""
JWT authentication middleware and endpoints.

Provides:
  - POST /api/v1/auth/login   — exchange credentials for a JWT
  - POST /api/v1/auth/refresh — exchange a valid JWT for a new one with extended expiry
  - get_current_user          — FastAPI dependency that validates Bearer tokens (OPTIONAL)
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import BaseModel

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Configuration (read from environment with safe defaults)
# ---------------------------------------------------------------------------
JWT_SECRET: str = os.getenv("JWT_SECRET", "dev-secret-change-in-production")
JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_HOURS: int = 24

# ---------------------------------------------------------------------------
# Demo user store (replace with DB lookup in production)
# ---------------------------------------------------------------------------
_DEMO_USERS: dict[str, dict] = {
    "admin": {"username": "admin", "password": "admin123", "role": "admin"},
    "user":  {"username": "user",  "password": "user123",  "role": "user"},
}

# ---------------------------------------------------------------------------
# OAuth2 scheme — expects "Authorization: Bearer <token>" (auto_error=False makes it optional)
# ---------------------------------------------------------------------------
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserContext(BaseModel):
    username: str
    role: str


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------


def _create_access_token(username: str, role: str) -> str:
    """Create a signed JWT with sub, role, and exp claims."""
    expire = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {
        "sub": username,
        "role": role,
        "exp": expire,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _decode_token(token: str) -> dict:
    """
    Decode and validate a JWT.

    Raises HTTPException 401 if the token is invalid or expired.
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except JWTError as exc:
        logger.warning("jwt_decode_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


# ---------------------------------------------------------------------------
# FastAPI dependency - NOW OPTIONAL (returns None if no token provided)
# ---------------------------------------------------------------------------


def get_current_user(token: Annotated[Optional[str], Depends(oauth2_scheme)] = None) -> Optional[UserContext]:
    """
    Validate the Bearer token and return the authenticated user context.
    
    Returns None if no token is provided (authentication is optional).
    Raises HTTP 401 only if a token is provided but is invalid or expired.
    """
    if token is None:
        # No token provided - authentication is optional
        return None
    
    payload = _decode_token(token)

    username: str | None = payload.get("sub")
    role: str | None = payload.get("role")

    if not username or not role:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token payload is missing required claims",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return UserContext(username=username, role=role)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(credentials: LoginRequest) -> TokenResponse:
    """
    Authenticate with username + password and return a JWT.

    Requirements: 17.1
    """
    user = _DEMO_USERS.get(credentials.username)
    if user is None or user["password"] != credentials.password:
        logger.warning("login_failed", username=credentials.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = _create_access_token(username=user["username"], role=user["role"])
    logger.info("login_success", username=user["username"], role=user["role"])
    return TokenResponse(access_token=token)


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(
    current_user: Annotated[Optional[UserContext], Depends(get_current_user)],
) -> TokenResponse:
    """
    Accept a valid Bearer token and return a new token with extended expiration.

    Requirements: 17.2
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = _create_access_token(
        username=current_user.username,
        role=current_user.role,
    )
    logger.info("token_refreshed", username=current_user.username)
    return TokenResponse(access_token=token)
