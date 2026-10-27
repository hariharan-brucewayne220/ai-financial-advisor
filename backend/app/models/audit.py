"""AuditLog model for compliance and usage tracking."""

from datetime import datetime
from uuid import uuid4
from typing import Optional, List

from sqlalchemy import Column, String, DateTime, Text, Integer, Index, ForeignKey, NUMERIC, text
from sqlalchemy.dialects.postgresql import UUID, ARRAY, JSONB
from sqlalchemy.orm import relationship

from app.models.base import Base


class AuditLog(Base):
    """
    AuditLog model for compliance audit trail.

    Append-only audit trail for regulated financial domain.
    Records every LLM query, response, token usage, and retrieval decisions.
    This table is never deleted from - only appended to.
    """

    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    advisor_id = Column(UUID(as_uuid=True), ForeignKey("advisors.id", ondelete="RESTRICT"), nullable=False)
    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False)
    action = Column(String(100), nullable=False, index=True)  # query_answered, report_generated, document_uploaded
    prompt_text = Column(Text)  # Full prompt sent to LLM
    response_text = Column(Text)  # Full response from LLM
    input_tokens = Column(Integer)
    output_tokens = Column(Integer)
    total_tokens = Column(Integer)
    latency_ms = Column(Integer)
    model_used = Column(String(100))  # gpt-4o, text-embedding-3-small, etc.
    doc_ids_retrieved = Column(ARRAY(UUID(as_uuid=True)), default=[])  # Which documents were used
    retrieval_method = Column(String(50))  # hybrid, dense, bm25
    faithfulness_score = Column(NUMERIC(5, 4))  # 0.0000 - 1.0000 (NLI entailment)
    compression_ratio = Column(NUMERIC(5, 4))  # (original - compressed) / original
    cost_usd = Column(NUMERIC(12, 6))

    # Market Data Audit
    market_data_symbols = Column(ARRAY(String), default=[])  # Stock symbols queried
    market_data_available = Column(String(20))  # "success", "failed", "unavailable", "not_applicable"
    market_data_errors = Column(ARRAY(String), default=[])  # Error messages if market data fetch failed
    market_data_timestamp = Column(DateTime(timezone=True))  # When market data was retrieved

    # PII Audit
    pii_detected_count = Column(Integer, default=0)  # Number of PII entities detected and redacted
    pii_types_found = Column(ARRAY(String), default=[])  # ["PERSON", "EMAIL", "PHONE_NUMBER", ...]
    pii_redaction_applied = Column(String(20), default="none")  # "none", "partial", "full"

    # Data Quality
    retrieval_empty = Column(String(20), default="no")  # "yes" if no sources found, "no" if sources exist
    sources_grounded = Column(String(20), default="yes")  # "yes" if response backed by sources, "no" if hallucinated

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False, index=True)

    # Relationships
    advisor = relationship("Advisor", back_populates="audit_logs")
    client = relationship("Client", back_populates="audit_logs")

    # Indexes
    __table_args__ = (
        Index("idx_audit_logs_advisor_id", "advisor_id"),
        Index("idx_audit_logs_client_id", "client_id"),
        Index("idx_audit_logs_created_at", text("created_at DESC")),
        Index("idx_audit_logs_action", "action"),
    )

    def __repr__(self) -> str:
        return f"<AuditLog(id={self.id}, action={self.action}, tokens={self.total_tokens})>"
