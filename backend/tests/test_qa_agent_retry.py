"""
The QA graph's faithfulness retry loop must stop after
FAITHFULNESS_RETRY_LIMIT retries, even when every answer scores low.
"""

import pytest

from app.agents import financial_qa_agent as qa


class StubScorer:
    def __init__(self, score: float):
        self._score = score

    async def score(self, context: str, answer: str) -> float:
        return self._score


@pytest.fixture
def agent_factory(monkeypatch):
    calls = {"retrieve": 0}

    async def classify(self, state):
        return {"query_type": "simple_qa", "requires_retrieval": True}

    async def retrieve(self, state):
        calls["retrieve"] += 1
        return {"retrieved_chunks": [
            {"id": "c1", "content": "The fee is 0.5%.", "score": 1.0,
             "document_id": "d1", "metadata": {}},
        ]}

    async def market(self, state):
        return {"market_data_context": ""}

    async def generate(self, state):
        return {"generated_response": "The fee is 0.5%.", "generation_metadata": {}}

    monkeypatch.setattr(qa.FinancialQAAgent, "_classify_query", classify)
    monkeypatch.setattr(qa.FinancialQAAgent, "_retrieve_documents", retrieve)
    monkeypatch.setattr(qa.FinancialQAAgent, "_fetch_market_data", market)
    monkeypatch.setattr(qa.FinancialQAAgent, "_generate_response", generate)

    def make(score: float):
        monkeypatch.setattr(qa, "FaithfulnessScorer", lambda: StubScorer(score))
        return qa.FinancialQAAgent(db_session=None)

    return make, calls


def _initial_state():
    return {"query": "What is the fee?", "client_id": "c", "retry_count": 0}


async def test_low_score_retries_up_to_limit_then_stops(agent_factory):
    make, calls = agent_factory
    agent = make(score=0.1)

    final = await agent.invoke(_initial_state())

    limit = qa.settings.faithfulness_retry_limit
    assert calls["retrieve"] == 1 + limit
    assert final["retry_count"] == limit
    assert final["final_response"] == "The fee is 0.5%."


async def test_high_score_does_not_retry(agent_factory):
    make, calls = agent_factory
    agent = make(score=0.9)

    final = await agent.invoke(_initial_state())

    assert calls["retrieve"] == 1
    assert final["confidence"] == 0.9
