"""LLM client for OpenAI-compatible API."""
import requests
from typing import List, Dict, Optional, Iterator
import logging

logger = logging.getLogger(__name__)


class LLMClient:
    """Client for communicating with OpenAI-compatible LLM server."""

    def __init__(self, base_url: str, model: str, max_tokens: int = 2048):
        """Initialize LLM client.

        Args:
            base_url: Base URL of the LLM server (e.g., http://localhost:8001/v1)
            model: Model name to use
            max_tokens: Maximum tokens to generate
        """
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = 120  # 2 minutes timeout for completions

    def complete(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
        stop: Optional[List[str]] = None
    ) -> str:
        """Generate completion from messages.

        Args:
            messages: List of message dicts with 'role' and 'content'
            temperature: Sampling temperature (0.0 to 1.0)
            max_tokens: Maximum tokens to generate (overrides default)
            stop: List of stop sequences

        Returns:
            Generated completion text

        Raises:
            ConnectionError: If LLM server is unreachable
            TimeoutError: If request times out
            ValueError: If response is invalid
        """
        url = f"{self.base_url}/chat/completions"

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens or self.max_tokens,
            "stream": False
        }

        if stop:
            payload["stop"] = stop

        try:
            response = requests.post(
                url,
                json=payload,
                timeout=self.timeout
            )
            response.raise_for_status()

            data = response.json()

            if "choices" not in data or len(data["choices"]) == 0:
                raise ValueError("Invalid response from LLM server: no choices")

            return data["choices"][0]["message"]["content"]

        except requests.exceptions.ConnectionError as e:
            logger.error(f"Failed to connect to LLM server at {url}: {e}")
            raise ConnectionError(f"LLM server unreachable at {url}") from e

        except requests.exceptions.Timeout as e:
            logger.error(f"Request to LLM server timed out after {self.timeout}s")
            raise TimeoutError(f"LLM request timed out after {self.timeout}s") from e

        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error from LLM server: {e}")
            raise ValueError(f"LLM server returned error: {e}") from e

    def stream_complete(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: Optional[int] = None
    ) -> Iterator[str]:
        """Stream completion tokens from messages.

        Args:
            messages: List of message dicts with 'role' and 'content'
            temperature: Sampling temperature (0.0 to 1.0)
            max_tokens: Maximum tokens to generate (overrides default)

        Yields:
            Generated completion tokens

        Raises:
            ConnectionError: If LLM server is unreachable
            TimeoutError: If request times out
        """
        url = f"{self.base_url}/chat/completions"

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens or self.max_tokens,
            "stream": True
        }

        try:
            response = requests.post(
                url,
                json=payload,
                timeout=self.timeout,
                stream=True
            )
            response.raise_for_status()

            for line in response.iter_lines():
                if line:
                    line_str = line.decode('utf-8')
                    if line_str.startswith('data: '):
                        data_str = line_str[6:]  # Remove 'data: ' prefix
                        if data_str == '[DONE]':
                            break
                        try:
                            import json
                            data = json.loads(data_str)
                            if "choices" in data and len(data["choices"]) > 0:
                                delta = data["choices"][0].get("delta", {})
                                if "content" in delta and delta["content"] is not None:
                                    yield delta["content"]
                        except json.JSONDecodeError:
                            continue

        except requests.exceptions.ConnectionError as e:
            logger.error(f"Failed to connect to LLM server at {url}: {e}")
            raise ConnectionError(f"LLM server unreachable at {url}") from e

        except requests.exceptions.Timeout as e:
            logger.error(f"Request to LLM server timed out after {self.timeout}s")
            raise TimeoutError(f"LLM request timed out after {self.timeout}s") from e
