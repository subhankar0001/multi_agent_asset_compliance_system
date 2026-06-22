"""
FastAPI dependency injection providers.

All external clients are initialised once per Lambda cold start and
reused across requests via module-level LRU-cached singletons.
FastAPI's Depends() system injects them cleanly into route handlers.

Pattern: private `_get_*` functions are cached at the module level;
public `get_*` wrappers are the FastAPI Depends targets.
"""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

import boto3
import structlog
from fastapi import Depends
from langchain.chat_models import init_chat_model
from langchain.embeddings import init_embeddings
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from pinecone import Index, Pinecone

from app.config import Settings, get_settings
from app.utils.offline_clients import LocalDynamoDBClient, LocalPineconeIndex, LocalS3Client

logger = structlog.get_logger(__name__)


# ── Singleton client factories ─────────────────────────────────────────────


@lru_cache
def _get_pinecone_index() -> Index:
    """Initialise and cache the Pinecone index client."""
    settings = get_settings()
    if settings.local_offline:
        logger.info("local_offline_pinecone_initialised")
        return LocalPineconeIndex(Path(".local_storage/qdrant"), settings.embedding_dimensions)
    pc = Pinecone(api_key=settings.pinecone_api_key.get_secret_value())
    index: Index = pc.Index(settings.pinecone_index_name)
    logger.info("pinecone_client_initialised", index=settings.pinecone_index_name)
    return index


def _get_api_key(provider: str, settings: Settings) -> str | None:
    if provider == "anthropic" and settings.anthropic_api_key:
        return settings.anthropic_api_key.get_secret_value()
    if provider == "openai" and settings.openai_api_key:
        return settings.openai_api_key.get_secret_value()
    if provider == "google_genai" and settings.google_api_key:
        return settings.google_api_key.get_secret_value()
    if provider in ("xai", "grok") and settings.xai_api_key:
        return settings.xai_api_key.get_secret_value()
    return None


@lru_cache
def _get_agent_llm(provider: str, model: str) -> BaseChatModel:
    """Initialise and cache a generic BaseChatModel for a specific agent."""
    settings = get_settings()
    api_key = _get_api_key(provider, settings)

    # init_chat_model will fallback to os.environ if api_key is None
    kwargs = {"api_key": api_key} if api_key else {}

    client = init_chat_model(  # type: ignore[call-overload]
        model=model, model_provider=provider, **kwargs
    )
    logger.info("llm_client_initialised", provider=provider, model=model)
    return client  # type: ignore[no-any-return]


@lru_cache
def _get_embeddings_model() -> Embeddings:
    """Initialise and cache the generic embeddings model."""
    settings = get_settings()
    provider = settings.embedding_provider
    api_key = _get_api_key(provider, settings)

    kwargs = {"api_key": api_key} if api_key else {}

    embeddings = init_embeddings(model=settings.embedding_model, model_provider=provider, **kwargs)
    logger.info("embeddings_initialised", provider=provider, model=settings.embedding_model)
    return embeddings  # type: ignore[return-value]


@lru_cache
def _get_s3_client() -> Any:  # boto3 clients are not generically typed
    """Initialise and cache the boto3 S3 client."""
    settings = get_settings()
    if settings.local_offline:
        logger.info("local_offline_s3_initialised")
        return LocalS3Client(Path(".local_storage/s3"))
    client = boto3.client("s3", region_name=settings.aws_region)
    logger.info("s3_client_initialised", region=settings.aws_region)
    return client


@lru_cache
def _get_dynamodb_client() -> Any:  # boto3 clients are not generically typed
    """Initialise and cache the boto3 DynamoDB client."""
    settings = get_settings()
    if settings.local_offline:
        logger.info("local_offline_dynamodb_initialised")
        return LocalDynamoDBClient(Path(".local_storage/dynamodb.db"))
    client = boto3.client("dynamodb", region_name=settings.aws_region)
    logger.info("dynamodb_client_initialised", region=settings.aws_region)
    return client


# ── FastAPI Depends providers ─────────────────────────────────────────────


def get_pinecone_index() -> Index:
    """FastAPI dependency: returns the cached Pinecone index."""
    return _get_pinecone_index()


def get_image_agent_llm() -> BaseChatModel:
    """FastAPI dependency: returns the cached LLM for the image agent."""
    settings = get_settings()
    return _get_agent_llm(settings.image_agent_provider, settings.image_agent_model)


def get_rule_agent_llm() -> BaseChatModel:
    """FastAPI dependency: returns the cached LLM for the rule agent."""
    settings = get_settings()
    return _get_agent_llm(settings.rule_agent_provider, settings.rule_agent_model)


def get_verdict_agent_llm() -> BaseChatModel:
    """FastAPI dependency: returns the cached LLM for the verdict agent."""
    settings = get_settings()
    return _get_agent_llm(settings.verdict_agent_provider, settings.verdict_agent_model)


def get_chat_agent_llm() -> BaseChatModel:
    """FastAPI dependency: returns the cached LLM for the chat agent."""
    settings = get_settings()
    return _get_agent_llm(settings.chat_agent_provider, settings.chat_agent_model)


def get_embeddings() -> Embeddings:
    """FastAPI dependency: returns the cached Embeddings model."""
    return _get_embeddings_model()


def get_s3_client() -> Any:
    """FastAPI dependency: returns the cached S3 client."""
    return _get_s3_client()


def get_dynamodb_client() -> Any:
    """FastAPI dependency: returns the cached DynamoDB client."""
    return _get_dynamodb_client()


# ── Typed dependency aliases for route signatures ─────────────────────────

PineconeDep = Annotated[Index, Depends(get_pinecone_index)]
ImageLLMDep = Annotated[BaseChatModel, Depends(get_image_agent_llm)]
RuleLLMDep = Annotated[BaseChatModel, Depends(get_rule_agent_llm)]
VerdictLLMDep = Annotated[BaseChatModel, Depends(get_verdict_agent_llm)]
ChatLLMDep = Annotated[BaseChatModel, Depends(get_chat_agent_llm)]
EmbeddingsDep = Annotated[Embeddings, Depends(get_embeddings)]
S3Dep = Annotated[Any, Depends(get_s3_client)]
DynamoDBDep = Annotated[Any, Depends(get_dynamodb_client)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
