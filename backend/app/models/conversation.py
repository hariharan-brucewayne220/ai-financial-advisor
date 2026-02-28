"""Conversation and Message models for chat-based interactions."""

from datetime import datetime
from uuid import uuid4
from typing import Optional, List

from sqlalchemy import Column, String, DateTime, Text, Index, ForeignKey, NUMERIC
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import relationship

from app.models.base import Base


class Conversation(Base):
    """
    Conversation model for grouped messages with a client.

    Each conversation is a session where an advisor and the system
    discuss a client's financial situation.
    """

    __tablename__ = "conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255))
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    client = relationship("Client", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")

    # Indexes
    __table_args__ = (
        Index("idx_conversations_client_id", "client_id"),
    )

    def __repr__(self) -> str:
        return f"<Conversation(id={self.id}, client_id={self.client_id}, title={self.title})>"


class Message(Base):
    """
    Message model for individual messages in a conversation.

    Tracks user and assistant messages with retrieval metadata and quality scores.
    Retrieved chunk IDs link back to the source documents used for RAG.
    Faithfulness score measures whether the answer is grounded in retrieved context.

    **Audit Trail:**
    - retrieved_chunk_ids: Which document chunks were used
    - retrieved_at: Timestamp when documents were retrieved (data freshness)
    - market_data_symbols: Which stock symbols were queried for market data
    - market_data_available: Whether market data was successfully fetched
    - data_sources_json: JSON audit of all data sources used (documents + market + timestamps)
    """

    __tablename__ = "messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(20), nullable=False)  # user, assistant
    content = Column(Text, nullable=False)
    retrieved_chunk_ids = Column(ARRAY(UUID(as_uuid=True)), default=[])  # Which chunks were used
    faithfulness_score = Column(NUMERIC(5, 4))  # 0.0000 - 1.0000 (NLI entailment)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False, index=True)

    # Audit Trail - Data Source Tracking
    retrieved_at = Column(DateTime(timezone=True))  # When documents were retrieved (freshness)
    market_data_symbols = Column(ARRAY(String), default=[])  # Stock symbols queried
    market_data_available = Column(String(20))  # "success", "failed", "unavailable", "not_applicable"
    data_sources_json = Column(Text)  # Full audit: {documents: [...], market_data: {...}, timestamps: {...}}

    # Relationships
    conversation = relationship("Conversation", back_populates="messages")

    # Indexes
    __table_args__ = (
        Index("idx_messages_conversation_id", "conversation_id"),
        Index("idx_messages_created_at", "created_at", postgresql_using="DESC"),
    )

    def __repr__(self) -> str:
        return f"<Message(id={self.id}, role={self.role}, conv_id={self.conversation_id})>"
