"""
Remote filesystem tools that proxy file operations through the VSCode extension.

When the agent server runs on a different machine from the user's workspace,
this module calls back to a lightweight HTTP file server running inside the
VSCode extension to read, list, search, and write files on the client machine.
"""

import logging
import time
from typing import List, Optional

import requests

logger = logging.getLogger(__name__)

# Timeout for proxy calls (seconds): (connect_timeout, read_timeout)
PROXY_CONNECT_TIMEOUT = 10
PROXY_READ_TIMEOUT = 30

# Retry configuration
MAX_RETRIES = 2
RETRY_BACKOFF = 1.5  # seconds between retries (multiplied each attempt)


class ProxyUnavailableError(RuntimeError):
    """Raised when the VSCode file proxy is unreachable after retries."""
    pass


class RemoteFilesystemTools:
    """
    Filesystem tools that delegate to the VSCode extension's file proxy.

    Implements the same interface as FilesystemTools so it can be used
    as a drop-in replacement in the ToolSystem.
    """

    def __init__(self, proxy_url: str, config: Optional[dict] = None):
        self.proxy_url = proxy_url.rstrip('/')
        self.config = config or {}

    def _request(self, endpoint: str, payload: dict) -> dict:
        """
        Make a POST request to the proxy with retry logic.

        Retries on connection errors and timeouts. Returns the parsed
        JSON response on success.

        Raises:
            ProxyUnavailableError: If the proxy is unreachable after all retries.
            RuntimeError: If the proxy returns a non-200 status.
        """
        url = f"{self.proxy_url}/{endpoint}"
        last_error: Optional[Exception] = None

        for attempt in range(1, MAX_RETRIES + 2):  # +2 because range is exclusive and attempt 1 is the initial try
            try:
                resp = requests.post(
                    url,
                    json=payload,
                    timeout=(PROXY_CONNECT_TIMEOUT, PROXY_READ_TIMEOUT),
                )
                return {"status_code": resp.status_code, "body": resp.json()}
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_error = exc
                if attempt <= MAX_RETRIES:
                    wait = RETRY_BACKOFF * attempt
                    logger.warning(
                        "Proxy request to %s failed (attempt %d/%d): %s — retrying in %.1fs",
                        endpoint, attempt, MAX_RETRIES + 1, exc, wait,
                    )
                    time.sleep(wait)

        # All retries exhausted
        raise ProxyUnavailableError(
            f"VSCode file proxy is unreachable at {self.proxy_url}. "
            f"Ensure the VSCode extension is running and the file proxy server "
            f"is started. Last error: {last_error}"
        )

    def check_connectivity(self) -> bool:
        """
        Quick connectivity check to the file proxy.

        Returns True if the proxy responds, False otherwise.
        """
        try:
            requests.post(
                f"{self.proxy_url}/list_directory",
                json={"path": "."},
                timeout=(5, 10),
            )
            return True
        except (requests.ConnectionError, requests.Timeout):
            return False

    def read_file(self, path: str) -> str:
        """Read file contents via the proxy."""
        result = self._request("read_file", {"path": path})
        if result["status_code"] != 200:
            raise FileNotFoundError(
                result["body"].get("error", f"Failed to read {path}")
            )
        return result["body"]["content"]

    def list_directory(self, path: str = ".") -> List[str]:
        """List directory contents via the proxy."""
        result = self._request("list_directory", {"path": path})
        if result["status_code"] != 200:
            raise FileNotFoundError(
                result["body"].get("error", f"Failed to list {path}")
            )
        return result["body"]["entries"]

    def search_files(self, query: str) -> List[str]:
        """Search for files matching a glob pattern via the proxy."""
        result = self._request("search_files", {"query": query})
        if result["status_code"] != 200:
            raise RuntimeError(
                result["body"].get("error", f"Search failed for {query}")
            )
        return result["body"]["files"]

    def write_file(self, path: str, contents: str) -> None:
        """Write file contents via the proxy."""
        result = self._request("write_file", {"path": path, "contents": contents})
        if result["status_code"] != 200:
            raise RuntimeError(
                result["body"].get("error", f"Failed to write {path}")
            )

    def create_file(self, path: str) -> None:
        """Create an empty file via the proxy."""
        self.write_file(path, "")
