"""
Structured JSON logging via structlog.

All log output is newline-delimited JSON, compatible with:
  - AWS CloudWatch Logs Insights queries
  - Lambda Powertools log correlation
  - Any structured log aggregation platform

Usage:
    import structlog
    logger = structlog.get_logger(__name__)
    logger.info("event_name", key1=value1, key2=value2)

Do NOT use f-string messages in log calls — always use structured key=value pairs.
"""

import logging

import structlog


def configure_logging(level: str = "INFO") -> None:
    """
    Configure structlog for CloudWatch-compatible JSON output.

    Should be called once at application startup (FastAPI lifespan).
    Safe to call multiple times — subsequent calls are no-ops due to structlog's
    internal configuration state.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    structlog.configure(
        processors=[
            # Merge any context vars set via structlog.contextvars.bind_contextvars
            structlog.contextvars.merge_contextvars,
            # Add the log level string to every event
            structlog.processors.add_log_level,
            # ISO 8601 timestamp in UTC
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            # Format exceptions as structured dicts (not raw tracebacks)
            structlog.processors.dict_tracebacks,
            # Render as JSON
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
