"""
Provider switching: OpenAI vs Azure OpenAI, chosen only by env vars.

The Azure tests exercise the real openai SDK against an in-process mock
transport, so they check the actual URL, auth header and body that would
go over the wire, without an Azure account.
"""

import json

import httpx2
import pytest
from pydantic import ValidationError

from app import llm
from app.config import Settings

BASE_ENV = {
    "SECRET_KEY": "s",
    "DATABASE_URL": "postgresql+asyncpg://u:p@localhost/db",
    "REDIS_URL": "redis://localhost:6379/0",
}


def make_settings(**env) -> Settings:
    return Settings(_env_file=None, **BASE_ENV, **env)


AZURE_ENV = {
    "MODEL_PROVIDER": "azure_openai",
    "AZURE_OPENAI_ENDPOINT": "https://my-aoai.openai.azure.com/",
    "AZURE_OPENAI_CHAT_DEPLOYMENT": "chat-dep",
    "AZURE_OPENAI_EMBEDDING_DEPLOYMENT": "embed-dep",
}


class FakeAzure:
    """Records requests and answers like Azure OpenAI's v1 API."""

    def __init__(self):
        self.requests: list[httpx2.Request] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        body = json.loads(request.content)
        if request.url.path.endswith("/embeddings"):
            inputs = body["input"] if isinstance(body["input"], list) else [body["input"]]
            return httpx2.Response(200, json={
                "object": "list",
                "model": body["model"],
                "data": [
                    {"object": "embedding", "index": i, "embedding": [0.1] * 1536}
                    for i in range(len(inputs))
                ],
                "usage": {"prompt_tokens": 3, "total_tokens": 3},
            })
        if request.url.path.endswith("/chat/completions"):
            return httpx2.Response(200, json={
                "id": "chatcmpl-1",
                "object": "chat.completion",
                "created": 0,
                "model": body["model"],
                "choices": [{
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "mock answer"},
                }],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
            })
        return httpx2.Response(404, json={"error": {"message": "unexpected path"}})

    def client(self, settings: Settings):
        transport = httpx2.MockTransport(self.handler)
        return llm.build_llm_client(
            settings, http_client=httpx2.AsyncClient(transport=transport), max_retries=0
        )


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def test_default_provider_is_openai_and_keeps_current_models():
    s = make_settings(OPENAI_API_KEY="sk-x")
    assert s.model_provider == "openai"
    assert s.chat_model == "gpt-4o"
    assert s.embedding_model == "text-embedding-3-small"
    assert s.vision_model == "gpt-4o"


def test_azure_provider_uses_deployment_names():
    s = make_settings(**AZURE_ENV)
    assert s.chat_model == "chat-dep"
    assert s.embedding_model == "embed-dep"
    assert s.vision_model == "chat-dep"


def test_azure_defaults_to_gpt_4o_mini():
    s = make_settings(MODEL_PROVIDER="azure_openai", AZURE_OPENAI_ENDPOINT="https://x.openai.azure.com")
    assert s.chat_model == "gpt-4o-mini"
    assert s.embedding_model == "text-embedding-3-small"


def test_openai_provider_requires_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValidationError, match="OPENAI_API_KEY"):
        make_settings()


def test_azure_provider_requires_endpoint_but_not_openai_key():
    with pytest.raises(ValidationError, match="AZURE_OPENAI_ENDPOINT"):
        make_settings(MODEL_PROVIDER="azure_openai")


def test_unknown_provider_is_rejected():
    with pytest.raises(ValidationError):
        make_settings(MODEL_PROVIDER="anthropic", OPENAI_API_KEY="sk-x")


@pytest.mark.parametrize("endpoint", [
    "https://r.openai.azure.com",
    "https://r.openai.azure.com/",
    "https://r.openai.azure.com/openai/v1",
    "https://r.openai.azure.com/openai/v1/",
])
def test_azure_v1_base_url(endpoint):
    assert llm.azure_v1_base_url(endpoint) == "https://r.openai.azure.com/openai/v1/"


# ---------------------------------------------------------------------------
# Client construction
# ---------------------------------------------------------------------------

