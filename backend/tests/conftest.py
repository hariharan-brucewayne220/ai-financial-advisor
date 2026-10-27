"""
Shared test setup.

Settings are read from the environment at import time (get_settings() is
lru_cached), so the minimum required variables are set here before any
app module is imported. No test talks to a real model provider.
"""

import os

os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-not-a-real-key")
