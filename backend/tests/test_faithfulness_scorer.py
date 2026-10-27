"""
NLI faithfulness score.

The fast tests use a fake classifier so CI does not download the 1.6 GB
model. test_real_model_* runs facebook/bart-large-mnli when transformers
is installed (skipped otherwise).
"""

import importlib.util

import pytest

from app.services.faithfulness_scorer import FaithfulnessScorer, WINDOW_WORDS


def _nli(entail: float):
    rest = (1 - entail) / 2
    return [
        {"label": "entailment", "score": entail},
        {"label": "neutral", "score": rest},
        {"label": "contradiction", "score": rest},
    ]


class FakeClassifier:
    """Entailment 0.9 if the hypothesis's words all appear in the premise, else 0.1."""

    def __init__(self):
        self.calls = []

    def __call__(self, pairs, **kwargs):
        self.calls.append((pairs, kwargs))
        out = []
        for pair in pairs:
            premise = pair["text"].lower()
            words = [w.strip(".,") for w in pair["text_pair"].lower().split()]
            out.append(_nli(0.9 if all(w in premise for w in words) else 0.1))
        return out


async def test_mean_over_sentences_of_best_window():
    scorer = FaithfulnessScorer(classifier=FakeClassifier())
    score = await scorer.score(
        context="The fee is 0.5%. Stocks are 60%.",
        answer="The fee is 0.5%. The fund has no risk.",
    )
    assert score == pytest.approx((0.9 + 0.1) / 2)


async def test_citations_are_not_scored_as_claims():
    fake = FakeClassifier()
    scorer = FaithfulnessScorer(classifier=fake)
    score = await scorer.score(
        context="The fee is 0.5%.",
        answer="The fee is 0.5% (Document: [ab12cd34]).",
    )
    assert score == pytest.approx(0.9)
    hypotheses = [p["text_pair"] for p in fake.calls[0][0]]
    assert "Document" not in hypotheses[0]


async def test_long_context_is_windowed_and_best_window_wins():
    filler = " ".join(["filler"] * (WINDOW_WORDS * 2))
    context = filler + " the fee is 0.5%."
    fake = FakeClassifier()
    scorer = FaithfulnessScorer(classifier=fake)

    score = await scorer.score(context=context, answer="The fee is 0.5%.")

    pairs, kwargs = fake.calls[0]
    assert len(pairs) > 1  # several windows
    assert all(len(p["text"].split()) <= WINDOW_WORDS for p in pairs)
    assert kwargs["truncation"] is True
    assert score == pytest.approx(0.9)


async def test_empty_answer_scores_zero():
    scorer = FaithfulnessScorer(classifier=FakeClassifier())
    assert await scorer.score("some context", "   ") == 0.0


def test_missing_entailment_label_is_an_error():
    with pytest.raises(ValueError):
        FaithfulnessScorer._entailment([{"label": "LABEL_0", "score": 1.0}])


needs_transformers = pytest.mark.skipif(
    importlib.util.find_spec("transformers") is None, reason="transformers not installed"
)


@pytest.fixture(scope="module")
def real_scorer():
    return FaithfulnessScorer()


@needs_transformers
async def test_real_model_separates_supported_from_unsupported(real_scorer):
    context = "The client's portfolio holds 60% stocks and 40% bonds. The annual fee is 0.5%."
    supported = await real_scorer.score(context, "The portfolio holds 60% stocks and 40% bonds.")
    contradicted = await real_scorer.score(context, "The portfolio is 100% cash and charges no fees.")
    unrelated = await real_scorer.score(context, "The Eiffel Tower is in Paris.")

    assert supported > 0.8
    assert contradicted < 0.2
    assert unrelated < 0.2
