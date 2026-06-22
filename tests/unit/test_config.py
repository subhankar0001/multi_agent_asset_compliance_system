"""Unit tests for app/config.py — Settings validation."""

import pytest

from app.config import Settings, get_settings


def test_get_settings_returns_cached_instance():
    """get_settings() should return the same cached instance on repeated calls."""
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2


def test_settings_secret_str_not_in_repr():
    """SecretStr fields must not expose raw values in repr or str."""
    s = get_settings()
    settings_repr = repr(s)
    assert s.anthropic_api_key.get_secret_value() not in settings_repr
    assert s.pinecone_api_key.get_secret_value() not in settings_repr
    assert s.openai_api_key.get_secret_value() not in settings_repr
    assert s.xai_api_key.get_secret_value() not in settings_repr
    assert s.api_secret_key.get_secret_value() not in settings_repr


def test_settings_loads_from_env():
    """Settings should load correctly from the env vars set in conftest."""
    s = get_settings()
    assert s.aws_region == "us-east-1"
    assert s.s3_bucket_name == "test-bucket"
    assert s.image_agent_provider == "mock_provider"
    assert s.image_agent_model == "mock_model"
    assert s.embedding_dimensions == 1536
    assert s.app_env == "development"


def test_settings_secret_values_accessible():
    """SecretStr.get_secret_value() must return the actual value."""
    s = get_settings()
    assert s.anthropic_api_key.get_secret_value() == "test-anthropic-key"
    assert s.pinecone_api_key.get_secret_value() == "test-pinecone-key"
    assert s.openai_api_key.get_secret_value() == "test-openai-key"
    assert s.xai_api_key.get_secret_value() == "test-xai-key"


def test_settings_default_values():
    """Optional settings should fall back to documented defaults."""
    s = get_settings()
    assert s.local_offline is False
    assert s.retrieval_top_k_audit == 20
    assert s.retrieval_top_k_chat == 12
    assert s.chunk_size == 512
    assert s.chunk_overlap == 64
    assert s.llm_max_tokens == 4096
    assert s.llm_chat_max_tokens == 1024


def test_settings_invalid_app_env(monkeypatch):
    """Settings must reject an invalid APP_ENV value."""
    monkeypatch.setenv("APP_ENV", "invalid_env")
    # Clear the lru_cache so a fresh Settings is created
    get_settings.cache_clear()
    with pytest.raises(Exception):
        Settings()
    # Restore cache after test
    get_settings.cache_clear()
