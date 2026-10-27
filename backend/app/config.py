"""
Configuration management using Pydantic Settings v2.

All environment variables are typed and validated at startup.
This ensures configuration errors are caught early.
"""

from typing import List, Literal
from functools import lru_cache

from pydantic import Field, validator, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # ========================================================================
    # FASTAPI & SERVER
    # ========================================================================
    fastapi_env: str = Field(default="development", alias="FASTAPI_ENV")
    fastapi_debug: bool = Field(default=False, alias="FASTAPI_DEBUG")
    secret_key: str = Field(..., alias="SECRET_KEY")
    api_title: str = "AI Financial Advisor"
    api_version: str = "1.0.0"

    # ========================================================================
    # DATABASE
    # ========================================================================
    database_url: str = Field(..., alias="DATABASE_URL")
    sqlalchemy_echo: bool = Field(default=False, alias="SQLALCHEMY_ECHO")
    db_pool_size: int = Field(default=20)
    db_max_overflow: int = Field(default=10)
    db_pool_recycle: int = Field(default=3600)
    db_pool_pre_ping: bool = Field(default=True)

    # ========================================================================
    # REDIS & CACHING
    # ========================================================================
    redis_url: str = Field(..., alias="REDIS_URL")
    redis_queue_db: int = Field(default=1, alias="REDIS_QUEUE_DB")
    cache_ttl_seconds: int = Field(default=3600)

    # ========================================================================
    # MODEL PROVIDER
    # ========================================================================
    # "openai" (default) or "azure_openai". Switched only by environment
    # variables; see app/llm.py for how the client is built.
    model_provider: Literal["openai", "azure_openai"] = Field(
        default="openai", alias="MODEL_PROVIDER"
    )

    # ========================================================================
    # OPENAI API
    # ========================================================================
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_embedding_model: str = Field(
        default="text-embedding-3-small", alias="OPENAI_EMBEDDING_MODEL"
    )
    openai_chat_model: str = Field(default="gpt-4o", alias="OPENAI_CHAT_MODEL")
    openai_vision_model: str = Field(default="gpt-4o", alias="OPENAI_VISION_MODEL")
    openai_batch_embedding: bool = Field(default=False, alias="OPENAI_BATCH_EMBEDDING")
    openai_embedding_dimension: int = 1536  # text-embedding-3-small output dimension

    # ========================================================================
    # AZURE OPENAI (used when MODEL_PROVIDER=azure_openai)
    # ========================================================================
    # Resource endpoint, e.g. https://my-resource.openai.azure.com
    azure_openai_endpoint: str | None = Field(default=None, alias="AZURE_OPENAI_ENDPOINT")
    # Optional. When unset, the app authenticates with Microsoft Entra ID
    # (managed identity in Azure, az login locally) and no key is needed.
    azure_openai_api_key: str | None = Field(default=None, alias="AZURE_OPENAI_API_KEY")
    # Deployment names (what Azure calls the model in API calls)
    azure_openai_chat_deployment: str = Field(
        default="gpt-4o-mini", alias="AZURE_OPENAI_CHAT_DEPLOYMENT"
    )
    azure_openai_embedding_deployment: str = Field(
        default="text-embedding-3-small", alias="AZURE_OPENAI_EMBEDDING_DEPLOYMENT"
    )
    azure_openai_token_scope: str = Field(
        default="https://cognitiveservices.azure.com/.default",
        alias="AZURE_OPENAI_TOKEN_SCOPE",
    )

    # ========================================================================
    # ALPHA VANTAGE API
    # ========================================================================
    alpha_vantage_api_key: str | None = Field(
        default=None, alias="ALPHA_VANTAGE_API_KEY"
    )
    alpha_vantage_mcp_url: str | None = Field(
        default=None, alias="ALPHA_VANTAGE_MCP_URL"
    )

    # ========================================================================
    # AWS / S3 CONFIGURATION
    # ========================================================================
    aws_access_key_id: str = Field(default="test", alias="AWS_ACCESS_KEY_ID")
    aws_secret_access_key: str = Field(default="test", alias="AWS_SECRET_ACCESS_KEY")
    aws_region: str = Field(default="us-east-1", alias="AWS_REGION")
    s3_bucket: str = Field(default="financial-advisor-docs", alias="S3_BUCKET")
    s3_endpoint_url: str | None = Field(
        default=None, alias="S3_ENDPOINT_URL"
    )  # LocalStack in dev, None in prod

    # ========================================================================
    # CORS & SECURITY
    # ========================================================================
    cors_origins: List[str] = Field(
        default=[
            "http://localhost:5173",
            "http://localhost:3000",
            "http://localhost:80",
        ],
        alias="CORS_ORIGINS",
    )
    jwt_expiration_hours: int = Field(default=24, alias="JWT_EXPIRATION_HOURS")
    jwt_refresh_expiration_days: int = Field(default=7, alias="JWT_REFRESH_EXPIRATION_DAYS")
    jwt_algorithm: str = "HS256"

    # ========================================================================
    # PRESIDIO PII DETECTION
    # ========================================================================
    presidio_entities_to_scan: List[str] = Field(
        default=[
            "PERSON",
            "ORGANIZATION",
            "EMAIL_ADDRESS",
            "PHONE_NUMBER",
            "CREDIT_CARD",
            "IBAN_CODE",
            "URL",
            "US_SSN",
            "US_PASSPORT",
        ],
        alias="PRESIDIO_ENTITIES_TO_SCAN",
    )
    presidio_score_threshold: float = Field(
        default=0.75, description="PII detection confidence threshold"
    )

    # ========================================================================
    # RETRIEVAL & RAG CONFIGURATION
    # ========================================================================
    # Dense retrieval (pgvector)
    vector_search_k: int = Field(default=20, description="Top-k for dense retrieval")
    vector_search_threshold: float = Field(
        default=0.5, description="Cosine similarity threshold for vector search"
    )

    # BM25 sparse retrieval
    bm25_k: int = Field(default=20, description="Top-k for BM25 retrieval")

    # Which store answers queries: "pgvector" (default: pgvector dense + local
    # BM25, fused with RRF) or "azure_search" (Azure AI Search hybrid query).
    retrieval_backend: Literal["pgvector", "azure_search"] = Field(
        default="pgvector", alias="RETRIEVAL_BACKEND"
    )
    # Azure AI Search (used when RETRIEVAL_BACKEND=azure_search)
    azure_search_endpoint: str | None = Field(default=None, alias="AZURE_SEARCH_ENDPOINT")
    azure_search_index: str = Field(default="financial-chunks", alias="AZURE_SEARCH_INDEX")
    # Optional. When unset, Microsoft Entra ID (managed identity / az login) is used.
    azure_search_api_key: str | None = Field(default=None, alias="AZURE_SEARCH_API_KEY")
    azure_search_api_version: str = Field(default="2024-07-01", alias="AZURE_SEARCH_API_VERSION")

    # Reranking
    reranker_model: str = Field(
        default="cross-encoder/ms-marco-MiniLM-L-6-v2",
        description="Cross-encoder model for reranking",
    )
    reranker_top_k: int = Field(default=5, description="Top-k after reranking")
    reranker_threshold: float = Field(default=0.1, description="Reranking score threshold")

    # Context compression (LLMLingua)
    compression_target_ratio: float = Field(
        default=0.35, description="Target token compression ratio (0.0-1.0)"
    )

    # Faithfulness scoring
    faithfulness_threshold: float = Field(
        default=0.6, description="Minimum NLI entailment score to accept answer"
    )
    faithfulness_retry_limit: int = Field(
        default=2, description="Max retrieval retries if faithfulness is low"
    )

    # ========================================================================
    # CHUNKING STRATEGY
    # ========================================================================
    chunk_size: int = Field(default=1024, description="Default chunk size in tokens")
    chunk_overlap: int = Field(default=128, description="Overlap between chunks")
    semantic_chunker_breakpoint_threshold: float = Field(
        default=0.5, description="Threshold for semantic chunking breakpoints"
    )

    # ========================================================================
    # ARQ WORKER CONFIGURATION
    # ========================================================================
    arq_pool_size: int = Field(default=10, alias="ARQ_POOL_SIZE")
    arq_job_timeout_seconds: int = Field(default=3600, alias="ARQ_JOB_TIMEOUT_SECONDS")
    arq_keep_result_seconds: int = Field(default=86400)  # 24 hours

    # ========================================================================
    # LOGGING
    # ========================================================================
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    structlog_pretty: bool = Field(default=True, alias="STRUCTLOG_PRETTY")

    # ========================================================================
    # FEATURE FLAGS
    # ========================================================================
    enable_pii_detection: bool = Field(default=True, alias="ENABLE_PII_DETECTION")
    enable_faithfulness_scoring: bool = Field(
        default=True, alias="ENABLE_FAITHFULNESS_SCORING"
    )
    enable_compression: bool = Field(default=True, alias="ENABLE_COMPRESSION")
    enable_audit_logging: bool = Field(default=True, alias="ENABLE_AUDIT_LOGGING")
    enable_hyde_retrieval: bool = Field(default=True, description="HyDE prompt expansion")

    # ========================================================================
    # COMPUTED PROPERTIES
    # ========================================================================
    @property
    def is_production(self) -> bool:
        """Check if running in production mode."""
        return self.fastapi_env == "production"

    @property
    def chat_model(self) -> str:
        """Model name (OpenAI) or deployment name (Azure) for chat calls."""
        if self.model_provider == "azure_openai":
            return self.azure_openai_chat_deployment
        return self.openai_chat_model

    @property
    def embedding_model(self) -> str:
        """Model name (OpenAI) or deployment name (Azure) for embeddings."""
        if self.model_provider == "azure_openai":
            return self.azure_openai_embedding_deployment
        return self.openai_embedding_model

    @property
    def vision_model(self) -> str:
        """Model used to read uploaded images. Azure reuses the chat deployment."""
        if self.model_provider == "azure_openai":
            return self.azure_openai_chat_deployment
        return self.openai_vision_model

    @property
    def cors_origins_list(self) -> List[str]:
        """Get CORS origins as list."""
        if isinstance(self.cors_origins, str):
            return [origin.strip() for origin in self.cors_origins.split(",")]
        return self.cors_origins

    @property
    def jwt_expiration_seconds(self) -> int:
        """Get JWT expiration in seconds."""
        return self.jwt_expiration_hours * 3600

    @property
    def jwt_refresh_expiration_seconds(self) -> int:
        """Get JWT refresh expiration in seconds."""
        return self.jwt_refresh_expiration_days * 86400

    # ========================================================================
    # VALIDATION
    # ========================================================================
    @validator("compression_target_ratio")
    def validate_compression_ratio(cls, v):
        """Ensure compression ratio is between 0 and 1."""
        if not 0.0 <= v <= 1.0:
            raise ValueError("compression_target_ratio must be between 0.0 and 1.0")
        return v

    @validator("presidio_score_threshold")
    def validate_presidio_threshold(cls, v):
        """Ensure Presidio threshold is between 0 and 1."""
        if not 0.0 <= v <= 1.0:
            raise ValueError("presidio_score_threshold must be between 0.0 and 1.0")
        return v

    @validator("faithfulness_threshold")
    def validate_faithfulness_threshold(cls, v):
        """Ensure faithfulness threshold is between 0 and 1."""
        if not 0.0 <= v <= 1.0:
            raise ValueError("faithfulness_threshold must be between 0.0 and 1.0")
        return v

    @model_validator(mode="after")
    def check_model_provider_settings(self):
        """Fail at startup if the chosen provider is missing its settings."""
        if self.model_provider == "openai" and not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required when MODEL_PROVIDER=openai")
        if self.model_provider == "azure_openai" and not self.azure_openai_endpoint:
            raise ValueError(
                "AZURE_OPENAI_ENDPOINT is required when MODEL_PROVIDER=azure_openai"
            )
        if self.retrieval_backend == "azure_search" and not self.azure_search_endpoint:
            raise ValueError(
                "AZURE_SEARCH_ENDPOINT is required when RETRIEVAL_BACKEND=azure_search"
            )
        return self

    @model_validator(mode="after")
    def set_alpha_vantage_mcp_url(self):
        """Default MCP URL when API key is provided and URL not set."""
        if not self.alpha_vantage_mcp_url and self.alpha_vantage_api_key:
            self.alpha_vantage_mcp_url = (
                f"https://mcp.alphavantage.co/mcp?apikey={self.alpha_vantage_api_key}"
            )
        return self

    class Config:
        """Pydantic configuration."""
        env_file = ".env"
        case_sensitive = False
        json_encoders = {
            # Add custom JSON encoders if needed
        }


@lru_cache()
def get_settings() -> Settings:
    """
    Get cached settings instance.

    Using LRU cache ensures Settings is only loaded once,
    improving performance and consistency throughout the app lifetime.
    """
    return Settings()
