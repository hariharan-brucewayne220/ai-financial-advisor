"""
Retrieval + answer eval for pgvector, BM25, the app's hybrid (pgvector +
BM25 with RRF) and Azure AI Search.

Run from backend/ with the app's normal environment variables:

    python -m eval.run_eval ingest [--azure-search]
    python -m eval.run_eval run --backends bm25,pgvector,hybrid,azure_search [--answer] [--hyde]

ingest  parses and chunks eval/corpus/*.pdf with the app's parser and
        chunker, embeds the chunks with the configured provider, and stores
        them in Postgres under a dedicated eval client (and in the Azure AI
        Search index with --azure-search).
run     asks every question in eval/questions.jsonl against each backend
        and reports recall@5, hit@5, MRR@5, latency, token cost and, with
        --answer, the NLI faithfulness of the generated answer.

Every run writes eval/out/<timestamp>-<command>.json with per-question rows.
Nothing here invents numbers: the summary is computed from those rows.
"""

import argparse
import asyncio
import hashlib
import json
import logging
import platform
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.llm import get_llm_client
from app.models.advisor import Advisor
from app.models.client import Client
from app.models.document import Document, DocumentChunk
from app.services.embedder import EmbedderService
from app.services.retriever import HybridRetriever, RetrievedChunk
from eval import metrics
from eval.corpus import DOCS, EVAL_DIR, Chunk, corpus_stats, load_chunks, load_questions

logger = logging.getLogger("eval")

OUT_DIR = EVAL_DIR / "out"
NAMESPACE = uuid.UUID("5d6c1a52-7f0e-4e8e-9b7e-0c1e5f0a1b2c")
ADVISOR_ID = uuid.uuid5(NAMESPACE, "eval-advisor")
CLIENT_ID = uuid.uuid5(NAMESPACE, "eval-client-irs-590")
TOP_K = 5
ALL_BACKENDS = ["bm25", "pgvector", "hybrid", "azure_search"]


def chunk_uuid(key: str) -> uuid.UUID:
    """Deterministic chunk id, so retrieved ids map back to 'p590a#12' keys."""
    return uuid.uuid5(NAMESPACE, key)


def document_uuid(doc: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"doc-{doc}")


class UsageMeter:
    """Wraps the shared OpenAI client and counts tokens per model."""

    def __init__(self, client):
        self._usage: Dict[str, Dict[str, int]] = defaultdict(lambda: {"input": 0, "output": 0})
        chat_create = client.chat.completions.create
        embed_create = client.embeddings.create

        async def metered_chat(*args, **kwargs):
            response = await chat_create(*args, **kwargs)
            self._add(kwargs["model"], response.usage.prompt_tokens, response.usage.completion_tokens)
            return response

        async def metered_embed(*args, **kwargs):
            response = await embed_create(*args, **kwargs)
            self._add(kwargs["model"], response.usage.prompt_tokens, 0)
            return response

        client.chat.completions.create = metered_chat
        client.embeddings.create = metered_embed

    def _add(self, model: str, input_tokens: int, output_tokens: int) -> None:
        self._usage[model]["input"] += input_tokens
        self._usage[model]["output"] += output_tokens

    def take(self) -> Dict[str, Dict[str, int]]:
        """Usage since the last take()."""
        snapshot = {m: dict(v) for m, v in self._usage.items()}
        self._usage.clear()
        return snapshot


def load_prices(provider: str) -> Dict[str, Dict[str, float]]:
    return json.loads((EVAL_DIR / "prices.json").read_text())[provider]


def run_metadata(settings) -> dict:
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model_provider": settings.model_provider,
        "chat_model": settings.chat_model,
        "embedding_model": settings.embedding_model,
        "python": platform.python_version(),
        "machine": platform.machine(),
    }


def write_output(name: str, payload: dict) -> Path:
    OUT_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = OUT_DIR / f"{stamp}-{name}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return path


# ---------------------------------------------------------------------------
# ingest
# ---------------------------------------------------------------------------

