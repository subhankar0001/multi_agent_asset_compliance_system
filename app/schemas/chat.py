"""
Pydantic schemas for the auditor chat endpoint.

Defines the request and response models for POST /api/v1/chat/query.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.audit import AssetSpec


class Message(BaseModel):
    """One turn in a conversation history."""

    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1)


class SourceCitation(BaseModel):
    """Reference to a specific document chunk that contributed to a chat answer."""

    doc_id: str
    doc_type: str
    filename: str
    page: int | None = None
    excerpt: str | None = None


class ChatRequest(BaseModel):
    """Request body for POST /api/v1/chat/query."""

    asset_id: str = Field(..., min_length=1)
    asset_spec: AssetSpec = Field(..., description="Asset metadata from backend client")
    question: str = Field(..., min_length=1, max_length=2000)
    conversation_history: list[Message] = Field(
        default_factory=list,
        max_length=50,
        description=(
            "Full prior turns in this session (max 50). "
            "Lambda is stateless — the backend client passes the full history."
        ),
    )
    previous_verdicts: list[dict[str, Any]] | None = Field(
        default=None,
        description="Recent audit verdicts — enables questions about past audit findings",
    )
    doc_type_filter: Literal[
        "user_manual",
        "safety_sheet",
        "compliance_spec",
        "installation_image",
        "other",
    ] | None = Field(
        default=None,
        description=(
            "Optional: restrict RAG retrieval to one doc_type. "
            "e.g. 'safety_sheet', 'user_manual'. "
            "If null, searches across all document types for this asset."
        ),
    )


class ChatResponse(BaseModel):
    """Response body for POST /api/v1/chat/query."""

    asset_id: str
    answer: str
    sources: list[SourceCitation] = Field(
        default_factory=list,
        description="Documents that contributed to this answer",
    )
    search_path: Literal["pinecone_rag", "asset_spec", "web_search"] = Field(
        ...,
        description="Which retrieval path produced the answer",
    )
    web_search_used: bool = False
