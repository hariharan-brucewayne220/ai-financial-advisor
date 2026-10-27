"""
Azure AI Search backend, tested against a mock Search service.

Checks the REST calls the app sends (paths, api-version, auth, filter,
hybrid query body) and that HybridRetriever switches backend on the flag.
"""

import json
import uuid

import httpx
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.services import azure_search
from app.services.azure_search import AzureSearchError, AzureSearchIndex, client_filter

CLIENT = str(uuid.uuid4())
BASE_ENV = {
    "SECRET_KEY": "s",
    "DATABASE_URL": "postgresql+asyncpg://u:p@localhost/db",
    "REDIS_URL": "redis://localhost:6379/0",
    "OPENAI_API_KEY": "sk-x",
}
SEARCH_ENV = {
    "RETRIEVAL_BACKEND": "azure_search",
    "AZURE_SEARCH_ENDPOINT": "https://my-search.search.windows.net/",
    "AZURE_SEARCH_INDEX": "chunks",
}


def make_settings(**env) -> Settings:
    return Settings(_env_file=None, **{**BASE_ENV, **env})


class FakeSearch:
    def __init__(self, hits=None, status=200):
        self.requests: list[httpx.Request] = []
        self.hits = hits or []
        self.status = status

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(self.status, text="boom")
        path = request.url.path
        if path.endswith("/docs/index"):
            docs = json.loads(request.content)["value"]
            return httpx.Response(200, json={"value": [
                {"key": d["id"], "status": True, "statusCode": 200} for d in docs
            ]})
        if path.endswith("/docs/search"):
            return httpx.Response(200, json={"value": self.hits})
        if path.endswith("/stats"):
            return httpx.Response(200, json={"documentCount": 3, "storageSize": 100, "vectorIndexSize": 50})
        return httpx.Response(201, json={})

    def index(self, settings, **kwargs) -> AzureSearchIndex:
        return AzureSearchIndex(
            settings, http_client=httpx.AsyncClient(transport=httpx.MockTransport(self.handler)), **kwargs
        )


def body(request: httpx.Request) -> dict:
    return json.loads(request.content)


# ---------------------------------------------------------------------------
# Settings and helpers
# ---------------------------------------------------------------------------

def test_default_backend_is_pgvector():
    assert make_settings().retrieval_backend == "pgvector"


def test_azure_search_backend_requires_endpoint():
    with pytest.raises(ValidationError, match="AZURE_SEARCH_ENDPOINT"):
        make_settings(RETRIEVAL_BACKEND="azure_search")


def test_client_filter_only_accepts_uuids():
    assert client_filter(CLIENT) == f"client_id eq '{CLIENT}'"
    with pytest.raises(ValueError):
        client_filter("x' or client_id ne '")


def test_index_schema_vector_field_is_not_stored():
    schema = azure_search.index_schema("chunks", 1536)
    emb = next(f for f in schema["fields"] if f["name"] == "embedding")
    assert emb["dimensions"] == 1536
    assert emb["stored"] is False and emb["retrievable"] is False
    assert emb["vectorSearchProfile"] == schema["vectorSearch"]["profiles"][0]["name"]


# ---------------------------------------------------------------------------
# REST calls
# ---------------------------------------------------------------------------

async def test_ensure_index_puts_schema_with_api_key():
    fake = FakeSearch()
    idx = fake.index(make_settings(**SEARCH_ENV, AZURE_SEARCH_API_KEY="k"))

    await idx.ensure_index()

    req = fake.requests[0]
    assert req.method == "PUT"
    assert str(req.url) == "https://my-search.search.windows.net/indexes/chunks?api-version=2024-07-01"
    assert req.headers["api-key"] == "k"
    assert body(req)["name"] == "chunks"


async def test_entra_token_used_when_no_key():
    async def token():
        return "tok"

    fake = FakeSearch()
    idx = fake.index(make_settings(**SEARCH_ENV), token_provider=token)
    await idx.stats()

    req = fake.requests[0]
    assert req.headers["authorization"] == "Bearer tok"
    assert "api-key" not in req.headers


