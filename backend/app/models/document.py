"""Document and DocumentChunk models for stored financial documents."""

from datetime import datetime
from uuid import uuid4
from typing import Optional, List

from sqlalchemy import Column, String, DateTime, BIGINT, Integer, Index, ForeignKey, Text, Boolean
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from pgvector.sqlalchemy import Vector
from sqlalchemy.orm import relationship

from app.models.base import Base


class Document(Base):
    """
    Document model for uploaded financial documents.

    Tracks documents uploaded by advisors for their clients.
    Status tracks ingestion pipeline: pending -> processing -> indexed -> failed.
    PII detection results are stored in pii_entities JSONB.
    """

    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    file_name = Column(String(255), nullable=False)
    file_type = Column(String(50), nullable=False)  # pdf, csv, xlsx, txt
    s3_key = Column(String(1024), nullable=False)
    file_size_bytes = Column(BIGINT)
    status = Column(String(50), default="pending", index=True, nullable=False)  # pending, processing, indexed, failed
    error_message = Column(Text)
    pii_detected = Column(Boolean, default=False)
    pii_entities = Column(JSONB, default=[])  # [{type, value, start, end}, ...]
    chunk_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    client = relationship("Client", back_populates="documents")
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")

    # Indexes
    __table_args__ = (
        Index("idx_documents_client_id", "client_id"),
        Index("idx_documents_status", "status"),
        Index("idx_documents_created_at", "created_at", postgresql_using="DESC"),
    )

    def __repr__(self) -> str:
        return f"<Document(id={self.id}, name={self.file_name}, status={self.status})>"


class DocumentChunk(Base):
    """
    DocumentChunk model for document segments.

    Stores embeddings, BM25 tokens, and metadata for each chunk.
    The HNSW index on embedding provides fast approximate nearest neighbor search.
    """

    __tablename__ = "document_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    content_length = Column(Integer)
    embedding = Column(Vector(1536), nullable=False)  # text-embedding-3-small: 1536 dims
    bm25_tokens = Column(ARRAY(String), default=[])  # Tokenized text for BM25 search
    chunk_metadata = Column(JSONB, default={})  # page numbers, section titles, etc.
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    # Relationships
    document = relationship("Document", back_populates="chunks")

    # Indexes
    __table_args__ = (
        Index("idx_document_chunks_document_id", "document_id"),
        Index("idx_document_chunks_embedding", "embedding", postgresql_using="hnsw"),
        Index("idx_document_chunks_bm25_tokens", "bm25_tokens", postgresql_using="gin"),
    )

    def __repr__(self) -> str:
        return f"<DocumentChunk(id={self.id}, doc_id={self.document_id}, idx={self.chunk_index})>"