async def embed_with_cache(chunks: List[Chunk], settings) -> List[List[float]]:
    """Embed chunk texts, reusing earlier results for the same provider/model."""
    cache_path = OUT_DIR / f"embeddings-{settings.model_provider}-{settings.embedding_model}.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    digest = [hashlib.sha256(c.content.encode()).hexdigest() for c in chunks]
    missing = [i for i, d in enumerate(digest) if d not in cache]
    if missing:
        vectors = await EmbedderService().embed_texts([chunks[i].content for i in missing])
        for i, vector in zip(missing, vectors):
            cache[digest[i]] = vector
        OUT_DIR.mkdir(exist_ok=True)
        cache_path.write_text(json.dumps(cache))
    logger.info(f"Embedded {len(missing)} chunks, {len(chunks) - len(missing)} from cache")
    return [cache[d] for d in digest]


async def ingest(args) -> None:
    settings = get_settings()
    meter = UsageMeter(get_llm_client())
    chunks = await load_chunks()
    questions = load_questions(chunks)  # fails early on bad evidence spans

    if args.skip_embeddings:
        # BM25-only runs need no model provider (and cost nothing)
        vectors = [None] * len(chunks)
    else:
        vectors = await embed_with_cache(chunks, settings)
    embed_usage = meter.take()

    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        # Start clean: deleting the client cascades to documents and chunks
        await db.execute(delete(Client).where(Client.id == CLIENT_ID))
        if not await db.get(Advisor, ADVISOR_ID):
            db.add(Advisor(id=ADVISOR_ID, email="eval@example.invalid",
                           hashed_password="!", full_name="Eval Advisor"))
        db.add(Client(id=CLIENT_ID, advisor_id=ADVISOR_ID, name="Eval client (IRS Pub 590)"))
        for doc, title in DOCS.items():
            doc_chunks = [c for c in chunks if c.doc == doc]
            db.add(Document(
                id=document_uuid(doc), client_id=CLIENT_ID, file_name=f"{doc}.pdf",
                file_type="pdf", s3_key=f"eval/{doc}.pdf", status="indexed",
                chunk_count=len(doc_chunks),
            ))
        await db.flush()
        rows = []
        for chunk, vector in zip(chunks, vectors):
            db.add(DocumentChunk(
                id=chunk_uuid(chunk.key), document_id=document_uuid(chunk.doc),
                chunk_index=chunk.chunk_index, content=chunk.content,
                content_length=len(chunk.content), embedding=vector,
                chunk_metadata={"doc": chunk.doc},
            ))
            rows.append({
                "id": chunk_uuid(chunk.key), "client_id": CLIENT_ID,
                "document_id": document_uuid(chunk.doc), "chunk_index": chunk.chunk_index,
                "content": chunk.content, "metadata": {"doc": chunk.doc}, "embedding": vector,
            })
        await db.commit()
    await engine.dispose()

    index_stats = None
    if args.azure_search and args.skip_embeddings:
        raise SystemExit("--azure-search needs embeddings")
    if args.azure_search:
        from app.services.azure_search import AzureSearchIndex
        index = AzureSearchIndex(settings)
        await index.ensure_index()
        await index.delete_chunks([str(r["id"]) for r in rows])  # idempotent re-runs
        await index.upload_chunks(rows)
        await asyncio.sleep(5)  # stats lag a few seconds behind uploads
        index_stats = await index.stats()

    payload = {
        "meta": run_metadata(settings),
        "corpus": corpus_stats(chunks),
        "questions": len(questions),
        "embedding_usage": embed_usage,
        "embedding_cost_usd": metrics.cost_usd(embed_usage, load_prices(settings.model_provider)) if embed_usage else 0.0,
        "azure_search_index_stats": index_stats,
    }
    path = write_output("ingest", payload)
    print(json.dumps({k: v for k, v in payload.items() if k != "corpus"}, indent=2))
    print(f"corpus: {payload['corpus']['chunks']} chunks, {payload['corpus']['tokens']} tokens")
    print(f"wrote {path}")


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

