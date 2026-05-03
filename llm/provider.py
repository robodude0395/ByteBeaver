"""Model provider abstraction layer.

Separates the transport/API layer from model-specific prompt formatting.
This allows swapping between different LLM backends (llama.cpp, Anthropic,
OpenAI, Ollama, etc.) without touching the agent loop.

Each provider handles:
- API communication (HTTP, SDK, etc.)
- Message formatting (chat templates, stop tokens)
- Streaming protocol differences
- Model-specific quirks (token counting, context limits)

Usage:
    provider = create_provider(config)
    response = provider.complete(messages, temperature=0.2)
    for token in provider.stream_complete(messages):
        print(token, end="")
"""

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional

import requests

logger = logging.getLogger(__name__)


@dataclass
class ModelInfo:
    """Metadata about the model being used."""
    name: str
    provider: str
    context_window: int
    max_output_tokens: int
    supports_streaming: bool = True
    supports_system_role: bool = True
    stop_tokens: List[str] = field(default_factory=list)


class ModelProvider(ABC):
    """Abstract base class for LLM providers.

    All providers must implement complete() and stream_complete().
    """

    @abstractmethod
    def complete(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
        stop: Optional[List[str]] = None,
    ) -> str:
        """Generate a completion from messages.

        Args:
            messages: List of {"role": "...", "content": "..."} dicts.
            temperature: Sampling temperature.
            max_tokens: Max tokens to generate.
            stop: Stop sequences.

        Returns:
            Generated text.
        """
        ...

    @abstractmethod
    def stream_complete(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
    ) -> Iterator[str]:
        """Stream completion tokens.

        Args:
            messages: List of {"role": "...", "content": "..."} dicts.
            temperature: Sampling temperature.
            max_tokens: Max tokens to generate.

        Yields:
            Token strings.
        """
        ...

    @abstractmethod
    def get_model_info(self) -> ModelInfo:
        """Return metadata about the current model."""
        ...


