# AI Financial Advisor

A production-grade RAG (Retrieval-Augmented Generation) platform for financial advisors. Upload client documents, ask questions about their portfolios, and generate grounded financial reports — all powered by hybrid search, LangGraph agents, and real-time streaming.

---

## Features

- **Streaming Q&A** — Ask questions about client portfolios and receive streamed answers grounded in uploaded documents via Server-Sent Events (SSE)
- **Document Upload & Processing** — Upload PDFs, CSVs, and Excel files; documents are chunked, PII-redacted, and indexed automatically
- **Hybrid Retrieval** — Combines dense vector search (pgvector + OpenAI embeddings) with BM25 sparse search, fused via Reciprocal Rank Fusion (RRF)
- **Report Generation** — LangGraph agent generates structured financial reports backed by real client data — hard-fails if no documents are indexed
- **Market Data Integration** — Fetches live market data via Alpha Vantage and surfaces availability status explicitly in every response
- **JWT Authentication** — Cryptographic token validation with advisor-client ownership enforcement on every endpoint
- **Audit Trail** — Append-only audit logs with data source provenance, market data timestamps, and PII redaction tracking
- **Multi-Tenancy** — Client data is isolated per advisor; UUID-guessing attacks are blocked at the ownership layer

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Nginx (port 80)                         │
└────────────────┬───────────────────────────┬────────────────────┘
                 │                           │
        ┌────────▼────────┐        ┌─────────▼────────┐
        │  React + Vite   │        │   FastAPI (8000)  │
        │   (port 5173)   │        │   LangGraph Agent │
        └─────────────────┘        └────────┬─────────┘
                                            │
              ┌─────────────────────────────┼───────────────────┐
              │                             │                   │
     ┌────────▼──────┐          ┌───────────▼──────┐   ┌───────▼──────┐
     │  PostgreSQL   │          │      Redis        │   │  LocalStack  │
     │  + pgvector   │          │  (cache + queue)  │   │  (S3 / dev)  │
     └───────────────┘          └──────────────────┘   └──────────────┘
```

**Retrieval pipeline:**

```
Document → PII Redaction → Chunking → Embedding → pgvector (HNSW)
                                                         │
Query ──────────────────────────────────────── BM25 + Dense Search
                                                         │
                                              RRF Fusion → Rerank* → Compress*
                                                         │
                                              LangGraph Agent → SSE Stream
```

\* The `rerank` and `compress` graph nodes are currently **pass-through placeholders**
(see [Known Limitations](#known-limitations)).

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, shadcn/ui, Zustand |
| Backend | FastAPI, Python 3.11, SQLAlchemy (async), Alembic |
| LLM & Agents | OpenAI GPT-4o, LangGraph, LangChain |
| Vector Search | PostgreSQL 16 + pgvector (HNSW index) |
| Sparse Search | BM25Okapi (rank-bm25) |
| Task Queue | ARQ (async Redis queue) |
| Auth | python-jose (JWT), passlib (bcrypt) |
| Infrastructure | Docker Compose, Nginx, LocalStack (AWS S3 emulation) |
| Observability | Append-only audit logs, market data timestamps |

---

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose v2
- OpenAI API key
- Alpha Vantage API key (optional, for live market data)

---

## Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/hariharan-brucewayne220/ai-financial-advisor.git
cd ai-financial-advisor
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set the required values:

```env
# Required
OPENAI_API_KEY=sk-...
SECRET_KEY=your-secret-key-min-32-chars

# Database (defaults work with Docker Compose)
DATABASE_URL=postgresql+asyncpg://advisor:advisor_password@postgres:5432/financial_advisor_db
REDIS_URL=redis://redis:6379

# Optional — live market data
ALPHA_VANTAGE_API_KEY=your-key
```

### 3. Start the stack

```bash
docker compose up --build
```

This starts 6 services: PostgreSQL, Redis, LocalStack, backend, frontend, and Nginx.

| Service | URL |
|---|---|
| Frontend UI | http://localhost |
| Backend API | http://localhost/api |
| API Docs (Swagger) | http://localhost/api/docs |
| Frontend (direct) | http://localhost:5173 |
| Backend (direct) | http://localhost:8000 |

### 4. Initialize the database

The database schema is applied automatically on first startup via Alembic migrations. No manual step required.

---

## API Overview

### Authentication

All endpoints require a JWT bearer token:

```
Authorization: Bearer <token>
```

### Core Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/auth/register` | Register an advisor, returns JWT tokens |
| `POST` | `/api/auth/login` | Obtain JWT tokens |
| `POST` | `/api/clients` | Create a client |
| `GET` | `/api/clients` | List advisor's clients |
| `POST` | `/api/documents/{client_id}/upload` | Upload a document for a client |
| `GET` | `/api/documents/{client_id}` | List client documents |
| `GET` | `/api/documents/{client_id}/{document_id}/status` | Poll ingestion status |
| `POST` | `/api/conversations/{client_id}/conversations` | Create a conversation |
| `GET` | `/api/conversations/{client_id}/conversations/{conv_id}/messages?query=...` | Stream Q&A response (SSE; `token` may be passed as a query param for `EventSource`) |
| `POST` | `/api/reports/{client_id}/generate?report_type=portfolio_summary` | Generate a grounded financial report |
| `GET` | `/api/reports/{client_id}/{report_id}` | Fetch a generated report |

