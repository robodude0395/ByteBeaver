"""
Embedding cache for avoiding recomputation of embeddings.

This module provides caching functionality to store embeddings with file hashes,
allowing the system to skip embedding generation for unchanged files during
re-indexing operations.
"""

from typing import Optional, Dict, Tuple
import hashlib
import logging
import pickle
import os
from pathlib import Path
import numpy as np

logger = logging.getLogger(__name__)


class EmbeddingCache:
    """
    Cache for storing embeddings with file content hashes.

    The cache uses file content hash (SHA256) as the key to determine if
    a file has changed. If the hash matches, the cached embedding is returned
    instead of recomputing it.

    Cache structure: file_path -> (content_hash, embedding)
    """

    def __init__(self, cache_dir: Optional[str] = None):
        """
        Initialize the embedding cache.

        Args:
            cache_dir: Optional directory path for cache persistence.
                      If provided, cache will be loaded from and saved to disk.
                      If None, cache is memory-only.
        """
        self.cache: Dict[str, Tuple[str, np.ndarray]] = {}
        self.cache_dir = cache_dir
        self.cache_file = None

        if cache_dir:
            # Create cache directory if it doesn't exist
            Path(cache_dir).mkdir(parents=True, exist_ok=True)
            self.cache_file = os.path.join(cache_dir, "embedding_cache.pkl")
            self._load_from_disk()
            logger.info(f"Initialized embedding cache with disk persistence: {self.cache_file}")
        else:
            logger.info("Initialized in-memory embedding cache")

    def get_or_compute(
        self,
        file_path: str,
        content: str,
        compute_fn: callable
    ) -> np.ndarray:
        """
        Get cached embedding or compute new one if cache miss.

        This method checks if the file content has changed by comparing
        the SHA256 hash. If the hash matches the cached version, the
        cached embedding is returned. Otherwise, the compute_fn is called
        to generate a new embedding.

        Args:
            file_path: Path to the file (used as cache key)
            content: File content to hash and potentially embed
            compute_fn: Function to call if cache miss. Should accept
                       content string and return numpy array embedding.

        Returns:
            numpy array embedding (either from cache or newly computed)

        Example:
            >>> cache = EmbeddingCache()
            >>> embedding = cache.get_or_compute(
            ...     "src/main.py",
            ...     file_content,
            ...     lambda c: model.encode([c])[0]
            ... )
        """
        # Compute content hash
        content_hash = self._compute_hash(content)

        # Check cache
        if file_path in self.cache:
            cached_hash, cached_embedding = self.cache[file_path]
            if cached_hash == content_hash:
                logger.debug(f"Cache hit for {file_path}")
                return cached_embedding
            else:
                logger.debug(f"Cache miss for {file_path} (content changed)")
        else:
            logger.debug(f"Cache miss for {file_path} (new file)")

        # Compute new embedding
        embedding = compute_fn(content)

        # Ensure embedding is numpy array
        if not isinstance(embedding, np.ndarray):
            embedding = np.array(embedding)

        # Store in cache
        self.cache[file_path] = (content_hash, embedding)

        return embedding

    def get(self, file_path: str, content: str) -> Optional[np.ndarray]:
        """
        Get cached embedding if it exists and content hash matches.

        Args:
            file_path: Path to the file
            content: File content to verify hash

        Returns:
            Cached embedding if found and hash matches, None otherwise
        """
        content_hash = self._compute_hash(content)

        if file_path in self.cache:
            cached_hash, cached_embedding = self.cache[file_path]
            if cached_hash == content_hash:
                return cached_embedding

        return None

    def put(self, file_path: str, content: str, embedding: np.ndarray) -> None:
        """
        Store embedding in cache with content hash.

        Args:
            file_path: Path to the file
            content: File content to hash
            embedding: Embedding vector to cache
        """
        content_hash = self._compute_hash(content)

        # Ensure embedding is numpy array
        if not isinstance(embedding, np.ndarray):
            embedding = np.array(embedding)

        self.cache[file_path] = (content_hash, embedding)
        logger.debug(f"Cached embedding for {file_path}")

    def invalidate(self, file_path: str) -> None:
        """
        Remove a file from the cache.

        Args:
            file_path: Path to the file to invalidate
        """
        if file_path in self.cache:
            del self.cache[file_path]
            logger.debug(f"Invalidated cache for {file_path}")

    def clear(self) -> None:
        """Clear all cached embeddings."""
        self.cache.clear()
        logger.info("Cleared embedding cache")

    def size(self) -> int:
        """
        Get the number of cached embeddings.

        Returns:
            Number of files in cache
        """
        return len(self.cache)

    def save_to_disk(self) -> None:
        """
        Save cache to disk if cache_dir was provided.

        The cache is serialized using pickle format.
        """
        if not self.cache_file:
            logger.warning("Cannot save cache: no cache_dir provided")
            return

        try:
            with open(self.cache_file, 'wb') as f:
                pickle.dump(self.cache, f)
            logger.info(f"Saved cache to disk: {self.cache_file} ({len(self.cache)} entries)")
        except Exception as e:
            logger.error(f"Failed to save cache to disk: {e}")

    def _load_from_disk(self) -> None:
        """Load cache from disk if cache file exists."""
        if not self.cache_file or not os.path.exists(self.cache_file):
            logger.debug("No cache file found, starting with empty cache")
            return

        try:
            with open(self.cache_file, 'rb') as f:
                self.cache = pickle.load(f)
            logger.info(f"Loaded cache from disk: {self.cache_file} ({len(self.cache)} entries)")
        except Exception as e:
            logger.error(f"Failed to load cache from disk: {e}")
            self.cache = {}

    def _compute_hash(self, content: str) -> str:
        """
        Compute SHA256 hash of content.

        Args:
            content: String content to hash

        Returns:
            Hexadecimal hash string
        """
        return hashlib.sha256(content.encode('utf-8')).hexdigest()

    def get_stats(self) -> Dict[str, int]:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache statistics:
            - size: Number of cached files
            - total_embeddings: Total number of embeddings stored
        """
        return {
            "size": len(self.cache),
            "total_embeddings": len(self.cache)
        }

    def __len__(self) -> int:
        """Return number of cached files."""
        return len(self.cache)

    def __contains__(self, file_path: str) -> bool:
        """Check if file_path is in cache."""
        return file_path in self.cache

    def __repr__(self) -> str:
        """String representation of cache."""
        cache_type = "disk-backed" if self.cache_dir else "in-memory"
        return f"EmbeddingCache({cache_type}, {len(self.cache)} entries)"
