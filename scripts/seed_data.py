"""
Seed Demo Data

Creates demo advisor, clients, and sample data for testing.
"""

import asyncio
from uuid import uuid4
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.config import get_settings
from app.models import Base, Advisor, Client
from passlib.context import CryptContext


settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


async def seed_data():
    """Populate database with demo data."""
    # Create engine
    engine = create_async_engine(settings.database_url)

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Create session
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Create demo advisor
        demo_advisor = Advisor(
            id=uuid4(),
            email="demo@example.com",
            hashed_password=pwd_context.hash("password123"),
            full_name="Demo Advisor",
            is_active=True,
        )
        session.add(demo_advisor)
        await session.flush()

        # Create demo clients
        clients_data = [
            {
                "name": "Alice Johnson",
                "email": "alice@example.com",
                "risk_profile": "moderate",
                "portfolio_value": 500000,
            },
            {
                "name": "Bob Smith",
                "email": "bob@example.com",
                "risk_profile": "aggressive",
                "portfolio_value": 750000,
            },
            {
                "name": "Carol Davis",
                "email": "carol@example.com",
                "risk_profile": "conservative",
                "portfolio_value": 250000,
            },
        ]

        for client_data in clients_data:
            client = Client(
                id=uuid4(),
                advisor_id=demo_advisor.id,
                **client_data,
            )
            session.add(client)

        await session.commit()

        print("✓ Demo data seeded successfully!")
        print(f"  - Advisor: {demo_advisor.email}")
        print(f"  - Clients: {len(clients_data)}")
        print("\nYou can now:")
        print("  1. Upload documents: POST /api/documents/{client_id}/upload")
        print("  2. Ask questions: POST /api/conversations/{client_id}/conversations/{id}/messages")
        print("  3. Generate reports: POST /api/reports/{client_id}/generate")


if __name__ == "__main__":
    asyncio.run(seed_data())
