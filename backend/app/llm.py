"""
Model provider selection: OpenAI or Azure OpenAI.

The rest of the app only ever sees an AsyncOpenAI client plus
settings.chat_model / settings.embedding_model, so switching provider is
purely a matter of environment variables:

    MODEL_PROVIDER=openai        OPENAI_API_KEY=...
    MODEL_PROVIDER=azure_openai  AZURE_OPENAI_ENDPOINT=https://<name>.openai.azure.com
                                 AZURE_OPENAI_CHAT_DEPLOYMENT=gpt-4o-mini
                                 AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-small

**Why the plain OpenAI client for Azure?**
Azure OpenAI's v1 API (<endpoint>/openai/v1/) accepts the standard OpenAI
request format with the deployment name in the "model" field, so no
api-version pinning or AzureOpenAI-specific client is needed.

**Auth on Azure:** if AZURE_OPENAI_API_KEY is unset we use Microsoft Entra
ID through DefaultAzureCredential. Inside Azure Container Apps that resolves
to the app's managed identity, locally it falls back to `az login`. The
openai client calls the token provider before each request, so tokens
refresh on their own.
"""

import logging
from functools import lru_cache
from typing import Awaitable, Callable

from openai import AsyncOpenAI

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


def azure_v1_base_url(endpoint: str) -> str:
    """https://x.openai.azure.com[/] -> https://x.openai.azure.com/openai/v1/"""
    endpoint = endpoint.rstrip("/")
    if endpoint.endswith("/openai/v1"):
        return endpoint + "/"
    return endpoint + "/openai/v1/"


def _entra_token_provider(scope: str) -> Callable[[], Awaitable[str]]:
    """Async bearer-token provider backed by DefaultAzureCredential."""
    # Imported lazily so the OpenAI-only path does not need azure-identity
    from azure.identity.aio import DefaultAzureCredential, get_bearer_token_provider

    return get_bearer_token_provider(DefaultAzureCredential(), scope)


def build_llm_client(settings: Settings, **client_kwargs) -> AsyncOpenAI:
    """
    Build the async client for the configured provider.

    client_kwargs are passed through to AsyncOpenAI (tests use this to
    inject a mock http_client).
    """
    if settings.model_provider == "azure_openai":
        api_key = settings.azure_openai_api_key or _entra_token_provider(
            settings.azure_openai_token_scope
        )
        logger.info(
            "Model provider: Azure OpenAI (%s auth)",
            "api-key" if settings.azure_openai_api_key else "Entra ID",
        )
        return AsyncOpenAI(
            base_url=azure_v1_base_url(settings.azure_openai_endpoint),
            api_key=api_key,
            **client_kwargs,
        )

    logger.info("Model provider: OpenAI")
    return AsyncOpenAI(api_key=settings.openai_api_key, **client_kwargs)


@lru_cache()
def get_llm_client() -> AsyncOpenAI:
    """Process-wide client (connection pool is reused across requests)."""
    return build_llm_client(get_settings())
