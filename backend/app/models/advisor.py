"""Advisor model - represents financial advisors who use the system."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, String, Boolean, DateTime, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.base import Base


class Advisor(Base):
    """
    Advisor model for financial advisors who use the system.

    Advisors are the primary users - each advisor has multiple clients,
    and can access all documents/conversations/reports for their clients.
    """

    __tablename__ = "advisors"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    clients = relationship("Client", back_populates="advisor", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="advisor")

    # Indexes
    __table_args__ = (
        Index("idx_advisors_email", "email"),
    )

    def __repr__(self) -> str:
        return f"<Advisor(id={self.id}, email={self.email}, name={self.full_name})>"
