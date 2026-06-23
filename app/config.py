"""
Application settings loaded from environment variables.

All external API keys, model names, and configuration values are read
from the environment — never hardcoded. SecretStr fields prevent secrets
from appearing in logs, tracebacks, or serialised model output.

Usage:
    from app.config import get_settings
    settings = get_settings()  # cached singleton per process
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated application settings sourced from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        # Extra fields are ignored, not rejected — allows future env var additions
        # without breaking existing deployments.
        extra="ignore",
    )

    # ── Local Offline Mode ────────────────────────────────────────────────────
    local_offline: bool = Field(default=False, description="Enable local offline development mode")

    # ── AWS ───────────────────────────────────────────────────────────────────
    aws_region: str = Field(default="us-east-1", description="AWS region for all SDK calls")
    s3_bucket_name: str = Field(
        default="local-bucket", description="S3 bucket holding asset documents and images"
    )

    # ── Pinecone ──────────────────────────────────────────────────────────────
    pinecone_api_key: SecretStr = Field(
        default=SecretStr("offline-dummy"), description="Pinecone API key"
    )
    pinecone_index_name: str = Field(
        default="local-index", description="Pinecone serverless index name"
    )
    pinecone_environment: str = Field(
        default="local", description="Pinecone cloud environment identifier"
    )

    # ── LLM Providers (API Keys) ──────────────────────────────────────────────
    anthropic_api_key: SecretStr | None = Field(default=None, description="Anthropic API key")
    openai_api_key: SecretStr | None = Field(default=None, description="OpenAI API key")
    google_api_key: SecretStr | None = Field(default=None, description="Google Gemini API key")
    xai_api_key: SecretStr | None = Field(default=None, description="xAI Grok API key")

    # ── Agent Configuration ───────────────────────────────────────────────────
    image_agent_provider: str = Field(default="openai", description="LLM provider for image agent")
    image_agent_model: str = Field(default="gpt-4o", description="Model for image agent")

    rule_agent_provider: str = Field(default="openai", description="LLM provider for rule agent")
    rule_agent_model: str = Field(default="gpt-4o", description="Model for rule agent")

    verdict_agent_provider: str = Field(
        default="openai", description="LLM provider for verdict agent"
    )
    verdict_agent_model: str = Field(default="gpt-4o", description="Model for verdict agent")

    chat_agent_provider: str = Field(default="openai", description="LLM provider for chat agent")
    chat_agent_model: str = Field(default="gpt-4o", description="Model for chat agent")

    # ── LLM Max Tokens ────────────────────────────────────────────────────────
    llm_max_tokens: int = Field(
        default=4096,
        ge=1,
        le=8192,
        description="Max tokens for audit verdict generation",
    )
    llm_chat_max_tokens: int = Field(
        default=1024,
        ge=1,
        le=4096,
        description="Max tokens for chat responses",
    )

    # ── Embeddings ────────────────────────────────────────────────────────────
    embedding_provider: str = Field(
        default="openai",
        description="Embedding provider name (e.g. openai)",
    )
    embedding_model: str = Field(
        default="text-embedding-3-small",
        description="Embedding model name — change via env var without code changes",
    )
    embedding_dimensions: int = Field(
        default=1536,
        ge=1,
        description="Embedding vector dimensions — must match Pinecone index configuration",
    )
    embedding_batch_size: int = Field(
        default=50,
        ge=1,
        le=500,
        description="Number of texts embedded per API call to stay within rate limits",
    )

    # ── LangSmith (optional tracing) ──────────────────────────────────────────
    langchain_tracing_v2: bool = Field(default=False, description="Enable LangSmith tracing")
    langchain_api_key: SecretStr | None = Field(
        default=None, description="LangSmith API key (optional)"
    )
    langchain_project: str = Field(
        default="asset-compliance-ai", description="LangSmith project name"
    )

    # ── Application ───────────────────────────────────────────────────────────
    app_env: Literal["development", "staging", "production"] = Field(
        default="development", description="Deployment environment"
    )
    log_level: str = Field(default="INFO", description="Logging level")
    cors_allowed_origins: list[str] = Field(
        default=["http://localhost:8000"],
        description=(
            "Allowed CORS origins. In production, set to your backend client domain(s) "
            "to prevent the wildcard + credentials CORS vulnerability. "
            'Example: CORS_ALLOWED_ORIGINS=["https://app.yourdomain.com"]'
        ),
    )
    retrieval_top_k_audit: int = Field(
        default=20, ge=1, le=100, description="Top-k chunks retrieved for audit queries"
    )
    retrieval_top_k_chat: int = Field(
        default=12, ge=1, le=50, description="Top-k chunks retrieved for chat queries"
    )
    chunk_size: int = Field(
        default=512, ge=64, le=4096, description="Document chunk size in characters"
    )
    chunk_overlap: int = Field(
        default=64, ge=0, le=512, description="Overlap between consecutive chunks in characters"
    )
    evidence_bundle_cap: int = Field(
        default=20, ge=1, le=100, description="Max number of evidence items passed to verdict LLM and returned in API"
    )
    audit_timeout_seconds: int = Field(
        default=120, ge=10, le=800, description="Max time allowed for the audit graph execution before timing out"
    )

    # ── DynamoDB ──────────────────────────────────────────────────────────────
    dynamodb_audit_table: str = Field(
        default="local-audit-runs",
        description=(
            "DynamoDB table name used for audit run idempotency tracking. "
            "Populated automatically from CloudFormation via SAM env vars."
        ),
    )

    # ── Rate Limiting ─────────────────────────────────────────────────────────
    # Format: "<count>/<period>" — e.g. "10/minute", "100/hour".
    # Enforced by slowapi on the Lambda Function URL ingress.
    rate_limit_audit: str = Field(
        default="10/minute",
        description="Max audit run requests per source IP per period",
    )
    rate_limit_ingest: str = Field(
        default="30/minute",
        description="Max ingest requests per source IP per period",
    )
    rate_limit_chat: str = Field(
        default="60/minute",
        description="Max chat query requests per source IP per period",
    )

    # ── Authentication ────────────────────────────────────────────────────────
    api_secret_key: SecretStr = Field(
        default=SecretStr("local-api-secret-key-12345"),
        description=(
            "Shared API secret key. Must match the API_SECRET_KEY configured in the "
            "enterprise asset management system. All inbound requests must include the "
            "X-API-Key header with this value."
        ),
    )

    @model_validator(mode="after")
    def validate_cors(self) -> "Settings":
        """Prevent wildcard CORS in production to mitigate SEC-1."""
        if self.app_env == "production" and "*" in self.cors_allowed_origins:
            raise ValueError("Wildcard CORS (['*']) is not allowed in production environments.")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance. Cache is per-process (Lambda warm start safe)."""
    return Settings()
