"""
Remote filesystem tools that proxy file operations through the VSCode extension.

When the agent server runs on a different machine from the user's workspace,
this module calls back to a lightweight HTTP file server running inside the
VSCode extension to read, list, search, and write files on the client machine.
"""

import logging
from typing import List, Optional

import requests

logger = logging.getLogger(__name__)

# Timeout for proxy calls (seconds)
PROXY_TIMEOUT = 15


class RemoteFilesystemTools:
    """
    Filesystem tools that delegate to the VSCode extension's file proxy.

    Implements the same interface as FilesystemTools so it can be used
    as a drop-in replacement in the ToolSystem.
    """

    def __init__(self, proxy_url: str, config: Optional[dict] = None):
        self.proxy_url = proxy_url.rstrip('/')
        self.config = config or {}

    def read_file(self, path: str) -> str:
        """Read file contents via the proxy."""
        resp = requests.post(
            f"{self.proxy_url}/read_file",
            json={"path": path},
            timeout=PROXY_TIMEOUT,
        )
        data = resp.json()
        if resp.status_code != 200:
            raise FileNotFoundError(data.get("error", f"Failed to read {path}"))
        return data["content"]

    def list_directory(self, path: str = ".") -> List[str]:
        """List directory contents via the proxy."""
        resp = requests.post(
            f"{self.proxy_url}/list_directory",
            json={"path": path},
            timeout=PROXY_TIMEOUT,
        )
        data = resp.json()
        if resp.status_code != 200:
            raise FileNotFoundError(data.get("error", f"Failed to list {path}"))
        return data["entries"]

    def search_files(self, query: str) -> List[str]:
        """Search for files matching a glob pattern via the proxy."""
        resp = requests.post(
            f"{self.proxy_url}/search_files",
            json={"query": query},
            timeout=PROXY_TIMEOUT,
        )
        data = resp.json()
        if resp.status_code != 200:
            raise RuntimeError(data.get("error", f"Search failed for {query}"))
        return data["files"]

    def write_file(self, path: str, contents: str) -> None:
        """Write file contents via the proxy."""
        resp = requests.post(
            f"{self.proxy_url}/write_file",
            json={"path": path, "contents": contents},
            timeout=PROXY_TIMEOUT,
        )
        if resp.status_code != 200:
            data = resp.json()
            raise RuntimeError(data.get("error", f"Failed to write {path}"))

    def create_file(self, path: str) -> None:
        """Create an empty file via the proxy."""
        self.write_file(path, "")
