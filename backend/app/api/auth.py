"""
Auth Router - Advisor registration and login

Provides JWT access tokens for authenticated requests.
"""

import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from passlib.context import CryptContext

from app.dependencies import get_db
from app.models.advisor import Advisor
from app.auth import create_access_token, create_refresh_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


class RegisterRequest(BaseModel):
    email: str
    password: str
    full_name: str


class LoginRequest(BaseModel):
    email: str
    password: str


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    advisor_id: str
    advisor_email: str


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password, hashed)


@router.post("/register", response_model=AuthResponse)
async def register_advisor(
    payload: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Register a new advisor and return JWT tokens.
    """
    stmt = select(Advisor).where(Advisor.email == payload.email)
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Advisor already exists",
        )

    advisor = Advisor(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
    )
    db.add(advisor)
    await db.commit()
    await db.refresh(advisor)

    access_token = create_access_token(advisor.id, advisor.email)
    refresh_token = create_refresh_token(advisor.id, advisor.email)

    return AuthResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        advisor_id=str(advisor.id),
        advisor_email=advisor.email,
    )


@router.post("/login", response_model=AuthResponse)
async def login_advisor(
    payload: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Authenticate advisor and return JWT tokens.
    """
    stmt = select(Advisor).where(Advisor.email == payload.email)
    result = await db.execute(stmt)
    advisor = result.scalar_one_or_none()
    if not advisor or not verify_password(payload.password, advisor.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(advisor.id, advisor.email)
    refresh_token = create_refresh_token(advisor.id, advisor.email)

    return AuthResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        advisor_id=str(advisor.id),
        advisor_email=advisor.email,
    )
