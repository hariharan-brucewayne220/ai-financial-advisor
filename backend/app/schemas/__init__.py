"""Pydantic schemas for request/response validation."""

from pydantic import BaseModel, Field
from typing import Optional, List
from uuid import UUID
from datetime import datetime


# ============================================================================
# MESSAGE SCHEMAS
# ============================================================================

class MessageCreate(BaseModel):
    """Schema for creating a new message."""
    content: str = Field(..., min_length=1, max_length=10000)


class MessageResponse(BaseModel):
    """Schema for message response."""
    id: UUID
    role: str
    content: str
    faithfulness_score: Optional[float] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# CONVERSATION SCHEMAS
# ============================================================================

class ConversationCreate(BaseModel):
    """Schema for creating a conversation."""
    title: Optional[str] = None


class ConversationResponse(BaseModel):
    """Schema for conversation response."""
    id: UUID
    title: Optional[str]
    created_at: datetime
    updated_at: datetime
    messages: List[MessageResponse] = []

    class Config:
        from_attributes = True
        # Avoid loading lazy relationships in async context
        populate_by_name = True


# ============================================================================
# DOCUMENT SCHEMAS
# ============================================================================

class DocumentStatus(BaseModel):
    """Schema for document upload status."""
    id: UUID
    file_name: str
    status: str  # pending, processing, indexed, failed
    chunk_count: int
    pii_detected: bool
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
