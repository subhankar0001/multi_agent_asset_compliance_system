"""
Custom exception hierarchy and FastAPI exception handlers.

All errors returned to API clients follow a consistent JSON envelope:
  {
    "error": {
      "code": "ERROR_CODE_SLUG",
      "message": "Human-readable description",
      "path": "/api/v1/..."
    }
  }

This makes error handling on the Django client side deterministic.
"""

from fastapi import Request, status
from fastapi.responses import JSONResponse


class AssetComplianceBaseError(Exception):
    """Base class for all application-specific errors."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code: str = "INTERNAL_ERROR"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class AssetNotFoundError(AssetComplianceBaseError):
    """Raised when the requested asset does not exist in Pinecone."""

    status_code = status.HTTP_404_NOT_FOUND
    error_code = "ASSET_NOT_FOUND"


class DocumentIngestError(AssetComplianceBaseError):
    """Raised when a document cannot be parsed, embedded, or upserted."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    error_code = "DOCUMENT_INGEST_ERROR"


class AuditRunError(AssetComplianceBaseError):
    """Raised when the LangGraph audit pipeline fails unrecoverably."""

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code = "AUDIT_RUN_ERROR"


class RateLimitError(AssetComplianceBaseError):
    """Raised when an upstream API rate limit is hit after retries are exhausted."""

    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    error_code = "RATE_LIMIT_EXCEEDED"


class EmbeddingError(AssetComplianceBaseError):
    """Raised when the embedding service fails after retries."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    error_code = "EMBEDDING_SERVICE_ERROR"


async def asset_compliance_exception_handler(
    request: Request,
    exc: AssetComplianceBaseError,
) -> JSONResponse:
    """
    FastAPI exception handler for all AssetComplianceBaseError subclasses.

    Registered in app/main.py via app.add_exception_handler().
    Returns a consistent JSON error envelope.
    """
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.error_code,
                "message": exc.message,
                "path": str(request.url),
            }
        },
    )
