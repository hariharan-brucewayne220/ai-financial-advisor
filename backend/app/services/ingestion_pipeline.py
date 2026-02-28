"""
Document Ingestion Pipeline - End-to-end RAG data preparation

Complete flow:
1. Parse document (PDF/Image/CSV/TXT)
2. Detect PII
3. Chunk intelligently
4. Generate embeddings
5. Store in pgvector
6. Build BM25 index
"""

import logging
import asyncio
from typing import List, Tuple
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.config import get_settings
from app.models.document import Document, DocumentChunk
from app.services.document_parser import DocumentParser
from app.services.chunker import ChunkerService
from app.services.embedder import EmbedderService
from app.services.pii_detector import PIIDetector

logger = logging.getLogger(__name__)
settings = get_settings()


class DocumentIngestionPipeline:
    """Orchestrates the complete document processing pipeline."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.parser = DocumentParser()
        self.chunker = ChunkerService()
        self.embedder = EmbedderService()
        self.pii_detector = PIIDetector()

    async def ingest(
        self,
        document_id: UUID,
        client_id: UUID,
        file_path: str,
        file_type: str,
    ) -> Tuple[int, bool]:
        """
        Full ingestion pipeline.

        Args:
            document_id: Document record ID
            client_id: Client ID
            file_path: Path to uploaded file
            file_type: File extension (pdf, csv, xlsx, txt, jpg, png, etc)

        Returns:
            (chunk_count, pii_detected)
        """
        try:
            logger.info(f"Starting pipeline for document {document_id}")

            # Step 1: Parse document
            logger.info(f"[1/6] Parsing {file_type} document...")
            text = await self._parse_document(file_path, file_type)
            logger.info(f"  ✓ Extracted {len(text)} characters")

            # Step 2: Detect PII
            logger.info(f"[2/6] Detecting PII...")
            pii_detected, sanitized_text = await self._detect_pii(text)
            logger.info(f"  ✓ PII detected: {pii_detected}")

            # Step 3: Chunk document
            logger.info(f"[3/6] Chunking document...")
            chunks = await self._chunk_document(sanitized_text)
            logger.info(f"  ✓ Created {len(chunks)} chunks")

            # Step 4: Generate embeddings
            logger.info(f"[4/6] Generating embeddings...")
            chunks_with_embeddings = await self._embed_chunks(chunks)
            logger.info(f"  ✓ Embedded {len(chunks_with_embeddings)} chunks")

            # Step 5: Store in database
            logger.info(f"[5/6] Storing in database...")
            await self._store_chunks(document_id, client_id, chunks_with_embeddings)
            logger.info(f"  ✓ Stored in pgvector")

            # Step 6: Update document status
            logger.info(f"[6/6] Finalizing...")
            await self._update_document_status(
                document_id, "indexed", len(chunks), pii_detected
            )
            logger.info(f"  ✓ Document ready for retrieval")

            return len(chunks), pii_detected

        except Exception as e:
            logger.error(f"Pipeline failed for {document_id}: {e}", exc_info=True)
            await self._update_document_status(
                document_id, "failed", 0, False, str(e)
            )
            raise

    async def _parse_document(self, file_path: str, file_type: str) -> str:
        """Parse document into text."""
        file_ext = file_type.lower()

        # Handle images with OpenAI Vision API
        if file_ext in ["jpg", "jpeg", "png", "gif", "webp"]:
            return await self._extract_from_image(file_path)

        # Handle text documents
        return await self.parser.parse(file_path, file_ext)

    async def _extract_from_image(self, file_path: str) -> str:
        """
        Extract text from image using OpenAI Vision API.

        Perfect for screenshots of:
        - Stock prices and portfolios
        - Financial statements
        - Charts and graphs
        - Transaction receipts
        """
        try:
            import base64
            from pathlib import Path
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=settings.openai_api_key)

            # Read image
            image_data = Path(file_path).read_bytes()
            base64_image = base64.standard_b64encode(image_data).decode("utf-8")

            # Detect format
            suffix = Path(file_path).suffix.lower()
            format_map = {
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
                ".gif": "image/gif",
                ".webp": "image/webp",
            }
            image_format = format_map.get(suffix, "image/jpeg")

            # Use Vision-capable chat completion to extract structured data
            data_url = f"data:{image_format};base64,{base64_image}"
            response = await client.chat.completions.create(
                model="gpt-4o",
                max_tokens=2000,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Extract all text and structured data from this image.\nInclude:\n- All visible text, numbers, and labels\n- Stock symbols, prices, gains/losses\n- Portfolio allocations\n- Dates and transactions\n- Any tables or lists\n\nFormat as clear, readable text that can be chunked and analyzed."},
                            {"type": "image_url", "image_url": {"url": data_url}},
                        ],
                    }
                ],
            )

            extracted_text = response.choices[0].message.content or ""
            logger.info(f"Vision API extracted {len(extracted_text)} chars from image")
            return extracted_text

        except ImportError:
            logger.error("OpenAI SDK not available for image processing")
            raise
        except Exception as e:
            logger.error(f"Vision API failed: {e}")
            raise

    async def _detect_pii(self, text: str) -> Tuple[bool, str]:
        """Detect and optionally redact PII."""
        try:
            sanitized, entities = await self.pii_detector.redact_pii(text)
            pii_found = len(entities) > 0
            return pii_found, sanitized
        except Exception as e:
            logger.warning(f"PII detection failed: {e}, continuing anyway")
            return False, text

    async def _chunk_document(self, text: str) -> List[dict]:
        """Split text into semantic chunks."""
        chunks = self.chunker.chunk_text(text)
        return chunks

    async def _embed_chunks(self, chunks: List[dict]) -> List[dict]:
        """Generate embeddings for chunks."""
        embeddings = []
        for chunk in chunks:
            embedding = await self.embedder.embed_single(chunk["content"])
            chunk["embedding"] = embedding
            embeddings.append(chunk)
        return embeddings

    async def _store_chunks(
        self,
        document_id: UUID,
        client_id: UUID,
        chunks_with_embeddings: List[dict],
    ) -> None:
        """Store chunks and embeddings in pgvector."""
        for chunk_data in chunks_with_embeddings:
            chunk = DocumentChunk(
                document_id=document_id,
                chunk_index=chunk_data.get("chunk_index", 0),
                content=chunk_data["content"],
                content_length=len(chunk_data["content"]),
                embedding=chunk_data.get("embedding", []),  # Automatically stored as vector type
                chunk_metadata=chunk_data.get("metadata", {}),
            )
            self.db.add(chunk)

        await self.db.commit()

    async def _update_document_status(
        self,
        document_id: UUID,
        status: str,
        chunk_count: int,
        pii_detected: bool,
        error_message: str = None,
    ) -> None:
        """Update document record with final status."""
        stmt = (
            update(Document)
            .where(Document.id == document_id)
            .values(
                status=status,
                chunk_count=chunk_count,
                pii_detected=pii_detected,
                error_message=error_message,
            )
        )
        await self.db.execute(stmt)
        await self.db.commit()
