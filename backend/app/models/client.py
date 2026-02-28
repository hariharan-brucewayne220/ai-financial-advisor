"""Client model - represents financial advisor clients."""

from datetime import datetime
from uuid import uuid4
from typing import Optional

from sqlalchemy import Column, String, DateTime, DECIMAL, Index, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.models.base import Base


class Client(Base):
    """
    Client model for financial advisor clients.

    Each client belongs to an advisor and has documents, conversations, and reports.
    Clients are the primary focus of the RAG system - all retrieval is scoped to a client.
    """

    __tablename__ = "clients"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    advisor_id = Column(UUID(as_uuid=True), ForeignKey("advisors.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    email = Column(String(255), index=True)
    risk_profile = Column(String(50), default="moderate", nullable=False)  # low, moderate, high, aggressive
    portfolio_value = Column(DECIMAL(20, 2))
    custom_metadata = Column(JSONB, default={})  # Custom fields, notes, etc.
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    advisor = relationship("Advisor", back_populates="clients")
    documents = relationship("Document", back_populates="client", cascade="all, delete-orphan")
    conversations = relationship("Conversation", back_populates="client", cascade="all, delete-orphan")
    reports = relationship("Report", back_populates="client", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="client")

    # Indexes
    __table_args__ = (
        Index("idx_clients_advisor_id", "advisor_id"),
        Index("idx_clients_email", "email"),
    )

    def __repr__(self) -> str:
        return f"<Client(id={self.id}, name={self.name}, risk={self.risk_profile})>"
