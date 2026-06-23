"""
FastAPI application factory and AWS Lambda handler.

The Mangum adapter bridges the FastAPI ASGI app to:
  - AWS Lambda Function URL (RESPONSE_STREAM mode)
  - AWS API Gateway HTTP API (v2 payload format)

Architecture:
  - All route logic lives in app/api/v1/
  - This file wires up middleware, exception handlers, and the Lambda export
  - API key authentication is enforced on every route except /health via middleware
  - Request IDs are injected into structlog context vars for distributed tracing
  - Rate limiting is enforced per X-API-Key via slowapi

Security:
  - X-API-Key header is validated against API_SECRET_KEY env var
  - Comparison uses hmac.compare_digest for timing-safe equality check
  - Docs endpoints are disabled in production
  - Rate limits: configurable per endpoint via RATE_LIMIT_* env vars
  - CORS origins: set CORS_ALLOWED_ORIGINS env var for production (comma-separated)
"""

import hmac
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from mangum import Mangum
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.base import RequestResponseEndpoint

from app.api.v1.router import api_router
from app.config import get_settings
from app.rate_limiter import limiter  # shared singleton — avoids circular import
from app.utils.exceptions import (
    AssetComplianceBaseError,
    asset_compliance_exception_handler,
)
from app.utils.logger import configure_logging

settings = get_settings()
logger = structlog.get_logger(__name__)

# Routes that do NOT require API key authentication
_PUBLIC_PATHS = {"/health", "/docs", "/redoc", "/openapi.json"}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: configure logging and validate Pinecone index dimension on startup."""
    configure_logging(level=settings.log_level)
    logger.info(
        "asset_compliance_ai_starting",
        env=settings.app_env,
        chat_model=settings.chat_agent_model,
        embedding_model=settings.embedding_model,
        rate_limits={
            "audit": settings.rate_limit_audit,
            "ingest": settings.rate_limit_ingest,
            "chat": settings.rate_limit_chat,
        },
    )

    # Validate Pinecone index dimension at cold start
    try:
        from app.dependencies import _get_pinecone_index
        index = _get_pinecone_index()
        stats = index.describe_index_stats()
        dimension = getattr(stats, "dimension", None)
        if dimension is None and isinstance(stats, dict):
            dimension = stats.get("dimension")

        if dimension is not None and dimension != settings.embedding_dimensions:
            raise ValueError(
                f"Pinecone index dimension mismatch: Index has dimension {dimension}, "
                f"but application expected {settings.embedding_dimensions}."
            )
        logger.info("pinecone_index_validation_successful", dimension=dimension)
    except Exception as exc:
        logger.critical("pinecone_index_validation_failed", error=type(exc).__name__)
        raise

    yield
    logger.info("asset_compliance_ai_shutting_down")


def create_app() -> FastAPI:
    """Construct and return the configured FastAPI application."""
    app = FastAPI(
        title="Asset Compliance AI",
        description=(
            "Serverless LangGraph microservice for automated physical asset "
            "compliance auditing. Provides document ingestion, multi-agent "
            "audit workflows, and auditor Q&A chat."
        ),
        version="1.0.0",
        # Disable interactive docs in production to reduce attack surface
        docs_url="/docs" if settings.app_env != "production" else None,
        redoc_url="/redoc" if settings.app_env != "production" else None,
        lifespan=lifespan,
    )

    # ── Rate limiting ──────────────────────────────────────────────────────────
    # Attach the limiter state to the app instance so SlowAPIMiddleware can
    # read it.  The RateLimitExceeded handler returns a standard 429 JSON body.
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
    app.add_middleware(SlowAPIMiddleware)

    # ── CORS ──────────────────────────────────────────────────────────────────
    # SECURITY: Do NOT combine allow_origins=["*"] with allow_credentials=True.
    # Set CORS_ALLOWED_ORIGINS as a comma-separated env var for non-dev envs.
    # Example: CORS_ALLOWED_ORIGINS=https://app.yourdomain.com
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["POST", "GET", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-API-Key", "X-Request-ID"],
    )

    # ── Custom exception handler ───────────────────────────────────────────────
    app.add_exception_handler(
        AssetComplianceBaseError,
        asset_compliance_exception_handler,  # type: ignore[arg-type]
    )

    # ── Correlation ID middleware ──────────────────────────────────────────────
    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next: RequestResponseEndpoint) -> Response:
        """
        Extract X-Request-ID header or generate a new UUID.
        Bind it to structlog contextvars so all logs in this request share it.
        """
        structlog.contextvars.clear_contextvars()
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        structlog.contextvars.bind_contextvars(request_id=request_id)
        
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    # ── API key middleware ─────────────────────────────────────────────────────
    @app.middleware("http")
    async def api_key_auth(request: Request, call_next: RequestResponseEndpoint) -> Response:
        """
        Validate X-API-Key header on all non-public routes.

        The key must match API_SECRET_KEY from the environment.
        Uses hmac.compare_digest to prevent timing attacks.
        This key is shared with the enterprise asset management system.
        """
        if request.url.path in _PUBLIC_PATHS:
            return await call_next(request)

        provided_key = request.headers.get("X-API-Key", "")
        expected_key = settings.api_secret_key.get_secret_value()

        # Both strings must be encoded for compare_digest
        if not hmac.compare_digest(
            provided_key.encode("utf-8"),
            expected_key.encode("utf-8"),
        ):
            logger.warning(
                "api_key_auth_failed",
                path=request.url.path,
                method=request.method,
                # Never log the actual key — only whether one was provided
                key_provided=bool(provided_key),
            )
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "error": {
                        "code": "UNAUTHORIZED",
                        "message": "Missing or invalid X-API-Key header.",
                    }
                },
            )

        return await call_next(request)

    # ── Versioned API router ───────────────────────────────────────────────────
    app.include_router(api_router, prefix="/api/v1")

    # ── Health check (public, unauthenticated) ─────────────────────────────────
    @app.get("/health", tags=["health"], summary="Health check")
    async def health_check() -> dict[str, str]:
        """Returns service status. No authentication required."""
        return {"status": "ok"}

    return app


app = create_app()

# ── Lambda handler ────────────────────────────────────────────────────────────
# Mangum wraps the ASGI app for AWS Lambda + API Gateway / Function URL.
# lifespan="off" because Lambda manages the process lifecycle externally.
handler = Mangum(app, lifespan="off")
