# Results log

Every number in this file comes from a command that was actually run. Each
section lists the command, the environment and the raw output.

## 1. NLI faithfulness scorer: before and after the fix

**Date:** 2026-10-27. **Machine:** cloud dev container, 4 vCPU, CPU only.
**Model:** `facebook/bart-large-mnli`, transformers 5.21.0, torch 2.14.1+cpu.

Same context for all three cases:
`"The client's portfolio holds 60% stocks and 40% bonds. The annual fee is 0.5%."`

Script (`nli_check.py`, run from `backend/`):

```python
import asyncio
from app.services.faithfulness_scorer import FaithfulnessScorer

ctx = "The client's portfolio holds 60% stocks and 40% bonds. The annual fee is 0.5%."
cases = {
    "supported": "The portfolio holds 60% stocks and 40% bonds.",
    "contradicted": "The portfolio is 100% cash and charges no fees.",
    "unrelated": "The Eiffel Tower is in Paris.",
}
s = FaithfulnessScorer()
for name, ans in cases.items():
    print(name, asyncio.run(s.score(ctx, ans)))
```

```bash
PYTHONPATH=. SECRET_KEY=x DATABASE_URL=postgresql+asyncpg://u:p@localhost/db \
  REDIS_URL=redis://localhost OPENAI_API_KEY=sk-test python nli_check.py
```

The "before" run also printed the raw pipeline output for the supported case.
The same cases are a test now: `test_real_model_separates_supported_from_unsupported`
in `backend/tests/test_faithfulness_scorer.py`.

Before (commit `e18c0a3`, original scorer):

```
raw pipeline output labels: ['The portfolio holds 60% stocks and 40% bonds.'] scores: [0.9851950407028198]
supported 0.0
contradicted 0.0
unrelated 0.0
```

The zero-shot pipeline returns the candidate sentence as its label, so
`scores.get('ENTAILMENT', 0.0)` always fell through to 0.0.

After (this branch, `FaithfulnessScorer` using plain NLI):

```
supported: 0.9936
contradicted: 0.0002
unrelated: 0.0572
```

Related bug, also fixed: because every answer scored 0.0, the QA graph's
retry check always fired, and `retry_count` was never written to state, so
the graph looped until LangGraph raised `GraphRecursionError`.
`backend/tests/test_qa_agent_retry.py` reproduces that failure on the old
code and passes on the fix.

## 2. Eval corpus and question set

**Corpus:** IRS Publication 590-A (2025) and 590-B (2025), public domain,
committed under `backend/eval/corpus/` with SHA-256 hashes in `SOURCES.md`.

| | 590-A | 590-B | Total |
|---|---|---|---|
| PDF bytes | 1,817,459 | 2,097,777 | 3,915,236 |
| Pages | 62 | 71 | 133 |
| Chunks (app chunker, 1024-token target, 128 overlap) | 119 | 125 | 244 |
| Tokens (tiktoken, gpt-4o encoding) | 79,770 | 120,457 | 200,227 |

**Questions:** 42 in `backend/eval/questions.jsonl` (20 on 590-A, 22 on
590-B). Each has an `evidence` span copied from the extracted text. A chunk
is relevant if it contains that span after whitespace and quote
normalization. All 42 spans resolve to 1 or 2 chunks (overlapping chunks
can both contain a span). `tests/test_eval_harness.py` fails if that stops
being true.

**Metric definitions** (top 5 chunks returned to the generator):

- recall@5: share of a question's relevant chunks found in the top 5, averaged over questions
- hit@5: share of questions with at least one relevant chunk in the top 5
- MRR@5: mean of 1/rank of the first relevant chunk (0 if none in the top 5)
- latency: wall clock per question, sequential, measured in the harness
- p50/p95: linear interpolation over the 42 per-question values
- cost: tokens reported by the API for each call, times the prices in
  `backend/eval/prices.json` (checked 2026-10-27 on OpenAI's and Azure's pricing pages)

## 3. BM25-only baseline (no model provider needed)

**Date:** 2026-10-27. **Machine:** cloud dev container, 4 vCPU. Postgres
16.15 + pgvector 0.6.0 on localhost. BM25 is the app's own
`HybridRetriever._sparse_search` (rank-bm25 over whitespace tokens), with
a fresh retriever per question, as the app does per request (so every
question rebuilds the in-memory BM25 index).

```bash
cd backend
export DATABASE_URL=postgresql+asyncpg://advisor:password123@localhost:5432/financial_advisor_db \
  SECRET_KEY=x REDIS_URL=redis://localhost OPENAI_API_KEY=sk-none
python -m eval.run_eval ingest --skip-embeddings
python -m eval.run_eval run --backends bm25 --label bm25-local
```

Ingest output (trimmed): `corpus: 244 chunks, 200227 tokens`

Run output (`backend/eval/out/20261027T172203Z-run-bm25-local.json`):

| backend | n | recall@5 | hit@5 | MRR@5 | retrieval p50 ms | retrieval p95 ms | cost / 100 q (USD) |
|---|---|---|---|---|---|---|---|
| bm25 | 42 | 0.714 | 0.738 | 0.565 | 50 | 69 | 0.0000 |

11 of 42 questions miss. Most are vocabulary gaps between the question and
the IRS wording, for example q23 asks about a "penalty" where the text says
"25% excise tax", and q32 asks about "required minimum distributions from
my Roth IRA" where the text says "You aren't required to take
distributions from your Roth".

This is a baseline only. The pgvector, hybrid and Azure AI Search columns
need embeddings and will be added from real runs (sections below).