### SSE Stream Events

The Q&A stream emits the following event types in order:

```
event: step         # agent node in progress (classify, retrieve, rerank, ...)
event: token        # partial response text
event: sources      # retrieved document chunk ids
event: faithfulness # NLI faithfulness score for the answer
event: done         # stream complete
event: error        # terminal error (stream closes)
```

---

## Project Structure

```
ai-financial-advisor/
├── backend/
│   ├── app/
│   │   ├── agents/          # LangGraph agents (QA, report writer)
│   │   ├── api/             # FastAPI routers
│   │   ├── auth.py          # JWT encode/decode/validate
│   │   ├── models/          # SQLAlchemy ORM models
│   │   ├── schemas/         # Pydantic request/response schemas
│   │   ├── services/        # RAG services (retriever, embedder, chunker)
│   │   └── workers/         # ARQ background task workers
│   ├── alembic/             # Database migrations
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/      # React components
│   │   ├── hooks/           # Custom hooks (useChat)
│   │   └── lib/             # API client (api.ts) and JWT helpers (auth.ts)
│   └── package.json
├── infrastructure/
│   └── nginx/               # Nginx reverse-proxy config used by docker-compose
├── docker-compose.yml
├── postgres.Dockerfile      # PostgreSQL + pgvector image
├── scripts/                 # init_db.sql schema, seed_data.py
└── .env.example
```

---

## Development

### Running services individually

**Backend (hot reload):**
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

**Frontend (hot reload):**
```bash
cd frontend
npm install
npm run dev
```

### Database migrations

```bash
# Inside the backend container or with DATABASE_URL set
alembic upgrade head

# Create a new migration
alembic revision --autogenerate -m "description"
```

### Verifying a change

There is **no automated test suite** in this repository yet (no `pytest` tests and no
integration script). Until one exists, the checks are:

```bash
# Frontend type-check + production build
cd frontend && npm ci && npm run build

# Backend: byte-compile everything to catch syntax/import-path errors
cd backend && python -m compileall app

# End-to-end: bring the stack up and exercise it through Swagger
docker compose up --build   # then open http://localhost/api/docs
```

---

## Security Notes

- JWT tokens are validated cryptographically on every request
- Advisor-client ownership is verified before any data access
- PII is redacted via [Presidio](https://microsoft.github.io/presidio/) before document indexing (requires `presidio-analyzer` and the spaCy `en_core_web_lg` model from `requirements.txt`; if the import fails the detector logs a warning and disables itself)
- Market data availability is always explicit — responses never silently omit data
- Reports hard-fail if the client has no indexed documents (no hallucination)
- All Q&A responses include source citations and faithfulness scores

---

## Known Limitations

This is a working MVP; the following parts of the pipeline are not yet what the
docstrings describe:

- **Rerank stage is a placeholder.** `FinancialQAAgent._rerank_documents` sorts the
  RRF-fused candidates by their existing score and truncates to `reranker_top_k`
  (comment in code: "In production, would use cross-encoder here"). The
  `cross-encoder/ms-marco-MiniLM-L-6-v2` setting in `config.py` is not used.
- **Compress stage is a no-op.** `FinancialQAAgent._compress_context` joins the
  reranked chunks and returns them unchanged with a `0.0` compression ratio
  ("In production, would call LLMLingua here"). `ENABLE_COMPRESSION` and
  `compression_target_ratio` have no effect.
- **ARQ worker is not wired in.** Ingestion and report generation run as FastAPI
  `BackgroundTasks`; the `worker` service is commented out in `docker-compose.yml`.
- **Model downloads on first use.** Faithfulness scoring loads
  `facebook/bart-large-mnli` (~1.6 GB) from the Hugging Face hub the first time the
  QA agent is constructed.
- **No automated tests** (see [Verifying a change](#verifying-a-change)).

---

## Production Deployment

There is **no infrastructure-as-code in this repository**; `infrastructure/` only
holds the Nginx config for the local `docker-compose` stack. A cloud deployment
(e.g. ECS Fargate + RDS PostgreSQL with pgvector + ElastiCache Redis + S3 + ALB)
would need to be provisioned separately.

---

## License

MIT
