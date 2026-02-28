"""
Services module for RAG, embeddings, and document processing.
"""

from app.services.retriever import HybridRetriever, RetrievedChunk
from app.services.embedder import EmbedderService, EmbedderCache
from app.services.chunker import ChunkerService, SmartChunker
from app.services.document_parser import DocumentParser
from app.services.pii_detector import PIIDetector, PIIEntity
from app.services.faithfulness_scorer import FaithfulnessScorer, FactualConsistencyChecker

__all__ = [
    "HybridRetriever",
    "RetrievedChunk",
    "EmbedderService",
    "EmbedderCache",
    "ChunkerService",
    "SmartChunker",
    "DocumentParser",
    "PIIDetector",
    "PIIEntity",
    "FaithfulnessScorer",
    "FactualConsistencyChecker",
]
