"""Configuration management for the agent system."""
from dataclasses import dataclass, field
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


@dataclass
class AgentConfig:
    """Agent server configuration."""
    host: str
    port: int
    log_level: str
    log_file: str
    max_log_size_mb: int


@dataclass
class VectorDBConfig:
    """Vector database configuration."""
    type: str
    host: str
    port: int
    collection_prefix: str
    in_memory: bool


@dataclass
class ContextConfig:
    """Context engine configuration."""
    embedding_model_path: str
    vector_db: VectorDBConfig
    chunk_size: int
    chunk_overlap: int
    file_patterns: List[str]
    exclude_patterns: List[str]


@dataclass
class WebSearchConfig:
    """Web search tool configuration."""
    enabled: bool
    max_results: int
    timeout: int


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
    web_search: WebSearchConfig
    terminal: TerminalConfig
    filesystem: FilesystemConfig


@dataclass
class PerformanceConfig:
    """Performance configuration."""
    max_concurrent_tasks: int
    streaming_enabled: bool
    cache_embeddings: bool


@dataclass
class Config:
    """Main configuration object."""
    llm: LLMConfig
    agent: AgentConfig
    context: ContextConfig
    tools: ToolConfig
    performance: PerformanceConfig

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

        # Validate required sections
        required_sections = ['llm', 'agent', 'context', 'tools', 'performance']
        for section in required_sections:
            if section not in data:
                raise ValueError(f"Missing required configuration section: {section}")

        # Build configuration objects
        try:
            llm_config = LLMConfig(**data['llm'])
            agent_config = AgentConfig(**data['agent'])

            # Vector DB config
            vector_db_config = VectorDBConfig(**data['context']['vector_db'])
            context_config = ContextConfig(
                embedding_model_path=data['context']['embedding_model_path'],
                vector_db=vector_db_config,
                chunk_size=data['context']['chunk_size'],
                chunk_overlap=data['context']['chunk_overlap'],
                file_patterns=data['context']['file_patterns'],
                exclude_patterns=data['context']['exclude_patterns']
            )

            # Tool configs
            web_search_config = WebSearchConfig(**data['tools']['web_search'])
            terminal_config = TerminalConfig(**data['tools']['terminal'])
            filesystem_config = FilesystemConfig(**data['tools']['filesystem'])
            tool_config = ToolConfig(
                web_search=web_search_config,
                terminal=terminal_config,
                filesystem=filesystem_config
            )

            performance_config = PerformanceConfig(**data['performance'])

            return cls(
                llm=llm_config,
                agent=agent_config,
                context=context_config,
                tools=tool_config,
                performance=performance_config
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
        - AGENT_CONTEXT_EMBEDDING_MODEL_PATH overrides context.embedding_model_path

        Args:
            data: Configuration dictionary

        Returns:
            Configuration with environment overrides applied
        """
        # LLM overrides
        if 'AGENT_LLM_BASE_URL' in os.environ:
            data['llm']['base_url'] = os.environ['AGENT_LLM_BASE_URL']
        if 'AGENT_LLM_MODEL' in os.environ:
            data['llm']['model'] = os.environ['AGENT_LLM_MODEL']

        # Agent overrides
        if 'AGENT_HOST' in os.environ:
            data['agent']['host'] = os.environ['AGENT_HOST']
        if 'AGENT_PORT' in os.environ:
            data['agent']['port'] = int(os.environ['AGENT_PORT'])

        # Context overrides
        if 'AGENT_CONTEXT_EMBEDDING_MODEL_PATH' in os.environ:
            data['context']['embedding_model_path'] = os.environ['AGENT_CONTEXT_EMBEDDING_MODEL_PATH']

        return data
