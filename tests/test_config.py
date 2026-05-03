"""Tests for simplified config.py — Task 3.1.

Verifies:
- Config.load() works with only the required sections (llm, agent, tools)
- Config.load() gracefully ignores legacy sections (context, performance, tools.web_search)
- Missing required sections raise ValueError
- Environment variable overrides still work
"""
import os
import pytest
import yaml
from config import (
    Config, LLMConfig, AgentConfig, ToolConfig,
    TerminalConfig, FilesystemConfig,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MINIMAL_CONFIG = {
    "llm": {
        "provider": "openai_compatible",
        "base_url": "http://localhost:8001/v1",
        "model": "test-model",
        "max_tokens": 2048,
        "temperature": 0.2,
        "context_window": 8192,
        "api_key": "",
    },
    "agent": {
        "host": "0.0.0.0",
        "port": 8000,
        "log_level": "INFO",
        "log_file": "logs/agent.log",
        "max_log_size_mb": 100,
    },
    "tools": {
        "terminal": {
            "enabled": True,
            "timeout": 60,
            "allowed_commands": ["npm", "pip", "pytest"],
        },
        "filesystem": {
            "max_file_size_mb": 10,
        },
    },
}

LEGACY_SECTIONS = {
    "context": {
        "embedding_model_path": "models/bge-small-en-v1.5",
        "vector_db": {
            "type": "qdrant",
            "host": "localhost",
            "port": 6333,
            "collection_prefix": "workspace",
            "in_memory": True,
        },
        "chunk_size": 512,
        "chunk_overlap": 50,
        "file_patterns": ["**/*.py"],
        "exclude_patterns": ["**/node_modules/**"],
    },
    "performance": {
        "max_concurrent_tasks": 1,
        "streaming_enabled": True,
        "cache_embeddings": True,
    },
}


def _write_yaml(tmp_path, data):
    """Write a dict as YAML and return the path."""
    p = tmp_path / "config.yaml"
    p.write_text(yaml.dump(data))
    return str(p)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestConfigLoadMinimal:
    """Config.load() with only the required sections."""

    def test_loads_minimal_config(self, tmp_path):
        path = _write_yaml(tmp_path, MINIMAL_CONFIG)
        cfg = Config.load(path)

        assert isinstance(cfg, Config)
        assert cfg.llm.provider == "openai_compatible"
        assert cfg.llm.base_url == "http://localhost:8001/v1"
        assert cfg.llm.model == "test-model"
        assert cfg.agent.port == 8000
        assert cfg.tools.terminal.enabled is True
        assert cfg.tools.filesystem.max_file_size_mb == 10

    def test_config_has_no_context_attribute(self, tmp_path):
        path = _write_yaml(tmp_path, MINIMAL_CONFIG)
        cfg = Config.load(path)
        assert not hasattr(cfg, "context")

    def test_config_has_no_performance_attribute(self, tmp_path):
        path = _write_yaml(tmp_path, MINIMAL_CONFIG)
        cfg = Config.load(path)
        assert not hasattr(cfg, "performance")


class TestConfigLoadWithLegacySections:
    """Config.load() ignores legacy sections that may still be in YAML."""

    def test_loads_with_legacy_context_and_performance(self, tmp_path):
        data = {**MINIMAL_CONFIG, **LEGACY_SECTIONS}
        path = _write_yaml(tmp_path, data)
        cfg = Config.load(path)

        assert isinstance(cfg, Config)
        assert cfg.llm.model == "test-model"

    def test_loads_with_legacy_web_search_in_tools(self, tmp_path):
        data = {**MINIMAL_CONFIG}
        data["tools"] = {
            **MINIMAL_CONFIG["tools"],
            "web_search": {"enabled": False, "max_results": 3, "timeout": 5},
        }
        path = _write_yaml(tmp_path, data)
        cfg = Config.load(path)

        assert isinstance(cfg, Config)
        assert cfg.tools.terminal.enabled is True
        # web_search is silently ignored
        assert not hasattr(cfg.tools, "web_search")

    def test_loads_full_old_config(self, tmp_path):
        """Simulate loading the old config.example.yaml with all sections."""
        data = {**MINIMAL_CONFIG, **LEGACY_SECTIONS}
        data["tools"] = {
            **MINIMAL_CONFIG["tools"],
            "web_search": {"enabled": False, "max_results": 3, "timeout": 5},
        }
        path = _write_yaml(tmp_path, data)
        cfg = Config.load(path)

        assert isinstance(cfg, Config)
        assert cfg.llm.provider == "openai_compatible"
        assert cfg.agent.host == "0.0.0.0"


class TestConfigLoadErrors:
    """Config.load() raises on missing required sections."""

    def test_missing_llm_section(self, tmp_path):
        data = {k: v for k, v in MINIMAL_CONFIG.items() if k != "llm"}
        path = _write_yaml(tmp_path, data)
        with pytest.raises(ValueError):
            Config.load(path)

    def test_missing_agent_section(self, tmp_path):
        data = {k: v for k, v in MINIMAL_CONFIG.items() if k != "agent"}
        path = _write_yaml(tmp_path, data)
        with pytest.raises(ValueError, match="Missing required configuration section: agent"):
            Config.load(path)

    def test_missing_tools_section(self, tmp_path):
        data = {k: v for k, v in MINIMAL_CONFIG.items() if k != "tools"}
        path = _write_yaml(tmp_path, data)
        with pytest.raises(ValueError, match="Missing required configuration section: tools"):
            Config.load(path)

    def test_missing_tools_terminal(self, tmp_path):
        data = {**MINIMAL_CONFIG}
        data["tools"] = {"filesystem": MINIMAL_CONFIG["tools"]["filesystem"]}
        path = _write_yaml(tmp_path, data)
        with pytest.raises(ValueError, match="tools.terminal"):
            Config.load(path)

    def test_missing_tools_filesystem(self, tmp_path):
        data = {**MINIMAL_CONFIG}
        data["tools"] = {"terminal": MINIMAL_CONFIG["tools"]["terminal"]}
        path = _write_yaml(tmp_path, data)
        with pytest.raises(ValueError, match="tools.filesystem"):
            Config.load(path)

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            Config.load("/nonexistent/config.yaml")

    def test_empty_config(self, tmp_path):
        p = tmp_path / "config.yaml"
        p.write_text("")
        with pytest.raises(ValueError, match="empty"):
            Config.load(str(p))


class TestConfigEnvOverrides:
    """Environment variable overrides still work."""

    def test_llm_base_url_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGENT_LLM_BASE_URL", "http://override:9999/v1")
        path = _write_yaml(tmp_path, MINIMAL_CONFIG)
        cfg = Config.load(path)
        assert cfg.llm.base_url == "http://override:9999/v1"

    def test_agent_port_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGENT_PORT", "9999")
        path = _write_yaml(tmp_path, MINIMAL_CONFIG)
        cfg = Config.load(path)
        assert cfg.agent.port == 9999

    def test_llm_provider_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGENT_LLM_PROVIDER", "anthropic")
        path = _write_yaml(tmp_path, MINIMAL_CONFIG)
        cfg = Config.load(path)
        assert cfg.llm.provider == "anthropic"


class TestRemovedDataclasses:
    """Verify removed dataclasses are no longer importable from config."""

    def test_no_context_config(self):
        from config import __dict__ as config_ns
        assert "ContextConfig" not in config_ns

    def test_no_vector_db_config(self):
        from config import __dict__ as config_ns
        assert "VectorDBConfig" not in config_ns

    def test_no_web_search_config(self):
        from config import __dict__ as config_ns
        assert "WebSearchConfig" not in config_ns

    def test_no_performance_config(self):
        from config import __dict__ as config_ns
        assert "PerformanceConfig" not in config_ns
