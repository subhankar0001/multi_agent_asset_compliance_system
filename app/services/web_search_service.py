"""
Web search fallback service using DuckDuckGo.

Used by the chat agent when Pinecone returns no relevant results
and asset spec metadata is insufficient to answer the question.

The DuckDuckGo client is synchronous, so we run it in a thread
to avoid blocking the asyncio event loop.
"""

import asyncio
from typing import Any

import structlog
from ddgs import DDGS
from tenacity import retry, stop_after_attempt, wait_exponential

logger = structlog.get_logger(__name__)


def _run_ddg_search(query: str, max_results: int) -> list[dict[str, Any]]:
    """Run the synchronous DDGS text search."""
    with DDGS() as ddgs:
        return list(ddgs.text(query, max_results=max_results))


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=1, max=5),
    reraise=True,
)
async def search(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """
    Perform a web search via DuckDuckGo and return structured results.

    Returns a list of result dicts with keys: url, title, content, score.
    If DuckDuckGo returns no results, an empty list is returned.

    Used as the third-tier fallback in the chat endpoint when both Pinecone
    and asset spec context are insufficient to answer the question.
    """
    # Run in a threadpool so we don't block the async event loop
    ddg_results = await asyncio.to_thread(_run_ddg_search, query, max_results)

    results = []
    for r in ddg_results:
        results.append(
            {
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "content": r.get("body", ""),
                "score": 1.0,
            }
        )

    logger.info("web_search_complete", query=query, results_count=len(results))
    return results
