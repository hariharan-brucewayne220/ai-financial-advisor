"""
JWT Authentication Module

Handles encoding/decoding JWT tokens for advisor authentication.
Provides dependency injection for route protection.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict
from uuid import UUID

from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi import Request

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

security = HTTPBearer(auto_error=False)


def create_access_token(advisor_id: str, advisor_email: str, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create JWT access token for advisor.

    Args:
        advisor_id: UUID of advisor
        advisor_email: Email address of advisor
        expires_delta: Optional custom expiration time

    Returns:
        Encoded JWT token
    """
    if expires_delta is None:
        expires_delta = timedelta(hours=settings.jwt_expiration_hours)

    expire = datetime.now(timezone.utc) + expires_delta

    payload = {
        "advisor_id": str(advisor_id),
        "advisor_email": advisor_email,
        "exp": expire,
        "type": "access"
    }

    encoded_jwt = jwt.encode(
        payload,
        settings.secret_key,
        algorithm=settings.jwt_algorithm
    )

    logger.info(f"Created access token for {advisor_email}")
    return encoded_jwt


def create_refresh_token(advisor_id: str, advisor_email: str) -> str:
    """
    Create JWT refresh token for advisor.

    Args:
        advisor_id: UUID of advisor
        advisor_email: Email address of advisor

    Returns:
        Encoded JWT refresh token
    """
    expires_delta = timedelta(days=settings.jwt_refresh_expiration_days)
    expire = datetime.now(timezone.utc) + expires_delta

    payload = {
        "advisor_id": str(advisor_id),
        "advisor_email": advisor_email,
        "exp": expire,
        "type": "refresh"
    }

    encoded_jwt = jwt.encode(
        payload,
        settings.secret_key,
        algorithm=settings.jwt_algorithm
    )

    logger.info(f"Created refresh token for {advisor_email}")
    return encoded_jwt


def decode_token(token: str) -> Dict:
    """
    Decode and validate JWT token.

    Args:
        token: JWT token string

    Returns:
        Decoded payload with advisor_id, advisor_email, exp

    Raises:
        JWTError: If token is invalid or expired
    """
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm]
        )
        return payload
    except JWTError as e:
        logger.warning(f"Invalid token: {e}")
        raise


async def get_current_advisor(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    request: Request = None,
) -> Dict:
    """
    **REAL AUTHENTICATION:**
    Validate JWT token and extract current advisor.

    This is the actual authorization check - verifies token validity and expiration.

    Used as dependency:
    ```python
    async def protected_route(
        current_advisor: Dict = Depends(get_current_advisor)
    ):
        advisor_id = current_advisor["advisor_id"]
        advisor_email = current_advisor["advisor_email"]
    ```

    Args:
        credentials: HTTP Bearer token from Authorization header

    Returns:
        Dict with advisor_id and advisor_email

    Raises:
        HTTPException(401): If token is invalid or expired
    """
    token = None
    if credentials:
        token = credentials.credentials
    elif request is not None:
        token = request.query_params.get("token")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_token(token)

        advisor_id = payload.get("advisor_id")
        advisor_email = payload.get("advisor_email")
        token_type = payload.get("type")

        if not advisor_id or not advisor_email:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing advisor information",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if token_type != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type. Must be access token.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        logger.info(f"Authenticated advisor: {advisor_email}")

        return {
            "advisor_id": advisor_id,
            "advisor_email": advisor_email
        }

    except JWTError as e:
        logger.warning(f"Token validation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error validating token: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed",
            headers={"WWW-Authenticate": "Bearer"},
        )
