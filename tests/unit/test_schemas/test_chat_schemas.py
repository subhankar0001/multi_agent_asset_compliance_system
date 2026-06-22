"""Unit tests for chat schemas."""

import pytest
from pydantic import ValidationError

from app.schemas.chat import ChatRequest, ChatResponse, Message, SourceCitation


def test_message_valid():
    m = Message(role="user", content="What is the max pressure?")
    assert m.role == "user"


def test_message_invalid_role():
    with pytest.raises(ValidationError):
        Message(role="system", content="test")


def test_chat_request_valid(sample_asset_spec):
    req = ChatRequest(
        asset_id="abc-123",
        asset_spec=sample_asset_spec,
        question="What is the maximum operating pressure?",
    )
    assert req.asset_id == "abc-123"
    assert req.conversation_history == []
    assert req.doc_type_filter is None


def test_chat_request_empty_question_rejected(sample_asset_spec):
    with pytest.raises(ValidationError):
        ChatRequest(asset_id="abc-123", asset_spec=sample_asset_spec, question="")


def test_chat_request_too_many_history_items_rejected(sample_asset_spec):
    history = [
        Message(role="user" if i % 2 == 0 else "assistant", content=f"msg {i}") for i in range(51)
    ]
    with pytest.raises(ValidationError):
        ChatRequest(
            asset_id="abc-123",
            asset_spec=sample_asset_spec,
            question="test?",
            conversation_history=history,
        )


def test_chat_response_valid():
    resp = ChatResponse(
        asset_id="abc-123",
        answer="The max pressure is 150 PSI.",
        sources=[],
        search_path="pinecone_rag",
        web_search_used=False,
    )
    assert resp.search_path == "pinecone_rag"
    assert not resp.web_search_used


def test_source_citation_optional_fields():
    citation = SourceCitation(
        doc_id="doc-1",
        doc_type="user_manual",
        filename="manual.pdf",
    )
    assert citation.page is None
    assert citation.excerpt is None
