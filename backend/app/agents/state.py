"""
Shared Agent State Definition

**Why TypedDict for state?**
- Type-safe: Python type checker catches errors
- Self-documenting: State structure is clear
- LangGraph-compatible: nodes pass state between them

**State Flow:**
User Query → Classify → Retrieve → Rerank → Compress → Fetch Market Data → Generate → Score → Format → Return
"""

from typing import TypedDict, Optional, List, Any
from uuid import UUID


class AgentState(TypedDict, total=False):
    """
    Shared state passed between LangGraph nodes.

    Each node can read and modify this state.
    Similar to Redux in web development - single source of truth.
    """

    # Input
    query: str
    client_id: str
    user_id: str

    # Classification
    query_type: str  # simple_qa, analysis, recommendation, retrieval
    requires_retrieval: bool

    # Retrieval
    retrieved_chunks: List[dict]  # [{id, content, score, source}, ...]
    retrieval_method: str  # dense, sparse, hybrid

    # Reranking
    reranked_chunks: List[dict]
    reranked_count: int

    # Compression
    original_context_length: int
    compressed_context: str
    compression_ratio: float

    # Market Data Enrichment
    market_data_context: str  # Real-time prices, technicals, fundamentals
    market_symbols_queried: List[str]  # Stock symbols queried
    market_data_errors: Optional[List[str]]  # API errors if any
    market_data_available: str  # "success", "failed", "unavailable", "not_applicable"
    market_data_timestamp: Optional[str]  # ISO timestamp of when market data was fetched

    # Generation
    generated_response: str
    generation_metadata: dict  # {model, tokens, latency, ...}

    # Scoring
    faithfulness_score: float  # 0.0-1.0
    should_retry: bool
    retry_count: int
    retry_reason: Optional[str]

    # Audit
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float
    latency_ms: int

    # Final output
    final_response: str
    sources: List[str]  # Cited chunk IDs
    confidence: float

    # Error handling
    error: Optional[str]
    error_type: Optional[str]


class ReportGenerationState(TypedDict, total=False):
    """
    State for ReportWriterAgent.

    Orchestrates multi-step report generation with self-review.
    """

    # Input
    client_id: str
    report_type: str  # portfolio_summary, risk_assessment, client_email
    client_data: dict

    # Generation steps
    gathered_data: dict  # Financial snapshot
    risk_analysis: dict  # Risks identified
    draft_report: str  # Markdown draft
    self_review: dict  # {claims, unsupported_count, revision_needed}
    revised_draft: Optional[str]
    final_report: str  # Finalized markdown
    html_output: str

    # Metadata
    generation_metadata: dict
    total_iterations: int
    total_tokens: int
