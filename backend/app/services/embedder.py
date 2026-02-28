"""
Embedder Service: Convert text to dense vectors

**Why OpenAI text-embedding-3-small?**
- 1536 dimensions (good balance of quality vs memory)
- Fast and cheap (~$0.02 per 1M tokens)
- Pre-trained on massive web scale (better generalization)
- Can be batched for efficiency

**Why Batch Processing?**
- OpenAI charges per API call, not per token
- Batching 100 texts costs same as 1 text
- Critical for cost-efficient production RAG

**Vector Properties:**
- Normalized (unit length) so cosine similarity = dot product
- Semantic meaning: similar texts have similar vectors
- High dimensionality (1536) captures nuance
"""

import asyncio
import logging
from typing import List
import tiktoken

from openai import AsyncOpenAI, RateLimitError, APIError

from app.config import get_settings


logger = logging.getLogger(__name__)
settings = get_settings()


class EmbedderService:
    """Embed text using OpenAI API with batching and retry logic."""

    def __init__(self):
        """Initialize embedder with OpenAI client."""
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_embedding_model
        self.batch_size = 100  # Max 100 texts per API call
        self.max_retries = 3
        self.retry_delay = 2  # Start with 2 second delay

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """
        Embed multiple texts in batches.

        Args:
            texts: List of text strings to embed

        Returns:
            List of embedding vectors (one per text, in same order)

        **Why Batching?**
        Sending 100 texts together costs same as 1 text in API fees.
        This makes production RAG cost-effective.
        """
        if not texts:
            return []

        embeddings = [None] * len(texts)
        retry_count = 0

        while retry_count < self.max_retries:
            try:
                # Process in batches
                for i in range(0, len(texts), self.batch_size):
                    batch = texts[i : i + self.batch_size]
                    batch_embeddings = await self._get_batch_embeddings(batch)

                    # Store in order
                    for j, embedding in enumerate(batch_embeddings):
                        embeddings[i + j] = embedding

                    logger.info(f"Embedded batch {i//self.batch_size + 1}/{(len(texts)-1)//self.batch_size + 1}")

                return embeddings

            except RateLimitError as e:
                # OpenAI rate limit - back off exponentially
                retry_count += 1
                wait_time = self.retry_delay * (2 ** (retry_count - 1))
                logger.warning(f"Rate limited, waiting {wait_time}s before retry {retry_count}/{self.max_retries}")
                await asyncio.sleep(wait_time)

            except APIError as e:
                # Other API error - retry with backoff
                retry_count += 1
                if retry_count >= self.max_retries:
                    raise
                wait_time = self.retry_delay * retry_count
                logger.warning(f"API error: {e}, retrying in {wait_time}s")
                await asyncio.sleep(wait_time)

        raise Exception(f"Failed to embed texts after {self.max_retries} retries")

    async def embed_single(self, text: str) -> List[float]:
        """
        Embed a single text.

        Convenience method that calls embed_texts with list of 1.
        """
        result = await self.embed_texts([text])
        return result[0]

    async def _get_batch_embeddings(self, texts: List[str]) -> List[List[float]]:
        """
        Get embeddings for a batch of texts.

        **Implementation Detail:**
        OpenAI's batch endpoint accepts List[str] and returns embeddings
        in same order. The response includes token usage so we can track costs.
        """
        response = await self.client.embeddings.create(
            input=texts,
            model=self.model,
        )

        # Response.data is sorted by index, maintaining order
        embeddings = [item.embedding for item in response.data]
        return embeddings

    def estimate_tokens(self, text: str) -> int:
        """
        Estimate token count for text (for cost calculation).

        Uses tiktoken to count actual tokens that will be billed.
        This lets us estimate costs before making API calls.
        """
        try:
            encoding = tiktoken.encoding_for_model(self.model)
            tokens = len(encoding.encode(text))
            return tokens
        except Exception as e:
            logger.warning(f"Could not estimate tokens: {e}, using approximate (1 token per 4 chars)")
            return len(text) // 4

    def estimate_batch_cost(self, texts: List[str]) -> float:
        """
        Estimate cost of embedding texts.

        text-embedding-3-small: $0.02 per 1M tokens
        Helps track budget and decide batch sizes.
        """
        total_tokens = sum(self.estimate_tokens(text) for text in texts)
        cost_per_mtok = 0.02
        return (total_tokens / 1_000_000) * cost_per_mtok


class EmbedderCache:
    """
    Simple in-memory cache for embeddings.

    Avoids re-embedding the same text multiple times during a session.
    Useful for FAQ-style documents that repeat content.
    """

    def __init__(self, max_size: int = 10000):
        """Initialize cache with max size."""
        self.cache = {}
        self.max_size = max_size
        self.hits = 0
        self.misses = 0

    def get(self, text: str) -> List[float] | None:
        """Get embedding from cache if exists."""
        if text in self.cache:
            self.hits += 1
            return self.cache[text]
        self.misses += 1
        return None

    def put(self, text: str, embedding: List[float]) -> None:
        """Store embedding in cache (with size limit)."""
        if len(self.cache) >= self.max_size:
            # Simple eviction: remove oldest key
            oldest_key = next(iter(self.cache))
            del self.cache[oldest_key]

        self.cache[text] = embedding

    def hit_rate(self) -> float:
        """Get cache hit rate."""
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0
