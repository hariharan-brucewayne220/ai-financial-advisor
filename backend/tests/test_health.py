"""/health/full without Redis configured (the Azure deployment)."""

from fastapi.testclient import TestClient


def test_health_full_without_redis(monkeypatch):
    from app import main
    from app.dependencies import get_db

    class OkSession:
        async def execute(self, stmt):
            return None

    async def fake_db():
        yield OkSession()

    monkeypatch.setattr(main.settings, "redis_url", None)
    main.app.dependency_overrides[get_db] = fake_db
    try:
        # No "with": skips the lifespan, which needs a real database
        body = TestClient(main.app).get("/health/full").json()
    finally:
        main.app.dependency_overrides.clear()

    assert body == {"status": "healthy", "database": True, "redis": "not_configured"}
