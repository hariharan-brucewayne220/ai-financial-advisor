"""Eval harness: metric math, question ground truth and token metering."""

import json

import httpx2
import pytest

from eval import metrics


def test_recall_hit_and_rr():
    retrieved = ["a", "b", "c", "d", "e", "f"]
    assert metrics.recall_at_k(retrieved, ["b", "f"], k=5) == 0.5
    assert metrics.hit_at_k(retrieved, ["f"], k=5) == 0.0
    assert metrics.hit_at_k(retrieved, ["e"], k=5) == 1.0
    assert metrics.reciprocal_rank(retrieved, ["c"], k=5) == pytest.approx(1 / 3)
    assert metrics.reciprocal_rank(retrieved, ["z"], k=5) == 0.0


def test_recall_needs_ground_truth():
    with pytest.raises(ValueError):
        metrics.recall_at_k(["a"], [], k=5)


def test_percentile_matches_numpy_linear():
    values = [10, 20, 30, 40]
    assert metrics.percentile(values, 50) == 25
    assert metrics.percentile(values, 95) == pytest.approx(38.5)
    assert metrics.percentile([7], 95) == 7


def test_cost_uses_per_million_prices():
    usage = {"gpt-4o-mini": {"input": 1_000_000, "output": 500_000}}
    prices = {"gpt-4o-mini": {"input": 0.15, "output": 0.60}}
    assert metrics.cost_usd(usage, prices) == pytest.approx(0.45)
    with pytest.raises(KeyError):
        metrics.cost_usd({"unknown": {"input": 1}}, prices)


async def test_every_question_maps_to_chunks():
    """Guards the ground truth if the parser or chunker changes."""
    from eval.corpus import MAX_RELEVANT_CHUNKS, load_chunks, load_questions

    chunks = await load_chunks()
    questions = load_questions(chunks)

    assert 30 <= len(questions) <= 50
    assert len({q.id for q in questions}) == len(questions)
    assert all(1 <= len(q.relevant) <= MAX_RELEVANT_CHUNKS for q in questions)


async def test_usage_meter_counts_tokens_per_model():
    from openai import AsyncOpenAI
    from eval.run_eval import UsageMeter

    def handler(request):
        body = json.loads(request.content)
        if request.url.path.endswith("/embeddings"):
            return httpx2.Response(200, json={
                "object": "list", "model": body["model"],
                "data": [{"object": "embedding", "index": 0, "embedding": [0.0]}],
                "usage": {"prompt_tokens": 7, "total_tokens": 7},
            })
        return httpx2.Response(200, json={
            "id": "x", "object": "chat.completion", "created": 0, "model": body["model"],
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": "ok"}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14},
        })

    client = AsyncOpenAI(api_key="sk-test", max_retries=0,
                         http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))
    meter = UsageMeter(client)

    await client.embeddings.create(model="emb", input="hi")
    await client.chat.completions.create(model="chat", messages=[{"role": "user", "content": "hi"}])
    await client.chat.completions.create(model="chat", messages=[{"role": "user", "content": "hi"}])

    assert meter.take() == {"emb": {"input": 7, "output": 0}, "chat": {"input": 22, "output": 6}}
    assert meter.take() == {}