def test_openai_client_points_at_openai():
    client = llm.build_llm_client(make_settings(OPENAI_API_KEY="sk-x"))
    assert str(client.base_url).startswith("https://api.openai.com/v1")


def test_azure_client_without_key_uses_entra_token_provider(monkeypatch):
    seen_scopes = []

    def fake_provider(scope):
        seen_scopes.append(scope)

        async def token():
            return "entra-token"
        return token

    monkeypatch.setattr(llm, "_entra_token_provider", fake_provider)
    client = llm.build_llm_client(make_settings(**AZURE_ENV))

    assert str(client.base_url) == "https://my-aoai.openai.azure.com/openai/v1/"
    assert seen_scopes == ["https://cognitiveservices.azure.com/.default"]


def test_real_entra_token_provider_is_built_from_default_credential(monkeypatch):
    import azure.identity.aio as aio

    calls = {}

    class FakeCredential:
        pass

    def fake_get_provider(credential, scope):
        calls["credential"] = credential
        calls["scope"] = scope
        return "provider"

    monkeypatch.setattr(aio, "DefaultAzureCredential", FakeCredential)
    monkeypatch.setattr(aio, "get_bearer_token_provider", fake_get_provider)

    assert llm._entra_token_provider("scope/.default") == "provider"
    assert isinstance(calls["credential"], FakeCredential)
    assert calls["scope"] == "scope/.default"


# ---------------------------------------------------------------------------
# Wire-level behavior against a mock Azure endpoint
# ---------------------------------------------------------------------------

async def test_azure_chat_request_shape_with_entra_token(monkeypatch):
    async def token():
        return "entra-token"
    monkeypatch.setattr(llm, "_entra_token_provider", lambda scope: token)

    settings = make_settings(**AZURE_ENV)
    fake = FakeAzure()
    client = fake.client(settings)

    resp = await client.chat.completions.create(
        model=settings.chat_model,
        messages=[{"role": "user", "content": "hi"}],
    )

    assert resp.choices[0].message.content == "mock answer"
    req = fake.requests[0]
    assert str(req.url) == "https://my-aoai.openai.azure.com/openai/v1/chat/completions"
    assert req.headers["authorization"] == "Bearer entra-token"
    assert json.loads(req.content)["model"] == "chat-dep"


async def test_azure_embeddings_with_api_key(monkeypatch):
    settings = make_settings(**AZURE_ENV, AZURE_OPENAI_API_KEY="azure-key")
    fake = FakeAzure()
    client = fake.client(settings)

    resp = await client.embeddings.create(model=settings.embedding_model, input=["a", "b"])

    assert len(resp.data) == 2 and len(resp.data[0].embedding) == 1536
    req = fake.requests[0]
    assert str(req.url) == "https://my-aoai.openai.azure.com/openai/v1/embeddings"
    assert req.headers["authorization"] == "Bearer azure-key"
    assert json.loads(req.content)["model"] == "embed-dep"


async def test_app_embedder_and_hyde_run_against_azure(monkeypatch):
    """The app's own services, not just the SDK, work on the Azure path."""
    from app.services import embedder as embedder_mod
    from app.services import retriever as retriever_mod

    settings = make_settings(**AZURE_ENV, AZURE_OPENAI_API_KEY="azure-key")
    fake = FakeAzure()
    client = fake.client(settings)

    monkeypatch.setattr(embedder_mod, "settings", settings)
    monkeypatch.setattr(embedder_mod, "get_llm_client", lambda: client)
    monkeypatch.setattr(retriever_mod, "settings", settings)
    monkeypatch.setattr(retriever_mod, "get_llm_client", lambda: client)

    vectors = await embedder_mod.EmbedderService().embed_texts(["x", "y", "z"])
    assert len(vectors) == 3

    retriever = retriever_mod.HybridRetriever(db_session=None)
    hyde = await retriever._generate_hyde_answer("What is the IRA limit?")
    assert hyde == "mock answer"

    paths = [r.url.path for r in fake.requests]
    assert paths == ["/openai/v1/embeddings", "/openai/v1/chat/completions"]
    models = [json.loads(r.content)["model"] for r in fake.requests]
    assert models == ["embed-dep", "chat-dep"]