class OpenAICompatibleProvider(ModelProvider):
    """Provider for OpenAI-compatible APIs (llama.cpp, vLLM, Ollama, etc.).

    This is the default provider that works with any server exposing
    the /v1/chat/completions endpoint.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        max_tokens: int = 2048,
        context_window: int = 8192,
        timeout: int = 300,
        api_key: Optional[str] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_tokens = max_tokens
        self.context_window = context_window
        self.timeout = timeout
        self.api_key = api_key

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def complete(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
        stop: Optional[List[str]] = None,
    ) -> str:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens or self.max_tokens,
            "stream": False,
        }
        if stop:
            payload["stop"] = stop

        try:
            response = requests.post(
                url, json=payload, headers=self._headers(), timeout=self.timeout
            )
            response.raise_for_status()
            data = response.json()

            if "choices" not in data or len(data["choices"]) == 0:
                raise ValueError("Invalid response: no choices")

            return data["choices"][0]["message"]["content"]

        except requests.exceptions.ConnectionError as e:
            logger.error("Failed to connect to LLM at %s: %s", url, e)
            raise ConnectionError(f"LLM server unreachable at {url}") from e
        except requests.exceptions.Timeout as e:
            logger.error("LLM request timed out after %ds", self.timeout)
            raise TimeoutError(f"LLM request timed out after {self.timeout}s") from e
        except requests.exceptions.HTTPError as e:
            logger.error("HTTP error from LLM: %s", e)
            raise ValueError(f"LLM server error: {e}") from e

    def stream_complete(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
    ) -> Iterator[str]:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens or self.max_tokens,
            "stream": True,
        }

        try:
            response = requests.post(
                url,
                json=payload,
                headers=self._headers(),
                timeout=self.timeout,
                stream=True,
            )
            response.raise_for_status()

            for line in response.iter_lines():
                if line:
                    line_str = line.decode("utf-8")
                    if line_str.startswith("data: "):
                        data_str = line_str[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                            if "choices" in data and len(data["choices"]) > 0:
                                delta = data["choices"][0].get("delta", {})
                                content = delta.get("content")
                                if content is not None:
                                    yield content
                        except json.JSONDecodeError:
                            continue

        except requests.exceptions.ConnectionError as e:
            logger.error("Failed to connect to LLM at %s: %s", url, e)
            raise ConnectionError(f"LLM server unreachable at {url}") from e
        except requests.exceptions.Timeout as e:
            logger.error("LLM request timed out after %ds", self.timeout)
            raise TimeoutError(f"LLM request timed out after {self.timeout}s") from e

    def get_model_info(self) -> ModelInfo:
        return ModelInfo(
            name=self.model,
            provider="openai_compatible",
            context_window=self.context_window,
            max_output_tokens=self.max_tokens,
        )


class AnthropicProvider(ModelProvider):
    """Provider for Anthropic's Claude API.

    Handles the differences in Anthropic's message format:
    - System prompt is a top-level parameter, not a message
    - Different streaming protocol (SSE with different event types)
    - Different error format
    """

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 4096,
        context_window: int = 200000,
        base_url: str = "https://api.anthropic.com",
        timeout: int = 120,
    ):
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.context_window = context_window
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }

    def _extract_system_and_messages(
        self, messages: List[Dict[str, str]]
    ) -> tuple:
        """Separate system prompt from conversation messages.

        Anthropic expects system as a top-level param, not in messages.
        """
        system = ""
        conversation = []
        for msg in messages:
            if msg["role"] == "system":
                system += msg["content"] + "\n"
            else:
                conversation.append(msg)
        return system.strip(), conversation

    def complete(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
        stop: Optional[List[str]] = None,
    ) -> str:
        system, conversation = self._extract_system_and_messages(messages)
        url = f"{self.base_url}/v1/messages"

        payload = {
            "model": self.model,
            "max_tokens": max_tokens or self.max_tokens,
            "temperature": temperature,
            "messages": conversation,
        }
        if system:
            payload["system"] = system
        if stop:
            payload["stop_sequences"] = stop

        try:
            response = requests.post(
                url, json=payload, headers=self._headers(), timeout=self.timeout
            )
            response.raise_for_status()
            data = response.json()

            # Anthropic returns content as a list of blocks
            content_blocks = data.get("content", [])
            text_parts = [
                block["text"]
                for block in content_blocks
                if block.get("type") == "text"
            ]
            return "".join(text_parts)

        except requests.exceptions.ConnectionError as e:
            raise ConnectionError(f"Anthropic API unreachable: {e}") from e
        except requests.exceptions.Timeout as e:
            raise TimeoutError(f"Anthropic request timed out: {e}") from e
        except requests.exceptions.HTTPError as e:
            raise ValueError(f"Anthropic API error: {e}") from e

    def stream_complete(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
    ) -> Iterator[str]:
        system, conversation = self._extract_system_and_messages(messages)
        url = f"{self.base_url}/v1/messages"

        payload = {
            "model": self.model,
            "max_tokens": max_tokens or self.max_tokens,
            "temperature": temperature,
            "messages": conversation,
            "stream": True,
        }
        if system:
            payload["system"] = system

        try:
            response = requests.post(
                url,
                json=payload,
                headers=self._headers(),
                timeout=self.timeout,
                stream=True,
            )
            response.raise_for_status()

            for line in response.iter_lines():
                if line:
                    line_str = line.decode("utf-8")
                    if line_str.startswith("data: "):
                        try:
                            data = json.loads(line_str[6:])
                            event_type = data.get("type", "")
                            if event_type == "content_block_delta":
                                delta = data.get("delta", {})
                                if delta.get("type") == "text_delta":
                                    yield delta.get("text", "")
                            elif event_type == "message_stop":
                                break
                        except json.JSONDecodeError:
                            continue

        except requests.exceptions.ConnectionError as e:
            raise ConnectionError(f"Anthropic API unreachable: {e}") from e
        except requests.exceptions.Timeout as e:
            raise TimeoutError(f"Anthropic request timed out: {e}") from e

    def get_model_info(self) -> ModelInfo:
        return ModelInfo(
            name=self.model,
            provider="anthropic",
            context_window=self.context_window,
            max_output_tokens=self.max_tokens,
        )


class OllamaProvider(ModelProvider):
    """Provider for Ollama's local API.

    Ollama uses a slightly different API format from OpenAI but is
    close enough that we can adapt. Useful for running models like
    Llama 3, DeepSeek Coder, CodeGemma, etc. locally.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3",
        max_tokens: int = 2048,
        context_window: int = 8192,
        timeout: int = 300,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_tokens = max_tokens
        self.context_window = context_window
        self.timeout = timeout

    def complete(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
        stop: Optional[List[str]] = None,
    ) -> str:
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens or self.max_tokens,
            },
        }
        if stop:
            payload["options"]["stop"] = stop

        try:
            response = requests.post(url, json=payload, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
            return data.get("message", {}).get("content", "")
        except requests.exceptions.ConnectionError as e:
            raise ConnectionError(f"Ollama unreachable at {url}: {e}") from e
        except requests.exceptions.Timeout as e:
            raise TimeoutError(f"Ollama request timed out: {e}") from e

    def stream_complete(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
    ) -> Iterator[str]:
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens or self.max_tokens,
            },
        }

        try:
            response = requests.post(
                url, json=payload, timeout=self.timeout, stream=True
            )
            response.raise_for_status()

            for line in response.iter_lines():
                if line:
                    try:
                        data = json.loads(line.decode("utf-8"))
                        content = data.get("message", {}).get("content", "")
                        if content:
                            yield content
                        if data.get("done", False):
                            break
                    except json.JSONDecodeError:
                        continue

        except requests.exceptions.ConnectionError as e:
            raise ConnectionError(f"Ollama unreachable at {url}: {e}") from e
        except requests.exceptions.Timeout as e:
            raise TimeoutError(f"Ollama request timed out: {e}") from e

    def get_model_info(self) -> ModelInfo:
        return ModelInfo(
            name=self.model,
            provider="ollama",
            context_window=self.context_window,
            max_output_tokens=self.max_tokens,
        )


# ---------------------------------------------------------------------------
# Provider factory
# ---------------------------------------------------------------------------

# Maps provider type strings to classes
PROVIDER_REGISTRY: Dict[str, type] = {
    "openai_compatible": OpenAICompatibleProvider,
    "llamacpp": OpenAICompatibleProvider,  # llama.cpp uses OpenAI-compat API
    "vllm": OpenAICompatibleProvider,      # vLLM uses OpenAI-compat API
    "anthropic": AnthropicProvider,
    "ollama": OllamaProvider,
}


def create_provider(
    provider_type: str = "openai_compatible",
    **kwargs,
) -> ModelProvider:
    """Create a model provider from configuration.

    Args:
        provider_type: One of the registered provider types.
        **kwargs: Provider-specific configuration.

    Returns:
        Configured ModelProvider instance.

    Raises:
        ValueError: If provider_type is not recognized.
    """
    cls = PROVIDER_REGISTRY.get(provider_type)
    if cls is None:
        available = ", ".join(sorted(PROVIDER_REGISTRY.keys()))
        raise ValueError(
            f"Unknown provider type: {provider_type}. "
            f"Available: {available}"
        )
    return cls(**kwargs)
