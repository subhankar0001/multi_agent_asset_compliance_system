"""
Document loading and chunking service.

Supports PDF documents and image-type documents.

For PDFs:
  - Text is extracted page-by-page using pypdf
  - Each page's text is split into overlapping character-level chunks
  - Each chunk carries full metadata: asset_id, doc_id, doc_type, filename,
    chunk_index, page number, and the source text (stored for retrieval display)

For image documents (doc_type == "installation_image"):
  - A single vector is stored whose text is the LLM-generated description
  - The description is produced upstream by the image agent / ingest handler
  - This allows image documents to participate in semantic retrieval

Chunk metadata preserves all fields needed for source attribution in
evidence citations and chat responses.
"""

import io
from datetime import UTC, datetime
from typing import Any

import structlog
from pypdf import PdfReader

from app.config import get_settings
from app.schemas.ingest import S3Document

logger = structlog.get_logger(__name__)


def _chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """
    Split text into overlapping chunks by character count.

    Overlap allows adjacent chunks to share context, reducing the chance
    that a relevant clause is split across chunk boundaries.
    """
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return [c.strip() for c in chunks if c.strip()]


def load_pdf(
    raw_bytes: bytes,
    document: S3Document,
    asset_id: str,
) -> list[dict[str, Any]]:
    """
    Parse a PDF into text chunks ready for embedding and Pinecone upsert.

    Each returned dict has:
      - chunk_id: unique string ID for the vector
      - text: the chunk content (also stored in metadata for retrieval display)
      - metadata: all fields needed for source attribution

    Empty pages are skipped silently.
    """
    settings = get_settings()
    try:
        reader = PdfReader(io.BytesIO(raw_bytes))
        pages_to_process = reader.pages
    except Exception as exc:
        logger.warning("pdf_parse_error", doc_id=document.doc_id, error=str(exc))
        return []
    chunks: list[dict[str, Any]] = []
    chunk_global_idx = 0

    for page_num, page in enumerate(pages_to_process, start=1):
        page_text = page.extract_text() or ""
        if not page_text.strip():
            continue

        for chunk_text in _chunk_text(page_text, settings.chunk_size, settings.chunk_overlap):
            chunks.append(
                {
                    "chunk_id": f"{document.doc_id}_p{page_num}_c{chunk_global_idx}",
                    "text": chunk_text,
                    "metadata": {
                        "asset_id": asset_id,
                        "doc_id": document.doc_id,
                        "doc_type": document.doc_type,
                        "filename": document.filename,
                        "chunk_index": chunk_global_idx,
                        "page": page_num,
                        "embedded_at": datetime.now(UTC).isoformat(),
                        # Stored in metadata so it can be returned in retrieval
                        # results without a separate fetch
                        "text": chunk_text,
                    },
                }
            )
            chunk_global_idx += 1

    logger.info(
        "pdf_loaded",
        doc_id=document.doc_id,
        filename=document.filename,
        pages=len(reader.pages),
        chunks=len(chunks),
    )
    return chunks


def load_image_document(
    document: S3Document,
    asset_id: str,
    description: str,
) -> list[dict[str, Any]]:
    """
    Create a single vector record for an image-type document.

    The description is an LLM-generated text summary of the image,
    produced upstream by the image agent or ingest handler.
    Storing it as a vector allows the image to participate in semantic
    retrieval queries alongside PDF documents.
    """
    chunk_id = f"{document.doc_id}_img_0"
    return [
        {
            "chunk_id": chunk_id,
            "text": description,
            "metadata": {
                "asset_id": asset_id,
                "doc_id": document.doc_id,
                "doc_type": document.doc_type,
                "filename": document.filename,
                "chunk_index": 0,
                "page": None,
                "embedded_at": datetime.now(UTC).isoformat(),
                "text": description,
            },
        }
    ]
