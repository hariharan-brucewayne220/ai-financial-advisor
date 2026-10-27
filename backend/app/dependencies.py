"""
Dependency Injection for FastAPI

Provides database sessions, current user context, and other shared dependencies.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from fastapi import Depends, HTTPException, status
from jose import JWTError
import logging

from app.config import get_settings
from app.models import Base

logger = logging.getLogger(__name__)
settings = get_settings()

# ============================================================================
# DATABASE SESSION MANAGEMENT
# ============================================================================

# Create async SQLAlchemy engine
engine = create_async_engine(
    settings.database_url,
    echo=settings.sqlalchemy_echo,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_recycle=settings.db_pool_recycle,
    pool_pre_ping=settings.db_pool_pre_ping,
)

# Session factory
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db():
    """Initialize database tables."""
    async with engine.begin() as conn:
        # The Vector column type needs pgvector. Docker Compose creates it in
        # scripts/init_db.sql; managed Postgres (Azure) starts without it.
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        # Create all tables from models
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database initialized")


async def get_db() -> AsyncSession:
    """
    Get database session for request.

    Used as dependency: async def endpoint(db: AsyncSession = Depends(get_db))
    Automatically closes session after request completes.
    """
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()


# ============================================================================
# AUTHENTICATION DEPENDENCIES
# ============================================================================

# Import real JWT authentication functions
from app.auth import get_current_advisor


async def verify_client_ownership(
    client_id: str,
    db: AsyncSession = Depends(get_db),
    current_advisor: dict = Depends(get_current_advisor),
) -> dict:
    """
    **Multi-tenancy Isolation - ENFORCED:**
    Verify that current advisor owns the requested client.

    **SECURITY:** This dependency enforces client ownership. Any endpoint that
    accepts client_id MUST use this dependency to prevent cross-tenant access.

    Args:
        client_id: UUID string of client being accessed
        db: Database session
        current_advisor: Authenticated advisor from JWT token

    Returns:
        Client object if ownership verified

    Raises:
        HTTPException(404) if client not found
        HTTPException(403) if advisor doesn't own the client
        HTTPException(401) if not authenticated (delegated to get_current_advisor)
    """
    from uuid import UUID
    from app.models.client import Client

    try:
        # Fetch the client
        client = await db.get(Client, UUID(client_id))
        if not client:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Client {client_id} not found",
            )

        # **REAL OWNERSHIP CHECK:**
        # Verify that the client belongs to the authenticated advisor
        if str(client.advisor_id) != current_advisor["advisor_id"]:
            logger.warning(
                f"Access denied: Advisor {current_advisor['advisor_email']} "
                f"attempted to access client {client_id} owned by {client.advisor_id}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this client",
            )

        logger.info(
            f"Access granted: Advisor {current_advisor['advisor_email']} "
            f"accessing client {client_id}"
        )

        return client

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error verifying client ownership: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error verifying access",
        )
