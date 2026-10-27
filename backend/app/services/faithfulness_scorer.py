"""
Faithfulness Scorer Service

**Problem:** LLMs sometimes generate plausible-sounding but unsupported claims.
Example: "The portfolio gained 50%" when documents say "25%".

**Solution:** Use Natural Language Inference (NLI) to verify answer is grounded in context.

NLI classifies relationship between premise (retrieved docs) and hypothesis (answer):
  - ENTAILMENT: answer logically follows from docs (faithful)
  - NEUTRAL: answer not directly supported but possible
  - CONTRADICTION: answer contradicts docs (hallucination)

This gives us a 0.0-1.0 faithfulness score per answer.
"""

import asyncio
import logging
import re
from typing import Callable, List, Tuple

logger = logging.getLogger(__name__)

NLI_MODEL = "facebook/bart-large-mnli"

# BART's input limit is 1024 tokens, so long contexts are scored in
# overlapping word windows and each sentence keeps its best window.
WINDOW_WORDS = 300
WINDOW_STRIDE = 250

# Citations the QA prompt asks for, e.g. "(Document: [ab12cd34])". They are
# not claims, and leaving them in drags entailment down.
_CITATION_RE = re.compile(r"\((?:Document|Source|Live Market Data)[^)]*\)", re.IGNORECASE)


class FaithfulnessScorer:
    """Score faithfulness of generated answers against retrieved context."""

    def __init__(self, classifier: Callable | None = None):
        """
        Initialize NLI model.

        classifier: optional stand-in for the transformers pipeline (tests).
        """
        if classifier is not None:
            self.classifier = classifier
            return
        try:
            from transformers import pipeline
            # Plain NLI: premise = context, hypothesis = answer sentence,
            # output = probabilities for contradiction / neutral / entailment
            self.classifier = pipeline("text-classification", model=NLI_MODEL)
        except ImportError:
            logger.warning("transformers not installed. NLI scoring disabled. pip install transformers")
            self.classifier = None

    async def score(self, context: str, answer: str) -> float:
        """
        Score how faithful answer is to context.

        Each answer sentence gets the highest entailment probability over
        the context windows; the answer's score is the mean over sentences.

        Args:
            context: Retrieved document chunks
            answer: Generated answer

        Returns:
            Faithfulness score 0.0-1.0 (higher = more faithful)
        """
        if not self.classifier:
            return 1.0  # Disabled, return neutral score

        try:
            sentences = self._split_sentences(_CITATION_RE.sub("", answer))
            premises = self._windows(context)

            if not sentences or not premises:
                return 0.0

            # Model inference is CPU-bound; keep it off the event loop
            scores = await asyncio.to_thread(self._sentence_scores, premises, sentences)

            overall_score = sum(scores) / len(scores)
            logger.debug(f"Faithfulness score: {overall_score:.3f} ({len(sentences)} sentences)")
            return overall_score

        except Exception as e:
            logger.error(f"Error scoring faithfulness: {e}")
            return 0.5  # Neutral score on error

    def _sentence_scores(self, premises: List[str], sentences: List[str]) -> List[float]:
        """Best entailment probability per sentence across all premises."""
        pairs = [{"text": p, "text_pair": s} for s in sentences for p in premises]
        outputs = self.classifier(pairs, top_k=None, truncation=True, batch_size=8)

        best = []
        for i in range(len(sentences)):
            window_outputs = outputs[i * len(premises):(i + 1) * len(premises)]
            best.append(max(self._entailment(o) for o in window_outputs))
        return best

    @staticmethod
    def _entailment(labels: List[dict]) -> float:
        """Pick the entailment probability out of one pipeline result."""
        for item in labels:
            if item["label"].lower() == "entailment":
                return float(item["score"])
        raise ValueError(f"No entailment label in NLI output: {labels}")

    @staticmethod
    def _windows(text: str) -> List[str]:
        """Split context into overlapping word windows."""
        words = text.split()
        if not words:
            return []
        if len(words) <= WINDOW_WORDS:
            return [" ".join(words)]
        windows = []
        for start in range(0, len(words), WINDOW_STRIDE):
            windows.append(" ".join(words[start:start + WINDOW_WORDS]))
            if start + WINDOW_WORDS >= len(words):
                break
        return windows

    @staticmethod
    def _split_sentences(text: str) -> List[str]:
        """
        Split text into sentences.

        Simple heuristic splitter (in production, use nltk or spacy).
        """
        # Split on periods, exclamation, question marks
        sentences = re.split(r'(?<=[.!?])\s+', text)
        return [s.strip() for s in sentences if s.strip()]


class FactualConsistencyChecker:
    """
    Check factual consistency of generated content.

    More lightweight than full NLI - just checks for direct contradictions.
    """

    def check_consistency(self, context: str, claim: str) -> Tuple[bool, float]:
        """
        Check if claim is consistent with context.

        Args:
            context: Retrieved context
            claim: Claim to verify

        Returns:
            (is_consistent, confidence_score)

        **Simple approach:**
        - Extract entities from both
        - Check for contradictory statements
        - Look for agreed facts
        """
        # This is a placeholder for more sophisticated checking
        # In production, would use:
        # - Entity extraction (spaCy)
        # - Fact verification (TfiDF overlap)
        # - Knowledge base lookup

        # For now, simple string matching
        is_consistent = self._simple_consistency_check(context, claim)
        confidence = 0.8 if is_consistent else 0.2

        return is_consistent, confidence

    @staticmethod
    def _simple_consistency_check(context: str, claim: str) -> bool:
        """
        Simple consistency check using keywords.

        Looks for direct contradictions in text.
        """
        # Extract key numbers/percentages from claim
        import re

        numbers_in_claim = re.findall(r'\d+\.?\d*%?', claim)
        if not numbers_in_claim:
            return True  # No specific claims to verify

        # Check if context contains same numbers
        context_lower = context.lower()
        claim_lower = claim.lower()

        # If claim says "30%" and context says "60%", that's inconsistent
        for num in numbers_in_claim:
            if num not in context_lower:
                # Number not mentioned in context - might be hallucination
                return False

        return True
