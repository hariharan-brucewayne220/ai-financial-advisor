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
                                              RRF Fusion → Cross-Encoder Rerank
                                                         │
                                              LangGraph Agent → SSE Stream
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, shadcn/ui, Zustand |
| Backend | FastAPI, Python 3.12, SQLAlchemy (async), Alembic |
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
| `POST` | `/api/auth/login` | Obtain JWT token |
| `GET` | `/api/clients` | List advisor's clients |
| `POST` | `/api/documents/{client_id}/upload` | Upload a document for a client |
| `GET` | `/api/documents/{client_id}` | List client documents |
| `POST` | `/api/conversations` | Create a conversation |
| `GET` | `/api/conversations/{id}/stream` | Stream Q&A response (SSE) |
| `POST` | `/api/reports/{client_id}` | Generate a grounded financial report |

### SSE Stream Events

The Q&A stream emits the following event types in order:

```
event: token        # partial response text
event: sources      # retrieved document chunks
event: metadata     # market data status, faithfulness score
event: done         # stream complete
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
│   │   ├── hooks/           # Custom hooks (useChat, useDocuments)
│   │   └── lib/             # API client, utilities
│   └── package.json
├── infrastructure/          # Terraform modules (AWS ECS/RDS/S3)
├── docker-compose.yml
├── postgres.Dockerfile      # PostgreSQL + pgvector image
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

### Running tests

```bash
# Backend
cd backend && pytest

# Integration tests (requires running stack)
bash test_integration.sh
```

---

## Security Notes

- JWT tokens are validated cryptographically on every request
- Advisor-client ownership is verified before any data access
- PII is redacted via [Presidio](https://microsoft.github.io/presidio/) before document indexing
- Market data availability is always explicit — responses never silently omit data
- Reports hard-fail if the client has no indexed documents (no hallucination)
- All Q&A responses include source citations and faithfulness scores

---

## Production Deployment

Terraform modules for AWS are in `infrastructure/`. The production stack uses:

- **ECS Fargate** for backend and frontend containers
- **RDS PostgreSQL** with pgvector extension
- **ElastiCache Redis** for task queue and caching
- **S3** for document storage
- **ALB** for load balancing and SSL termination

---

## License

MIT
