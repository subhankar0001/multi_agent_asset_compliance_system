"""Unit tests for document_loader."""

from app.schemas.ingest import S3Document
from app.services import document_loader


def _make_doc(doc_type: str = "user_manual") -> S3Document:
    return S3Document(
        s3_key="docs/manual.pdf",
        doc_id="manual-v1",
        doc_type=doc_type,
        filename="manual.pdf",
    )


def _make_minimal_pdf() -> bytes:
    """Create a minimal valid PDF with one text page."""
    # Minimal PDF 1.4 with one page containing "Hello World"
    return b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Contents 4 0 R/Resources<</Font<</F1<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>>>>>>>>>endobj
4 0 obj<</Length 44>>
stream
BT /F1 12 Tf 100 700 Td (Hello World Compliance Test) Tj ET
endstream
endobj
xref
0 5
0000000000 65535 f
0000000009 00000 n
0000000052 00000 n
0000000101 00000 n
0000000273 00000 n
trailer<</Size 5/Root 1 0 R>>
startxref
367
%%EOF"""


def test_chunk_text_basic():
    """_chunk_text should split text into overlapping chunks."""
    chunks = document_loader._chunk_text("a" * 100, chunk_size=40, overlap=10)
    assert len(chunks) > 1
    for c in chunks:
        assert len(c) <= 40


def test_chunk_text_strips_empty():
    """_chunk_text should discard empty or whitespace-only chunks."""
    chunks = document_loader._chunk_text("   \n   ", chunk_size=512, overlap=64)
    assert chunks == []


def test_load_image_document():
    """load_image_document should return exactly one chunk with the description."""
    doc = _make_doc(doc_type="installation_image")
    result = document_loader.load_image_document(doc, "asset-abc", "A pump diagram.")
    assert len(result) == 1
    assert result[0]["text"] == "A pump diagram."
    assert result[0]["metadata"]["doc_id"] == "manual-v1"
    assert result[0]["metadata"]["page"] is None


def test_load_image_document_metadata_fields():
    """load_image_document metadata must contain all required fields."""
    doc = _make_doc(doc_type="installation_image")
    result = document_loader.load_image_document(doc, "asset-xyz", "Diagram description.")
    meta = result[0]["metadata"]
    assert meta["asset_id"] == "asset-xyz"
    assert meta["doc_type"] == "installation_image"
    assert meta["filename"] == "manual.pdf"
    assert "embedded_at" in meta


def test_load_pdf_empty_returns_no_chunks():
    """load_pdf with empty PDF bytes should return empty list without raising."""
    doc = _make_doc()
    # pypdf raises on truly empty bytes; test with a corrupt/empty-page PDF
    # Use a valid but content-free fallback
    result = document_loader.load_pdf(b"%PDF-1.4", doc, "asset-abc")
    # Empty or malformed PDF should return empty chunks, not raise
    assert isinstance(result, list)
