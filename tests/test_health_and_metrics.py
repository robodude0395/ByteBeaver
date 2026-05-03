"""Tests for health check endpoint."""
import time
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

import server.api as api_module
from server.api import app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    return TestClient(app)


# ===================================================================
# Health check endpoint tests (simplified server)
# ===================================================================


class TestHealthEndpoint:
    """Tests for GET /health."""

    def test_health_returns_200_when_config_loaded(self, client):
        """Health endpoint always returns 200, even when degraded."""
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_ok_with_valid_config(self, client):
        """When config is loaded with a valid provider, status is 'ok'."""
        mock_config = MagicMock()
        mock_config.llm.provider = "openai_compatible"
        mock_config.llm.model = "test-model"
        mock_config.llm.base_url = "http://localhost:8001/v1"

        with patch.object(api_module, "config", mock_config):
            data = client.get("/health").json()

        assert data["status"] == "ok"
        assert data["message"] == "Server is running"
        assert data["llm"]["provider"] == "openai_compatible"
        assert data["llm"]["model"] == "test-model"
        assert data["llm"]["base_url"] == "http://localhost:8001/v1"

    def test_health_degraded_when_config_not_loaded(self, client):
        """When config is None, status is 'degraded'."""
        with patch.object(api_module, "config", None):
            data = client.get("/health").json()

        assert data["status"] == "degraded"
        assert "not loaded" in data["message"].lower()
        assert data["llm"] is None

    def test_health_degraded_with_unknown_provider(self, client):
        """When provider is not in the valid set, status is 'degraded'."""
        mock_config = MagicMock()
        mock_config.llm.provider = "unknown_provider"
        mock_config.llm.model = "some-model"
        mock_config.llm.base_url = "http://localhost:9999"

        with patch.object(api_module, "config", mock_config):
            data = client.get("/health").json()

        assert data["status"] == "degraded"
        assert "unknown_provider" in data["message"].lower()
        assert data["llm"]["provider"] == "unknown_provider"

    @pytest.mark.parametrize("provider", [
        "openai_compatible", "llamacpp", "vllm", "ollama", "anthropic",
    ])
    def test_health_ok_for_all_valid_providers(self, client, provider):
        """All recognised providers produce status 'ok'."""
        mock_config = MagicMock()
        mock_config.llm.provider = provider
        mock_config.llm.model = "m"
        mock_config.llm.base_url = "http://localhost"

        with patch.object(api_module, "config", mock_config):
            data = client.get("/health").json()

        assert data["status"] == "ok"
        assert data["llm"]["provider"] == provider
