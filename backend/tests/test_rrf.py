"""Reciprocal Rank Fusion keeps its current behavior."""

from app.services.retriever import HybridRetriever, RetrievedChunk


def _chunk(chunk_id: str, method: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id="doc",
        content=f"content {chunk_id}",
        score=0.0,
        retrieval_method=method,
        metadata={},
    )


def test_chunk_found_by_both_methods_ranks_first():
    dense = [_chunk("a", "dense"), _chunk("b", "dense")]
    sparse = [_chunk("b", "bm25"), _chunk("c", "bm25")]

    fused = HybridRetriever._reciprocal_rank_fusion(dense, sparse, k=60)

    assert [c.chunk_id for c in fused] == ["b", "a", "c"]
    assert fused[0].score == 1 / 62 + 1 / 61
    assert all(c.retrieval_method == "hybrid" for c in fused)


def test_empty_inputs_give_empty_output():
    assert HybridRetriever._reciprocal_rank_fusion([], []) == []