async def test_upload_batches_and_serializes():
    fake = FakeSearch()
    idx = fake.index(make_settings(**SEARCH_ENV, AZURE_SEARCH_API_KEY="k"))
    chunks = [
        {"id": uuid.uuid4(), "client_id": CLIENT, "document_id": "d", "chunk_index": i,
         "content": f"c{i}", "metadata": {"page": i}, "embedding": [0.0] * 4}
        for i in range(azure_search.UPLOAD_BATCH + 5)
    ]

    assert await idx.upload_chunks(chunks) == len(chunks)

    assert len(fake.requests) == 2
    first = body(fake.requests[0])["value"][0]
    assert first["@search.action"] == "mergeOrUpload"
    assert first["metadata"] == json.dumps({"page": 0})
    assert isinstance(first["id"], str)


async def test_upload_raises_on_per_document_failure():
    class Failing(FakeSearch):
        def handler(self, request):
            docs = json.loads(request.content)["value"]
            return httpx.Response(200, json={"value": [
                {"key": d["id"], "status": False, "errorMessage": "too big"} for d in docs
            ]})

    idx = Failing().index(make_settings(**SEARCH_ENV, AZURE_SEARCH_API_KEY="k"))
    with pytest.raises(AzureSearchError, match="failed to index"):
        await idx.upload_chunks([{"id": "1", "client_id": CLIENT, "document_id": "d",
                                  "content": "x", "embedding": [0.0]}])


async def test_http_error_is_raised():
    idx = FakeSearch(status=403).index(make_settings(**SEARCH_ENV, AZURE_SEARCH_API_KEY="k"))
    with pytest.raises(AzureSearchError, match="403"):
        await idx.stats()


@pytest.mark.parametrize("mode,has_text,has_vector", [
    ("hybrid", True, True),
    ("vector", False, True),
    ("text", True, False),
])
async def test_search_body_per_mode(mode, has_text, has_vector):
    fake = FakeSearch()
    idx = fake.index(make_settings(**SEARCH_ENV, AZURE_SEARCH_API_KEY="k"))

    await idx.search(CLIENT, "ira limit", [0.1, 0.2], top=5, mode=mode)

    b = body(fake.requests[0])
    assert b["filter"] == f"client_id eq '{CLIENT}'"
    assert b["top"] == 5
    assert ("search" in b) == has_text
    assert ("vectorQueries" in b) == has_vector
    if has_vector:
        vq = b["vectorQueries"][0]
        assert vq["fields"] == "embedding" and vq["k"] >= 5 and vq["vector"] == [0.1, 0.2]


# ---------------------------------------------------------------------------
# HybridRetriever uses the flag
# ---------------------------------------------------------------------------

async def test_retriever_uses_azure_search_when_flag_set(monkeypatch):
    from app.services import retriever as retriever_mod

    hits = [
        {"id": "c2", "document_id": "d1", "content": "second", "metadata": "{}", "@search.score": 0.02},
        {"id": "c1", "document_id": "d1", "content": "first", "metadata": '{"page": 3}', "@search.score": 0.03},
    ]
    fake = FakeSearch(hits=hits)
    settings = make_settings(**SEARCH_ENV, AZURE_SEARCH_API_KEY="k")
    monkeypatch.setattr(azure_search, "_shared_index", fake.index(settings))
    monkeypatch.setattr(retriever_mod, "settings", settings)

    retriever = retriever_mod.HybridRetriever(db_session=None)

    async def fake_embed(text):
        return [0.5, 0.5]

    async def no_pgvector(*args, **kwargs):
        raise AssertionError("pgvector path must not run")

    monkeypatch.setattr(retriever, "_embed_text", fake_embed)
    monkeypatch.setattr(retriever, "_dense_search", no_pgvector)
    monkeypatch.setattr(retriever, "_sparse_search", no_pgvector)

    chunks = await retriever.retrieve("ira limit", CLIENT, top_k=5, use_hyde=False)

    assert [c.chunk_id for c in chunks] == ["c1", "c2"]  # re-sorted by score
    assert chunks[0].metadata["page"] == 3
    assert chunks[0].retrieval_method == "azure_hybrid"
    sent = body(fake.requests[0])
    assert sent["search"] == "ira limit" and sent["vectorQueries"][0]["vector"] == [0.5, 0.5]
