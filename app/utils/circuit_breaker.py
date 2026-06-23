"""
Circuit breaker utility for external services.

Prevents cascading failures and retry storms by failing fast when
a downstream service (Pinecone, LLM, DDG) repeatedly fails.
"""

import asyncio
import time
from functools import wraps
from typing import Any, Callable, TypeVar

import structlog

from app.utils.exceptions import AssetComplianceBaseError

logger = structlog.get_logger(__name__)

T = TypeVar("T")


class CircuitBreakerOpenError(AssetComplianceBaseError):
    """Raised when the circuit breaker is OPEN and rejecting calls."""
    pass


class CircuitBreaker:
    """
    A simple state machine for a circuit breaker.
    CLOSED -> HALF_OPEN -> OPEN
    """

    def __init__(self, name: str, failure_threshold: int = 3, recovery_timeout: int = 60):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = 0.0
        self.state = "CLOSED"

    def _check_state(self) -> None:
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "HALF_OPEN"
                logger.info("circuit_breaker_half_open", circuit=self.name)
            else:
                raise CircuitBreakerOpenError(f"Circuit '{self.name}' is OPEN.")

    def _on_success(self) -> None:
        if self.state != "CLOSED":
            logger.info("circuit_breaker_closed", circuit=self.name)
        self.failure_count = 0
        self.state = "CLOSED"

    def _on_failure(self, exc: Exception) -> None:
        # Ignore client-side validation errors
        if isinstance(exc, (ValueError, TypeError)):
            return

        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.state != "OPEN" and self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            logger.error("circuit_breaker_opened", circuit=self.name, threshold=self.failure_threshold)

    def __call__(self, func: Callable[..., T]) -> Callable[..., T]:
        if asyncio.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                self._check_state()
                try:
                    result = await func(*args, **kwargs)
                    self._on_success()
                    return result
                except CircuitBreakerOpenError:
                    raise
                except Exception as exc:
                    self._on_failure(exc)
                    raise
            return async_wrapper  # type: ignore
        else:
            @wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                self._check_state()
                try:
                    result = func(*args, **kwargs)
                    self._on_success()
                    return result
                except CircuitBreakerOpenError:
                    raise
                except Exception as exc:
                    self._on_failure(exc)
                    raise
            return sync_wrapper  # type: ignore


_breakers: dict[str, CircuitBreaker] = {}


def circuit_breaker(name: str, failure_threshold: int = 3, recovery_timeout: int = 60) -> Any:
    """Decorator to apply a named circuit breaker to a function."""
    if name not in _breakers:
        _breakers[name] = CircuitBreaker(name, failure_threshold, recovery_timeout)
    return _breakers[name]