def make_retrieve_fn(backend: str, db: AsyncSession, settings, hyde: bool) -> Callable:
    """
    One retrieval function per backend. A fresh HybridRetriever per question
    mirrors the app, which builds a new agent (and retriever) per request.
    """
    async def query_vector(r: HybridRetriever, question: str):
        text = await r._generate_hyde_answer(question) if hyde else question
        return await r._embed_text(text)

    async def bm25(question):
        r = HybridRetriever(db)
        return await r._sparse_search(str(CLIENT_ID), question)

    async def pgvector(question):
        r = HybridRetriever(db)
        return await r._dense_search(str(CLIENT_ID), await query_vector(r, question))

    async def hybrid(question):
        r = HybridRetriever(db)
        r.settings = settings.model_copy(update={"retrieval_backend": "pgvector"})
        return await r.retrieve(question, str(CLIENT_ID), top_k=TOP_K, use_hyde=hyde)

    async def azure_search(question):
        r = HybridRetriever(db)
        r.settings = settings.model_copy(update={"retrieval_backend": "azure_search"})
        return await r.retrieve(question, str(CLIENT_ID), top_k=TOP_K, use_hyde=hyde)

    return {"bm25": bm25, "pgvector": pgvector, "hybrid": hybrid, "azure_search": azure_search}[backend]


async def run(args) -> None:
    settings = get_settings()
    backends = args.backends.split(",")
    unknown = set(backends) - set(ALL_BACKENDS)
    if unknown:
        raise SystemExit(f"unknown backends: {unknown}")

    meter = UsageMeter(get_llm_client())
    prices = load_prices(settings.model_provider)
    chunks = await load_chunks()
    questions = load_questions(chunks)
    if args.limit:
        questions = questions[:args.limit]
    key_by_id = {str(chunk_uuid(c.key)): c.key for c in chunks}

    agent = None
    if args.answer:
        from app.agents.financial_qa_agent import FinancialQAAgent
        agent = FinancialQAAgent(db_session=None)  # only its generate/score nodes are used

    engine = create_async_engine(settings.database_url)
    rows = []
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        stored = (await db.execute(
            select(DocumentChunk.id).join(Document).where(Document.client_id == CLIENT_ID)
        )).scalars().all()
        if len(stored) != len(chunks):
            raise SystemExit(f"DB has {len(stored)} eval chunks, corpus has {len(chunks)}: run ingest first")

        for backend in backends:
            retrieve = make_retrieve_fn(backend, db, settings, args.hyde)
            for q in questions:
                meter.take()
                t0 = time.perf_counter()
                retrieved: List[RetrievedChunk] = await retrieve(q.question)
                retrieval_ms = (time.perf_counter() - t0) * 1000
                top = retrieved[:TOP_K]
                keys = [key_by_id.get(c.chunk_id, c.chunk_id) for c in top]

                row = {
                    "backend": backend, "id": q.id, "question": q.question,
                    "relevant": q.relevant, "retrieved": keys,
                    "recall@5": metrics.recall_at_k(keys, q.relevant, TOP_K),
                    "hit@5": metrics.hit_at_k(keys, q.relevant, TOP_K),
                    "rr@5": metrics.reciprocal_rank(keys, q.relevant, TOP_K),
                    "retrieval_ms": retrieval_ms,
                }

                if agent is not None and backend != "bm25":
                    state = {
                        "query": q.question,
                        "reranked_chunks": [
                            {"id": c.chunk_id, "content": c.content, "score": c.score,
                             "document_id": c.document_id, "metadata": c.metadata}
                            for c in top
                        ],
                        "market_data_context": "",
                    }
                    state.update(await agent._compress_context(state))
                    t1 = time.perf_counter()
                    generated = await agent._generate_response(state)
                    row["generation_ms"] = (time.perf_counter() - t1) * 1000
                    row["end_to_end_ms"] = retrieval_ms + row["generation_ms"]
                    row["answer"] = generated["generated_response"]
                    t2 = time.perf_counter()
                    row["faithfulness"] = await agent.faithfulness_scorer.score(
                        state["compressed_context"], row["answer"]
                    )
                    row["nli_ms"] = (time.perf_counter() - t2) * 1000

                row["usage"] = meter.take()
                row["cost_usd"] = metrics.cost_usd(row["usage"], prices)
                rows.append(row)
                logger.info(f"{backend} {q.id} hit@5={row['hit@5']:.0f} {retrieval_ms:.0f}ms")
    await engine.dispose()

    summary = summarize(rows, backends)
    payload = {
        "meta": {**run_metadata(settings), "hyde": args.hyde, "answer": args.answer,
                 "questions": len(questions), "top_k": TOP_K},
        "summary": summary,
        "rows": rows,
    }
    path = write_output(f"run-{args.label}" if args.label else "run", payload)
    print(markdown_table(summary, args.answer))
    print(f"\nwrote {path}")


