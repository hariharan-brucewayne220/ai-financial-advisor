"""
PII (Personally Identifiable Information) Detector

**Why detect PII before indexing?**
1. Regulatory compliance (GDPR, HIPAA, financial regulations)
2. Prevent accidental leakage of sensitive data
3. Log detection results for audit trail
4. Flag documents that need masking before processing

**What we detect:**
- Person names
- Email addresses
- Phone numbers
- SSN, passport numbers
- Credit card numbers
- Bank account/IBAN codes
- URLs
"""

import logging
from typing import List, Dict, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PIIEntity:
    """Detected PII entity."""
    entity_type: str
    value: str
    start: int
    end: int
    confidence: float


class PIIDetector:
    """Detect sensitive information in text using Presidio."""

    def __init__(self):
        """Initialize Presidio analyzer."""
        try:
            from presidio_analyzer import AnalyzerEngine
            from presidio_analyzer.nlp_engine import NlpEngineProvider

            # Initialize Presidio analyzer
            self.analyzer = AnalyzerEngine()
            self.enabled = True
        except ImportError:
            logger.warning("presidio-analyzer not installed. PII detection disabled.")
            logger.warning("Install with: pip install presidio-analyzer")
            self.analyzer = None
            self.enabled = False

    async def detect_pii(
        self,
        text: str,
        entity_types: List[str] = None,
        confidence_threshold: float = 0.75,
    ) -> Tuple[bool, List[PIIEntity]]:
        """
        Scan text for PII.

        Args:
            text: Text to scan
            entity_types: Specific entities to detect (None = all)
            confidence_threshold: Only flag detections above this confidence

        Returns:
            (has_pii, list_of_entities)

        **Example:**
        text = "John Smith (john@example.com) called at 555-1234"
        has_pii, entities = await detector.detect_pii(text)
        # entities = [
        #   PIIEntity(PERSON, "John Smith", 0, 10, 0.95),
        #   PIIEntity(EMAIL, "john@example.com", 12, 28, 0.99),
        #   PIIEntity(PHONE, "555-1234", 39, 47, 0.85),
        # ]
        """
        if not self.enabled:
            return False, []

        try:
            # Default: scan common financial PII
            if entity_types is None:
                entity_types = [
                    "PERSON",
                    "EMAIL_ADDRESS",
                    "PHONE_NUMBER",
                    "CREDIT_CARD",
                    "IBAN_CODE",
                    "US_SSN",
                    "URL",
                ]

            # Run Presidio analysis
            results = self.analyzer.analyze(
                text=text,
                entities=entity_types,
                language="en",
            )

            # Convert to PIIEntity objects
            entities = []
            for result in results:
                # Filter by confidence threshold
                if result.score < confidence_threshold:
                    continue

                entity = PIIEntity(
                    entity_type=result.entity_type,
                    value=text[result.start : result.end],
                    start=result.start,
                    end=result.end,
                    confidence=result.score,
                )
                entities.append(entity)

            has_pii = len(entities) > 0
            logger.info(f"PII detection: found {len(entities)} entities in {len(text)} chars")

            return has_pii, entities

        except Exception as e:
            logger.error(f"Error detecting PII: {e}")
            return False, []

    async def mask_pii(self, text: str, entities: List[PIIEntity]) -> str:
        """
        Mask detected PII in text.

        Args:
            text: Original text
            entities: Detected PII entities

        Returns:
            Text with PII replaced by [ENTITY_TYPE]
        """
        if not entities:
            return text

        # Sort entities by position (descending) to avoid index shifting
        sorted_entities = sorted(entities, key=lambda e: e.start, reverse=True)

        masked_text = text
        for entity in sorted_entities:
            # Replace with placeholder
            placeholder = f"[{entity.entity_type}]"
            masked_text = (
                masked_text[: entity.start]
                + placeholder
                + masked_text[entity.end :]
            )

        return masked_text

    async def redact_pii(
        self,
        text: str,
        entity_types: List[str] = None,
        confidence_threshold: float = 0.75,
    ) -> Tuple[str, List[PIIEntity]]:
        """
        Detect and redact PII in text.

        Convenience method combining detect and mask.
        """
        has_pii, entities = await self.detect_pii(text, entity_types, confidence_threshold)
        masked = await self.mask_pii(text, entities)
        return masked, entities


# Initialize global PII detector
_pii_detector = None


def get_pii_detector() -> PIIDetector:
    """Get or create singleton PII detector."""
    global _pii_detector
    if _pii_detector is None:
        _pii_detector = PIIDetector()
    return _pii_detector
