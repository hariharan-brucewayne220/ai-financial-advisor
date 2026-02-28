"""
ARQ Worker - Async job queue for document ingestion and embeddings

Handles long-running tasks asynchronously:
- Document parsing (PDF/CSV/Excel)
- PII detection
- Chunking
- Embedding generation
- Vector indexing
"""

import logging
from arq.connections import RedisSettings

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


async def startup(ctx):
    """Called when worker starts."""
    logger.info("Worker starting up")


async def shutdown(ctx):
    """Called when worker shuts down."""
    logger.info("Worker shutting down")


async def health_check():
    """Health check function registered with ARQ."""
    logger.info("Worker health check executed")
    return {"status": "healthy"}


# ARQ Worker Configuration
class WorkerSettings:
    """ARQ worker configuration."""

    # Redis configuration
    redis_settings = RedisSettings(
        host='redis',
        port=6379,
        database=1,
    )

    # Worker settings
    max_jobs = 10
    job_timeout = settings.arq_job_timeout_seconds

    on_startup = startup
    on_shutdown = shutdown

    # Register the health_check function
    functions = [health_check]


# Export for ARQ to find
settings_obj = WorkerSettings()

if __name__ == "__main__":
    from arq import run_worker
    import asyncio
    asyncio.run(run_worker())