def summarize(rows: List[dict], backends: List[str]) -> Dict[str, dict]:
    summary = {}
    for backend in backends:
        rs = [r for r in rows if r["backend"] == backend]
        if not rs:
            continue
        n = len(rs)
        s = {
            "n": n,
            "recall@5": sum(r["recall@5"] for r in rs) / n,
            "hit@5": sum(r["hit@5"] for r in rs) / n,
            "mrr@5": sum(r["rr@5"] for r in rs) / n,
            "retrieval_p50_ms": metrics.percentile([r["retrieval_ms"] for r in rs], 50),
            "retrieval_p95_ms": metrics.percentile([r["retrieval_ms"] for r in rs], 95),
            "cost_per_100_usd": 100 * sum(r["cost_usd"] for r in rs) / n,
        }
        if all("faithfulness" in r for r in rs):
            s["faithfulness_mean"] = sum(r["faithfulness"] for r in rs) / n
            s["end_to_end_p50_ms"] = metrics.percentile([r["end_to_end_ms"] for r in rs], 50)
            s["end_to_end_p95_ms"] = metrics.percentile([r["end_to_end_ms"] for r in rs], 95)
        summary[backend] = s
    return summary


def markdown_table(summary: Dict[str, dict], with_answers: bool) -> str:
    head = ["backend", "n", "recall@5", "hit@5", "MRR@5", "retrieval p50 ms", "retrieval p95 ms"]
    if with_answers:
        head += ["faithfulness", "end-to-end p50 ms", "end-to-end p95 ms"]
    head += ["cost / 100 q (USD)"]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for backend, s in summary.items():
        cells = [backend, str(s["n"]), f"{s['recall@5']:.3f}", f"{s['hit@5']:.3f}", f"{s['mrr@5']:.3f}",
                 f"{s['retrieval_p50_ms']:.0f}", f"{s['retrieval_p95_ms']:.0f}"]
        if with_answers:
            if "faithfulness_mean" in s:
                cells += [f"{s['faithfulness_mean']:.3f}", f"{s['end_to_end_p50_ms']:.0f}",
                          f"{s['end_to_end_p95_ms']:.0f}"]
            else:
                cells += ["n/a", "n/a", "n/a"]
        cells += [f"{s['cost_per_100_usd']:.4f}"]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="load the corpus into Postgres (and Azure AI Search)")
    p_ingest.add_argument("--azure-search", action="store_true", help="also push chunks to Azure AI Search")
    p_ingest.add_argument("--skip-embeddings", action="store_true",
                          help="store chunks without vectors (BM25 only, no API calls)")

    p_run = sub.add_parser("run", help="ask every question against each backend")
    p_run.add_argument("--backends", default="bm25,pgvector,hybrid")
    p_run.add_argument("--answer", action="store_true", help="generate answers and score faithfulness")
    p_run.add_argument("--hyde", action="store_true", help="use HyDE query expansion (app default is on)")
    p_run.add_argument("--limit", type=int, default=0, help="only the first N questions")
    p_run.add_argument("--label", default="", help="suffix for the output file name")

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "httpx2", "app", "azure", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    asyncio.run({"ingest": ingest, "run": run}[args.command](args))


if __name__ == "__main__":
    main()
