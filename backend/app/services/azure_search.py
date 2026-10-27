"""
Azure AI Search backend: a second retrieval option next to pgvector.

Enabled with RETRIEVAL_BACKEND=azure_search. Postgres stays the system of
record for documents and chunks; chunk text, ids and embeddings are also
pushed to one Azure AI Search index, and queries go there instead of
pgvector + in-memory BM25.

**Why one hybrid query?**
Azure AI Search runs the keyword (BM25) and vector (HNSW) halves and fuses
them with Reciprocal Rank Fusion on the service side, which is the same
idea as HybridRetriever's local RRF, so the two backends are comparable.

**Free tier notes:** 50 MB storage and 3 indexes per service. The vector
field is stored=false (searchable but not returned), which roughly halves
the space vectors take, since the app never reads them back.

Talks to the REST API directly with httpx: four calls are all we need, and
it keeps the request bodies visible and easy to test with a mock transport.
Auth is Microsoft Entra ID (managed identity / az login) unless
AZURE_SEARCH_API_KEY is set.
"""

import json
import logging
from typing import Awaitable, Callable, List, Literal
from uuid import UUID

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

SEARCH_SCOPE = "https://search.azure.com/.default"
VECTOR_PROFILE = "hnsw-cosine"
UPLOAD_BATCH = 100  # ~1.5 MB per request with 1536-dim vectors

SearchMode = Literal["hybrid", "vector", "text"]


class AzureSearchError(RuntimeError):
    """Non-2xx response from Azure AI Search."""


def index_schema(name: str, dimensions: int) -> dict:
    """Index definition for document chunks."""
    return {
        "name": name,
        "fields": [
            {"name": "id", "type": "Edm.String", "key": True, "filterable": True},
            {"name": "client_id", "type": "Edm.String", "filterable": True},
            {"name": "document_id", "type": "Edm.String", "filterable": True},
            {"name": "chunk_index", "type": "Edm.Int32", "filterable": True},
            {"name": "content", "type": "Edm.String", "searchable": True},
            {"name": "metadata", "type": "Edm.String"},
            {
                "name": "embedding",
                "type": "Collection(Edm.Single)",
                "searchable": True,
                "retrievable": False,
                "stored": False,
                "dimensions": dimensions,
                "vectorSearchProfile": VECTOR_PROFILE,
            },
        ],
        "vectorSearch": {
            "algorithms": [{
                "name": "hnsw",
                "kind": "hnsw",
                "hnswParameters": {"metric": "cosine", "m": 4, "efConstruction": 400, "efSearch": 500},
            }],
            "profiles": [{"name": VECTOR_PROFILE, "algorithm": "hnsw"}],
        },
    }


def client_filter(client_id: str) -> str:
    """OData filter scoping results to one client. client_id must be a UUID."""
    return f"client_id eq '{UUID(str(client_id))}'"


class AzureSearchIndex:
    """Minimal async client for one Azure AI Search index."""

    def __init__(
        self,
        settings: Settings,
        http_client: httpx.AsyncClient | None = None,
        token_provider: Callable[[], Awaitable[str]] | None = None,
    ):
        if not settings.azure_search_endpoint:
            raise ValueError("AZURE_SEARCH_ENDPOINT is required for RETRIEVAL_BACKEND=azure_search")
        self.endpoint = settings.azure_search_endpoint.rstrip("/")
        self.index = settings.azure_search_index
        self.api_version = settings.azure_search_api_version
        self.dimensions = settings.openai_embedding_dimension
        self.api_key = settings.azure_search_api_key
        self.http = http_client or httpx.AsyncClient(timeout=30.0)
        self._token_provider = token_provider

    async def _headers(self) -> dict:
        if self.api_key:
            return {"api-key": self.api_key}
        if self._token_provider is None:
            from azure.identity.aio import DefaultAzureCredential, get_bearer_token_provider
            self._token_provider = get_bearer_token_provider(DefaultAzureCredential(), SEARCH_SCOPE)
        return {"Authorization": f"Bearer {await self._token_provider()}"}

    async def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        response = await self.http.request(
            method,
            f"{self.endpoint}{path}",
            params={"api-version": self.api_version},
            json=body,
            headers=await self._headers(),
        )
        if response.status_code >= 400:
            raise AzureSearchError(f"{method} {path} -> {response.status_code}: {response.text[:500]}")
        return response.json() if response.content else {}

    async def ensure_index(self) -> None:
        """Create the index, or update it in place if it exists."""
        await self._request("PUT", f"/indexes/{self.index}", index_schema(self.index, self.dimensions))
        logger.info(f"Azure AI Search index ready: {self.index}")

    async def delete_index(self) -> None:
        await self._request("DELETE", f"/indexes/{self.index}")

    async def upload_chunks(self, chunks: List[dict]) -> int:
        """
        Upsert chunks. Each dict needs id, client_id, document_id,
        chunk_index, content, metadata, embedding.
        """
        uploaded = 0
        for start in range(0, len(chunks), UPLOAD_BATCH):
            batch = chunks[start:start + UPLOAD_BATCH]
            body = {"value": [
                {
                    "@search.action": "mergeOrUpload",
                    "id": str(c["id"]),
                    "client_id": str(c["client_id"]),
                    "document_id": str(c["document_id"]),
                    "chunk_index": int(c.get("chunk_index", 0)),
                    "content": c["content"],
                    "metadata": json.dumps(c.get("metadata") or {}),
                    "embedding": list(c["embedding"]),
                }
                for c in batch
            ]}
            result = await self._request("POST", f"/indexes/{self.index}/docs/index", body)
            failed = [r for r in result.get("value", []) if not r.get("status", False)]
            if failed:
                raise AzureSearchError(f"{len(failed)} chunks failed to index: {failed[:3]}")
            uploaded += len(batch)
        return uploaded

    async def delete_chunks(self, chunk_ids: List[str]) -> None:
        if not chunk_ids:
            return
        body = {"value": [{"@search.action": "delete", "id": str(i)} for i in chunk_ids]}
        await self._request("POST", f"/indexes/{self.index}/docs/index", body)

    async def search(
        self,
        client_id: str,
        query_text: str,
        query_vector: List[float] | None,
        top: int = 20,
        mode: SearchMode = "hybrid",
    ) -> List[dict]:
        """
        Query the index, scoped to one client.

        mode="hybrid": BM25 on query_text + vector on query_vector, fused by
        the service with RRF. "vector" and "text" run one half only (used by
        the eval to compare).
        """
        body: dict = {
            "filter": client_filter(client_id),
            "top": top,
            "select": "id,document_id,chunk_index,content,metadata",
        }
        if mode in ("hybrid", "text"):
            body["search"] = query_text
        if mode in ("hybrid", "vector"):
            if query_vector is None:
                raise ValueError(f"mode={mode} needs a query vector")
            body["vectorQueries"] = [{
                "kind": "vector",
                "vector": list(query_vector),
                "fields": "embedding",
                "k": max(top, 50),
            }]
        result = await self._request("POST", f"/indexes/{self.index}/docs/search", body)
        return result.get("value", [])

    async def stats(self) -> dict:
        """documentCount, storageSize and vectorIndexSize (bytes) for the index."""
        return await self._request("GET", f"/indexes/{self.index}/stats")


_shared_index: AzureSearchIndex | None = None


def get_search_index() -> AzureSearchIndex:
    """Process-wide index client (reuses one connection pool)."""
    global _shared_index
    if _shared_index is None:
        from app.config import get_settings
        _shared_index = AzureSearchIndex(get_settings())
    return _shared_index
