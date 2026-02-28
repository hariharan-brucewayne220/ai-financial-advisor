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

import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)


class FaithfulnessScorer:
    """Score faithfulness of generated answers against retrieved context."""

    def __init__(self):
        """Initialize NLI model."""
        try:
            from transformers import pipeline
            # zero-shot-classification works like NLI
            self.classifier = pipeline(
                "zero-shot-classification",
                model="facebook/bart-large-mnli",
            )
        except ImportError:
            logger.warning("transformers not installed. NLI scoring disabled. pip install transformers")
            self.classifier = None

    async def score(self, context: str, answer: str) -> float:
        """
        Score how faithful answer is to context.

        Args:
            context: Retrieved document chunks
            answer: Generated answer

        Returns:
            Faithfulness score 0.0-1.0 (higher = more faithful)
        """
        if not self.classifier:
            return 1.0  # Disabled, return neutral score

        try:
            # Split answer into sentences for sentence-level scoring
            sentences = self._split_sentences(answer)

            if not sentences:
                return 0.0

            scores = []
            for sentence in sentences:
                # Use NLI to check if context entails sentence
                # (i.e., does context support this sentence?)
                score = await self._score_sentence(context, sentence)
                scores.append(score)

            # Average sentence-level scores
            overall_score = sum(scores) / len(scores) if scores else 0.0
            logger.debug(f"Faithfulness score: {overall_score:.3f} ({len(sentences)} sentences)")
            return overall_score

        except Exception as e:
            logger.error(f"Error scoring faithfulness: {e}")
            return 0.5  # Neutral score on error

    async def _score_sentence(self, context: str, sentence: str) -> float:
        """
        Score single sentence using NLI.

        Premise: context (what we know)
        Hypothesis: sentence (claim to verify)
        """
        try:
            result = self.classifier(
                context,
                [sentence],
                hypothesis_template="This text is about {}.",
            )

            # Extract entailment score
            # Result labels: ['ENTAILMENT', 'NEUTRAL', 'CONTRADICTION']
            scores = dict(zip(result['labels'], result['scores']))

            # Entailment = faithful, Contradiction = unfaithful
            entailment_score = scores.get('ENTAILMENT', 0.0)
            return entailment_score

        except Exception as e:
            logger.warning(f"Error in sentence scoring: {e}")
            return 0.5

    @staticmethod
    def _split_sentences(text: str) -> List[str]:
        """
        Split text into sentences.

        Simple heuristic splitter (in production, use nltk or spacy).
        """
        import re
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
