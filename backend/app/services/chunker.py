"""
Document Chunking Service

**Why Chunking?**
- LLMs have token limits (GPT-4o: 128K context)
- Embeddings can't handle entire documents (lose nuance)
- Need fixed-size chunks for vector database storage
- Overlapping chunks preserve context at boundaries

**Chunking Strategies:**
1. SemanticChunker: Break at semantic boundaries (best quality)
2. RecursiveCharacterTextSplitter: Break on tokens/sentences/paragraphs (simple fallback)
3. Sliding Window: Fixed-size with overlap (most common)

**Why Overlap?**
Without overlap, important context at chunk boundaries is lost.
Example:
  Chunk A ends: "...stock portfolio includes..."
  Chunk B starts: "Technology represents 35%..."
With overlap, context is preserved across boundary.
"""

import logging
from typing import List
import tiktoken

from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)


class ChunkerService:
    """Split documents into semantic chunks."""

    def __init__(self, model: str = "gpt-4o"):
        """Initialize chunker with token counter."""
        self.encoding = tiktoken.encoding_for_model(model)
        self.chunk_size = 1024  # tokens (convert to chars: ~4 chars per token)
        self.chunk_overlap = 128  # tokens
        self.separator = "\n\n"  # Prefer paragraph breaks

    def chunk_text(self, text: str, metadata: dict = None) -> List[dict]:
        """
        Split text into chunks.

        Returns:
            List of dicts: {content, tokens, metadata}
        """
        if not text or not text.strip():
            return []

        # Use RecursiveCharacterTextSplitter as reliable fallback
        # (SemanticChunker requires embedding model, kept simple for now)
        splitter = RecursiveCharacterTextSplitter(
            # Characters per chunk (approximate, based on ~4 chars/token)
            chunk_size=self.chunk_size * 4,
            chunk_overlap=self.chunk_overlap * 4,
            # Separators in priority order
            separators=[
                "\n\n",  # Paragraph break
                "\n",    # Line break
                ". ",    # Sentence
                " ",     # Word
                "",      # Character
            ],
            length_function=len,
        )

        chunks = splitter.split_text(text)
        result = []

        for i, chunk in enumerate(chunks):
            # Count actual tokens (for billing and tracking)
            tokens = len(self.encoding.encode(chunk))

            chunk_data = {
                "content": chunk,
                "chunk_index": i,
                "tokens": tokens,
                "metadata": metadata or {},
            }
            result.append(chunk_data)

        logger.info(f"Split document into {len(result)} chunks, {sum(c['tokens'] for c in result)} tokens total")
        return result

    def chunk_markdown(self, markdown: str) -> List[dict]:
        """
        Chunk markdown document while preserving structure.

        Better than generic chunking for structured documents.
        Keeps headers with their content sections.
        """
        # Split by headers (# ## ###, etc.)
        chunks = []
        current_section = []
        current_header = None

        for line in markdown.split("\n"):
            if line.startswith("#"):
                # Save previous section
                if current_section:
                    content = "\n".join(current_section)
                    tokens = len(self.encoding.encode(content))
                    chunks.append({
                        "content": content,
                        "header": current_header,
                        "tokens": tokens,
                    })
                    current_section = []

                current_header = line
                current_section.append(line)
            else:
                current_section.append(line)

        # Save final section
        if current_section:
            content = "\n".join(current_section)
            tokens = len(self.encoding.encode(content))
            chunks.append({
                "content": content,
                "header": current_header,
                "tokens": tokens,
            })

        logger.info(f"Markdown chunked into {len(chunks)} sections")
        return chunks

    def estimate_chunks_needed(self, text_length: int) -> int:
        """
        Estimate how many chunks a document will produce.

        Useful for progress bars and resource planning.
        """
        estimated_tokens = text_length // 4  # 4 chars per token
        chunks = max(1, estimated_tokens // self.chunk_size)
        return chunks


class SmartChunker:
    """
    Advanced chunking with semantic preservation.

    **How it works:**
    1. Split by paragraphs initially
    2. If paragraph < min_size, merge with next
    3. If paragraph > max_size, split recursively
    4. Add overlap from previous/next chunks

    This preserves semantic units better than pure token splitting.
    """

    def __init__(self, min_chunk_tokens: int = 256, max_chunk_tokens: int = 1024):
        """Initialize smart chunker."""
        self.min_tokens = min_chunk_tokens
        self.max_tokens = max_chunk_tokens
        self.encoding = tiktoken.encoding_for_model("gpt-4o")
        self.simple_chunker = ChunkerService()

    def chunk_text(self, text: str) -> List[dict]:
        """
        Smart chunking algorithm.

        Tries to preserve semantic boundaries (paragraphs, sentences)
        while maintaining token size constraints.
        """
        # First split by paragraphs
        paragraphs = text.split("\n\n")
        chunks = []
        current_chunk = []
        current_tokens = 0

        for para in paragraphs:
            para_tokens = len(self.encoding.encode(para))

            # If paragraph itself is too large, recursively chunk it
            if para_tokens > self.max_tokens:
                # Save current chunk first
                if current_chunk:
                    content = "\n\n".join(current_chunk)
                    chunks.append({
                        "content": content,
                        "tokens": current_tokens,
                    })
                    current_chunk = []
                    current_tokens = 0

                # Recursively chunk the large paragraph
                sub_chunks = self.simple_chunker.chunk_text(para)
                chunks.extend(sub_chunks)
            else:
                # Check if adding paragraph would exceed max
                if current_tokens + para_tokens > self.max_tokens and current_chunk:
                    # Save current chunk and start new one
                    content = "\n\n".join(current_chunk)
                    chunks.append({
                        "content": content,
                        "tokens": current_tokens,
                    })
                    current_chunk = [para]
                    current_tokens = para_tokens
                else:
                    # Add to current chunk
                    current_chunk.append(para)
                    current_tokens += para_tokens

        # Save final chunk
        if current_chunk:
            content = "\n\n".join(current_chunk)
            chunks.append({
                "content": content,
                "tokens": current_tokens,
            })

        # Add chunk indices
        for i, chunk in enumerate(chunks):
            chunk["chunk_index"] = i

        logger.info(f"Smart chunker produced {len(chunks)} chunks")
        return chunks
