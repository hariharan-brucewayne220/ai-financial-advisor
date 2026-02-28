"""Base SQLAlchemy model setup."""

from sqlalchemy.orm import declarative_base

# Declarative base for all ORM models
# Used by Alembic for auto-generating migrations
Base = declarative_base()
