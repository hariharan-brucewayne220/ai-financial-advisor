"""
Eval corpus: parse and chunk the PDFs with the app's own parser and
chunker, then map each question's evidence span to the chunks containing it.

A chunk is relevant to a question if it contains the question's evidence
span (after whitespace and quote normalization). Spans are short and
copied from the extracted text, so ground truth does not depend on chunk
ids and stays valid for any backend.
"""

import hashlib
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List

from app.services.chunker import ChunkerService
from app.services.document_parser import DocumentParser

EVAL_DIR = Path(__file__).parent
CORPUS_DIR = EVAL_DIR / "corpus"
QUESTIONS_PATH = EVAL_DIR / "questions.jsonl"
DOCS = {
    "p590a": "IRS Publication 590-A (2025), Contributions to IRAs",
    "p590b": "IRS Publication 590-B (2025), Distributions from IRAs",
}
# A span found in more chunks than this is too generic to be ground truth
MAX_RELEVANT_CHUNKS = 3

_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.translate(_QUOTES)).strip()


@dataclass
class Chunk:
    doc: str
    chunk_index: int
    content: str
    tokens: int

    @property
    def key(self) -> str:
        return f"{self.doc}#{self.chunk_index}"


@dataclass
class Question:
    id: str
    doc: str
    question: str
    evidence: str
    reference_answer: str
    relevant: List[str]  # chunk keys "p590a#12"


async def load_chunks() -> List[Chunk]:
    chunker = ChunkerService()
    chunks: List[Chunk] = []
    for doc in DOCS:
        text = await DocumentParser.parse(str(CORPUS_DIR / f"{doc}.pdf"), "pdf")
        for c in chunker.chunk_text(text):
            chunks.append(Chunk(doc, c["chunk_index"], c["content"], c["tokens"]))
    return chunks


def load_questions(chunks: List[Chunk]) -> List[Question]:
    """Read questions.jsonl and attach relevant chunk keys. Raises on bad spans."""
    normalized = {c.key: normalize(c.content) for c in chunks}
    questions, problems = [], []
    for line in QUESTIONS_PATH.read_text().splitlines():
        if not line.strip():
            continue
        q = json.loads(line)
        span = normalize(q["evidence"])
        relevant = [
            k for k, text in normalized.items()
            if k.startswith(q["doc"] + "#") and span in text
        ]
        if not relevant:
            problems.append(f"{q['id']}: evidence not found in {q['doc']}: {q['evidence']!r}")
        elif len(relevant) > MAX_RELEVANT_CHUNKS:
            problems.append(f"{q['id']}: evidence too generic, in {len(relevant)} chunks")
        questions.append(Question(**q, relevant=relevant))
    if problems:
        raise ValueError("Bad eval questions:\n" + "\n".join(problems))
    return questions


def corpus_stats(chunks: List[Chunk]) -> Dict:
    stats = {"documents": {}, "chunks": len(chunks), "tokens": sum(c.tokens for c in chunks)}
    for doc, title in DOCS.items():
        pdf = CORPUS_DIR / f"{doc}.pdf"
        doc_chunks = [c for c in chunks if c.doc == doc]
        stats["documents"][doc] = {
            "title": title,
            "pdf_bytes": pdf.stat().st_size,
            "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
            "chunks": len(doc_chunks),
            "tokens": sum(c.tokens for c in doc_chunks),
            "text_chars": sum(len(c.content) for c in doc_chunks),
        }
    return stats


def dump_ground_truth(questions: List[Question], path: Path) -> None:
    path.write_text(json.dumps([asdict(q) for q in questions], indent=2, ensure_ascii=False))
