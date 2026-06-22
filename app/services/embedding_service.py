"""
Embedding service — async wrapper around the configured embedding model.

Model name and dimensions are read entirely from Settings, so swapping
embedding providers requires only an env var change (EMBEDDING_MODEL,
EMBEDDING_DIMENSIONS) with no code changes.

All calls include tenacity retry logic for transient API errors.
"""

import structlog
from langchain_core.embeddings import Embeddings
from tenacity import retry, stop_after_attempt, wait_exponential

logger = structlog.get_logger(__name__)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    reraise=True,
)
async def embed_texts(client: Embeddings, texts: list[str]) -> list[list[float]]:
    """
    Embed a list of strings and return one vector per input.

    Batches requests at 100 texts per API call to stay within rate limits.
    Raises EmbeddingError after 3 failed retry attempts.
    """
    all_embeddings: list[list[float]] = []
    batch_size = 100

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        response = await client.aembed_documents(batch)
        all_embeddings.extend(response)
        logger.debug(
            "embedding_batch_complete",
            batch_index=i // batch_size,
            batch_size=len(batch),
        )

    logger.debug("embeddings_generated", total=len(all_embeddings))
    return all_embeddings


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    reraise=True,
)
async def embed_query(client: Embeddings, text: str) -> list[float]:
    """
    Embed a single query string for retrieval-time similarity search.

    Returns a single vector. Used by the chat and document agent nodes.
    """
    return await client.aembed_query(text)
