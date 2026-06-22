"""
Rate limiter singleton — shared across all route modules.

Defined in its own module to break the circular import that would occur if
routes imported the limiter from ``app.main`` (since main.py itself imports
from the router, which imports the routes).

Usage in route handlers::

    from app.rate_limiter import limiter

    @router.post("/run")
    @limiter.limit(lambda: get_settings().rate_limit_audit)
    async def run_audit(request: Request, ...):
        ...
"""

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def _get_api_key_for_rate_limit(request: Request) -> str:
    """
    Rate limit key function: use X-API-Key if present, else fall back to IP.

    This ensures rate limits are enforced per authenticated client rather than
    per shared NAT gateway IP, while still protecting unauthenticated paths.
    """
    key = request.headers.get("X-API-Key")
    return key if key else get_remote_address(request)


# Module-level limiter instance — imported by both main.py and route modules.
limiter = Limiter(key_func=_get_api_key_for_rate_limit)
