"""Configuration management for the agent system."""
from dataclasses import dataclass
from typing import Dict, List, Any
import yaml
import os
from pathlib import Path


@dataclass
class LLMConfig:
    """LLM server configuration."""
    base_url: str
    model: str
    max_tokens: int
    temperature: float
    context_window: int
    provider: str = "openai_compatible"
    api_key: str = ""


@dataclass
class AgentConfig:
    """Agent server configuration."""
    host: str
    port: int
    log_level: str
    log_file: str
    max_log_size_mb: int


@dataclass
class TerminalConfig:
    """Terminal tool configuration."""
    enabled: bool
    timeout: int
    allowed_commands: List[str]


@dataclass
class FilesystemConfig:
    """Filesystem tool configuration."""
    max_file_size_mb: int


@dataclass
class ToolConfig:
    """Tool system configuration."""
    terminal: TerminalConfig
    filesystem: FilesystemConfig


@dataclass
class Config:
    """Main configuration object."""
    llm: LLMConfig
    agent: AgentConfig
    tools: ToolConfig

    @classmethod
    def load(cls, config_path: str = "config.yaml") -> "Config":
        """Load configuration from YAML file with environment variable overrides.

        Args:
            config_path: Path to configuration file

        Returns:
            Loaded configuration object

        Raises:
            FileNotFoundError: If config file doesn't exist
            ValueError: If config is invalid
        """
        # Check if file exists
        if not Path(config_path).exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        # Load YAML
        with open(config_path, 'r') as f:
            data = yaml.safe_load(f)

        if not data:
            raise ValueError("Configuration file is empty")

        # Apply environment variable overrides
        data = cls._apply_env_overrides(data)

        # Validate configuration values
        from server.validation import validate_config_values
        config_errors = validate_config_values(data)
        if config_errors:
            raise ValueError(
                "Configuration validation errors: " + "; ".join(config_errors)
            )

        # Validate required sections
        required_sections = ['llm', 'agent', 'tools']
        for section in required_sections:
            if section not in data:
                raise ValueError(f"Missing required configuration section: {section}")

        # Build configuration objects
        try:
            llm_config = LLMConfig(**data['llm'])
            agent_config = AgentConfig(**data['agent'])

            # Tool configs — only terminal and filesystem are required.
            # Ignore any extra subsections (e.g. legacy web_search).
            tools_data = data['tools']
            if 'terminal' not in tools_data:
                raise ValueError("Missing required configuration field: 'tools.terminal'")
            if 'filesystem' not in tools_data:
                raise ValueError("Missing required configuration field: 'tools.filesystem'")

            terminal_config = TerminalConfig(**tools_data['terminal'])
            filesystem_config = FilesystemConfig(**tools_data['filesystem'])
            tool_config = ToolConfig(
                terminal=terminal_config,
                filesystem=filesystem_config
            )

            return cls(
                llm=llm_config,
                agent=agent_config,
                tools=tool_config
            )

        except KeyError as e:
            raise ValueError(f"Missing required configuration field: {e}") from e
        except TypeError as e:
            raise ValueError(f"Invalid configuration value: {e}") from e

    @staticmethod
    def _apply_env_overrides(data: Dict[str, Any]) -> Dict[str, Any]:
        """Apply environment variable overrides to configuration.

        Environment variables should be prefixed with AGENT_ and use underscores
        to separate nested keys. For example:
        - AGENT_LLM_BASE_URL overrides llm.base_url
        - AGENT_LLM_MODEL overrides llm.model

        Args:
            data: Configuration dictionary

        Returns:
            Configuration with environment overrides applied
        """
        # LLM overrides
        if 'AGENT_LLM_BASE_URL' in os.environ:
            data.setdefault('llm', {})['base_url'] = os.environ['AGENT_LLM_BASE_URL']
        if 'AGENT_LLM_MODEL' in os.environ:
            data.setdefault('llm', {})['model'] = os.environ['AGENT_LLM_MODEL']
        if 'AGENT_LLM_PROVIDER' in os.environ:
            data.setdefault('llm', {})['provider'] = os.environ['AGENT_LLM_PROVIDER']
        if 'AGENT_LLM_API_KEY' in os.environ:
            data.setdefault('llm', {})['api_key'] = os.environ['AGENT_LLM_API_KEY']
        if 'AGENT_LLM_CONTEXT_WINDOW' in os.environ:
            data.setdefault('llm', {})['context_window'] = int(os.environ['AGENT_LLM_CONTEXT_WINDOW'])

        # Agent overrides
        if 'AGENT_HOST' in os.environ:
            data.setdefault('agent', {})['host'] = os.environ['AGENT_HOST']
        if 'AGENT_PORT' in os.environ:
            data.setdefault('agent', {})['port'] = int(os.environ['AGENT_PORT'])

        return data
