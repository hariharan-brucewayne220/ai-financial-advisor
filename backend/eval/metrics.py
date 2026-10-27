"""Pure metric helpers for the eval (unit-tested in tests/test_eval_metrics.py)."""

import math
from typing import Dict, Iterable, List, Sequence


def recall_at_k(retrieved: Sequence[str], relevant: Iterable[str], k: int = 5) -> float:
    """Share of the question's relevant chunks that appear in the top k."""
    relevant = set(relevant)
    if not relevant:
        raise ValueError("question has no relevant chunks")
    return len(relevant & set(retrieved[:k])) / len(relevant)


def hit_at_k(retrieved: Sequence[str], relevant: Iterable[str], k: int = 5) -> float:
    """1.0 if any relevant chunk is in the top k, else 0.0."""
    return 1.0 if set(relevant) & set(retrieved[:k]) else 0.0


def reciprocal_rank(retrieved: Sequence[str], relevant: Iterable[str], k: int = 5) -> float:
    relevant = set(relevant)
    for rank, key in enumerate(retrieved[:k], 1):
        if key in relevant:
            return 1.0 / rank
    return 0.0


def percentile(values: List[float], p: float) -> float:
    """Linear-interpolation percentile (same as numpy's default)."""
    if not values:
        raise ValueError("no values")
    ordered = sorted(values)
    pos = (len(ordered) - 1) * p / 100
    lo, hi = math.floor(pos), math.ceil(pos)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def cost_usd(usage: Dict[str, Dict[str, int]], prices: Dict[str, Dict[str, float]]) -> float:
    """usage: {model: {"input": tokens, "output": tokens}}; prices per 1M tokens."""
    total = 0.0
    for model, tokens in usage.items():
        if model not in prices:
            raise KeyError(f"no price for model {model!r}; add it to eval/prices.json")
        total += tokens.get("input", 0) * prices[model]["input"] / 1e6
        total += tokens.get("output", 0) * prices[model]["output"] / 1e6
    return total
