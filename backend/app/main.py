"""
FastAPI Application Factory

Entry point for the AI Financial Advisor backend.
Sets up routes, middleware, dependencies, and lifespan events.
"""

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import get_settings
from app.dependencies import init_db, get_db

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = get_settings()


# ============================================================================
# LIFESPAN EVENT HANDLERS
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup/shutdown events.

    Runs once when app starts and when it shuts down.
    Used to initialize database, load models, set up caches, etc.
    """
    # STARTUP
    logger.info("Starting AI Financial Advisor")
    logger.info(f"Environment: {settings.fastapi_env}")
    logger.info(f"Debug mode: {settings.fastapi_debug}")

    # Initialize database
    try:
        await init_db()
        logger.info("✓ Database initialized")
    except Exception as e:
        logger.error(f"✗ Database initialization failed: {e}")
        raise

    logger.info("✓ Application startup complete")

    yield

    # SHUTDOWN
    logger.info("Shutting down application")
    # Cleanup can go here (close connections, etc.)
    logger.info("✓ Application shutdown complete")


# ============================================================================
# APPLICATION FACTORY
# ============================================================================

def create_app() -> FastAPI:
    """
    Create and configure FastAPI application.

    Factory pattern allows testing and multiple instances.
    """
    app = FastAPI(
        title=settings.api_title,
        version=settings.api_version,
        debug=settings.fastapi_debug,
        lifespan=lifespan,
    )

    # ====================================================================
    # MIDDLEWARE
    # ====================================================================

    # CORS middleware - allow frontend requests
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    # ====================================================================
    # ROUTERS
    # ====================================================================

    # Health check endpoint
    @app.get("/health")
    async def health_check():
        """Simple health check endpoint."""
        return {
            "status": "healthy",
            "environment": settings.fastapi_env,
        }

    @app.get("/health/full")
    async def health_full(db=Depends(get_db)):
        """Health check with DB and Redis connectivity."""
        db_ok = False
        redis_ok = False
        try:
            await db.execute(text("SELECT 1"))
            db_ok = True
        except Exception:
            db_ok = False

        try:
            import redis.asyncio as redis
            r = redis.from_url(settings.redis_url)
            pong = await r.ping()
            redis_ok = bool(pong)
            await r.close()
        except Exception:
            redis_ok = False

        return {
            "status": "healthy" if (db_ok and redis_ok) else "degraded",
            "database": db_ok,
            "redis": redis_ok,
        }

    @app.get("/health/market-data")
    async def health_market_data():
        """Health check for Alpha Vantage MCP/REST availability."""
        from app.services.market_data import MarketDataService
        service = MarketDataService()
        status = service.get_status()
        return {
            "status": "healthy" if status.get("available") else "degraded",
            "market_data": status,
        }

    # Proxy-friendly health endpoints under /api
    @app.get("/api/health/full")
    async def health_full_api(db=Depends(get_db)):
        return await health_full(db)

    @app.get("/api/health/market-data")
    async def health_market_data_api():
        return await health_market_data()

    # Version endpoint
    @app.get("/version")
    async def version():
        """Get API version."""
        return {
            "version": settings.api_version,
        }

    # Include API routers
    from app.api import conversations, documents, reports, clients, auth
    app.include_router(auth.router, prefix="/api")
    app.include_router(clients.router, prefix="/api")
    app.include_router(conversations.router, prefix="/api")
    app.include_router(documents.router, prefix="/api")
    app.include_router(reports.router, prefix="/api")

    return app


# Create app instance
app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.fastapi_debug,
        log_level="info",
    )
