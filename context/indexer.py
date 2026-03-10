"""
Repository indexing and semantic search engine.

This module provides the ContextEngine class for indexing workspace files,
generating embeddings, and performing semantic search.
"""

from typing import List, Dict, Any, Optional
import os
import glob
import logging
from dataclasses import dataclass

from context.embeddings import EmbeddingModel
from context.vector_db import VectorDB
from context.chunker import chunk_file, FileChunk

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """Represents a search result with file location and similarity score."""
    file_path: str
    line_start: int
    line_end: int
    content: str
    similarity_score: float


class ContextEngine:
    """
    Repository indexing and semantic search engine.

    This class handles:
    - Discovering and filtering files in a workspace
    - Chunking files into token-sized segments
    - Generating embeddings for chunks
    - Storing embeddings in a vector database
    - Performing semantic search for relevant code
    """

    def __init__(
        self,
        embedding_model_path: str,
        vector_db_config: Dict[str, Any]
    ):
        """
        Initialize the ContextEngine.

        Args:
            embedding_model_path: Path to the embedding model (local or HuggingFace ID)
            vector_db_config: Configuration dictionary for vector database with keys:
                - host: Qdrant server host (optional if in_memory=True)
                - port: Qdrant server port (optional if in_memory=True)
                - in_memory: If True, use in-memory mode
                - collection_prefix: Prefix for collection names
        """
        logger.info("Initializing ContextEngine")

        # Initialize embedding model
        self.embedding_model = EmbeddingModel(model_path=embedding_model_path)
        logger.info(f"Loaded embedding model with vector size: {self.embedding_model.get_vector_size()}")

        # Initialize vector database
        self.vector_db = VectorDB(
            host=vector_db_config.get("host", "localhost"),
            port=vector_db_config.get("port", 6333),
            in_memory=vector_db_config.get("in_memory", True)
        )

        self.collection_prefix = vector_db_config.get("collection_prefix", "workspace")
        logger.info("ContextEngine initialized successfully")

    def index_workspace(
        self,
        workspace_path: str,
        file_patterns: Optional[List[str]] = None,
        exclude_patterns: Optional[List[str]] = None,
        max_file_size: int = 1_000_000,  # 1MB default
        batch_size: int = 32
    ) -> None:
        """
        Index all files in the workspace.

        This method:
        1. Discovers files matching patterns
        2. Filters out large files and excluded patterns
        3. Chunks each file into token-sized segments
        4. Generates embeddings in batches
        5. Stores embeddings with metadata in vector database

        Args:
            workspace_path: Root directory of the workspace
            file_patterns: List of glob patterns for files to include
                          (default: common code file extensions)
            exclude_patterns: List of glob patterns for files/dirs to exclude
                            (default: node_modules, venv, .git, etc.)
            max_file_size: Maximum file size in bytes (default: 1MB)
            batch_size: Batch size for embedding generation (default: 32)

        Raises:
            ValueError: If workspace_path doesn't exist
        """
        if not os.path.exists(workspace_path):
            raise ValueError(f"Workspace path does not exist: {workspace_path}")

        logger.info(f"Starting workspace indexing: {workspace_path}")

        # Default file patterns if not provided
        if file_patterns is None:
            file_patterns = [
                "**/*.py", "**/*.js", "**/*.ts", "**/*.tsx", "**/*.jsx",
                "**/*.java", "**/*.cpp", "**/*.c", "**/*.h",
                "**/*.go", "**/*.rs", "**/*.md"
            ]

        # Default exclude patterns if not provided
        if exclude_patterns is None:
            exclude_patterns = [
                "**/node_modules/**", "**/venv/**", "**/.venv/**",
                "**/.git/**", "**/dist/**", "**/build/**",
                "**/__pycache__/**", "**/.pytest_cache/**"
            ]

        # Step 1: Discover files
        logger.info("Discovering files...")
        files = self._discover_files(workspace_path, file_patterns, exclude_patterns)
        logger.info(f"Found {len(files)} files matching patterns")

        # Step 2: Filter by file size
        logger.info(f"Filtering files by size (max: {max_file_size} bytes)...")
        filtered_files = self._filter_by_size(files, max_file_size)
        logger.info(f"Retained {len(filtered_files)} files after size filtering")

        if not filtered_files:
            logger.warning("No files to index after filtering")
            return

        # Step 3: Chunk files
        logger.info("Chunking files...")
        all_chunks = []
        for file_path in filtered_files:
            try:
                chunks = self._chunk_file_from_path(file_path)
                all_chunks.extend(chunks)
            except Exception as e:
                logger.warning(f"Failed to chunk file {file_path}: {e}")
                continue

        logger.info(f"Generated {len(all_chunks)} chunks from {len(filtered_files)} files")

        if not all_chunks:
            logger.warning("No chunks generated from files")
            return

        # Step 4: Generate embeddings in batches
        logger.info(f"Generating embeddings in batches of {batch_size}...")
        self._generate_embeddings_batch(all_chunks, batch_size)

        # Step 5: Store in vector database
        logger.info("Storing embeddings in vector database...")
        self._store_chunks(all_chunks, workspace_path)

        logger.info(
            f"Indexing complete: {len(filtered_files)} files, "
            f"{len(all_chunks)} chunks indexed"
        )

    def _discover_files(
        self,
        workspace_path: str,
        file_patterns: List[str],
        exclude_patterns: List[str]
    ) -> List[str]:
        """
        Discover files matching patterns in workspace.

        Args:
            workspace_path: Root directory to search
            file_patterns: List of glob patterns to include
            exclude_patterns: List of glob patterns to exclude

        Returns:
            List of absolute file paths
        """
        discovered_files = set()

        # Find all files matching include patterns
        for pattern in file_patterns:
            full_pattern = os.path.join(workspace_path, pattern)
            matches = glob.glob(full_pattern, recursive=True)
            # Only include actual files, not directories
            discovered_files.update(f for f in matches if os.path.isfile(f))

        # Filter out excluded patterns
        filtered_files = []
        for file_path in discovered_files:
            # Get relative path for pattern matching
            rel_path = os.path.relpath(file_path, workspace_path)

            # Check if file matches any exclude pattern
            excluded = False
            for exclude_pattern in exclude_patterns:
                # Remove leading ** for matching
                pattern = exclude_pattern.replace("**/", "")
                if pattern.endswith("/**"):
                    # Directory exclusion
                    dir_pattern = pattern[:-3]
                    if dir_pattern in rel_path.split(os.sep):
                        excluded = True
                        break
                else:
                    # File pattern exclusion
                    if glob.fnmatch.fnmatch(rel_path, pattern):
                        excluded = True
                        break

            if not excluded:
                filtered_files.append(file_path)

        return filtered_files

    def _filter_by_size(
        self,
        files: List[str],
        max_size: int
    ) -> List[str]:
        """
        Filter files by maximum size.

        Args:
            files: List of file paths
            max_size: Maximum file size in bytes

        Returns:
            List of file paths that are within size limit
        """
        filtered = []
        for file_path in files:
            try:
                size = os.path.getsize(file_path)
                if size <= max_size:
                    filtered.append(file_path)
                else:
                    logger.debug(f"Skipping large file: {file_path} ({size} bytes)")
            except OSError as e:
                logger.warning(f"Could not get size of {file_path}: {e}")
                continue

        return filtered

    def _chunk_file_from_path(self, file_path: str) -> List[FileChunk]:
        """
        Read and chunk a file.

        Args:
            file_path: Path to the file

        Returns:
            List of FileChunk objects

        Raises:
            Exception: If file cannot be read
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except UnicodeDecodeError:
            # Try with latin-1 encoding for binary-like files
            try:
                with open(file_path, 'r', encoding='latin-1') as f:
                    content = f.read()
            except Exception as e:
                raise Exception(f"Failed to read file with any encoding: {e}")

        return chunk_file(file_path, content)

    def _generate_embeddings_batch(
        self,
        chunks: List[FileChunk],
        batch_size: int
    ) -> None:
        """
        Generate embeddings for chunks in batches.

        Args:
            chunks: List of FileChunk objects (modified in place)
            batch_size: Number of chunks to process per batch
        """
        total_batches = (len(chunks) + batch_size - 1) // batch_size

        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            batch_num = i // batch_size + 1

            logger.debug(f"Processing batch {batch_num}/{total_batches}")

            # Extract content from chunks
            texts = [chunk.content for chunk in batch]

            # Generate embeddings
            embeddings = self.embedding_model.encode(
                texts=texts,
                batch_size=batch_size,
                normalize=True,
                show_progress=False
            )

            # Assign embeddings to chunks
            for j, chunk in enumerate(batch):
                chunk.embedding = embeddings[j].tolist()

    def _store_chunks(
        self,
        chunks: List[FileChunk],
        workspace_path: str
    ) -> None:
        """
        Store chunks with embeddings in vector database.

        Args:
            chunks: List of FileChunk objects with embeddings
            workspace_path: Root workspace path for collection naming
        """
        # Create collection name from workspace path
        workspace_name = os.path.basename(os.path.abspath(workspace_path))
        collection_name = f"{self.collection_prefix}_{workspace_name}"

        # Create collection if it doesn't exist
        if not self.vector_db.collection_exists(collection_name):
            vector_size = self.embedding_model.get_vector_size()
            self.vector_db.create_collection(
                collection_name=collection_name,
                vector_size=vector_size,
                distance="Cosine",
                recreate=False
            )

        # Prepare data for storage
        embeddings = [chunk.embedding for chunk in chunks]
        metadata = [
            {
                "file_path": chunk.file_path,
                "line_start": chunk.line_start,
                "line_end": chunk.line_end,
                "content": chunk.content,
                "chunk_id": chunk.chunk_id
            }
            for chunk in chunks
        ]
        ids = [chunk.chunk_id for chunk in chunks]

        # Store in vector database
        self.vector_db.store_embeddings(
            collection_name=collection_name,
            embeddings=embeddings,
            metadata=metadata,
            ids=ids
        )

        logger.info(f"Stored {len(chunks)} chunks in collection {collection_name}")

    def search(
        self,
        query: str,
        workspace_path: str,
        top_k: int = 10,
        min_score: float = 0.7
    ) -> List[SearchResult]:
        """
        Perform semantic search for relevant code chunks.

        Args:
            query: Search query string
            workspace_path: Root workspace path (for collection naming)
            top_k: Maximum number of results to return (default: 10)
            min_score: Minimum similarity score threshold (default: 0.7)

        Returns:
            List of SearchResult objects with file_path, line_start, line_end,
            content, and similarity_score. Results are de-duplicated by file
            (keeping highest scoring chunk per file) and limited to max 10 results.

        Raises:
            ValueError: If collection doesn't exist (workspace not indexed)
        """
        logger.info(f"Searching for: {query}")

        # Generate query embedding
        query_embedding = self.embedding_model.encode(
            texts=[query],
            batch_size=1,
            normalize=True,
            show_progress=False
        )[0].tolist()

        # Get collection name
        workspace_name = os.path.basename(os.path.abspath(workspace_path))
        collection_name = f"{self.collection_prefix}_{workspace_name}"

        # Check if collection exists
        if not self.vector_db.collection_exists(collection_name):
            raise ValueError(
                f"Workspace not indexed: {workspace_path}. "
                f"Call index_workspace() first."
            )

        # Search vector database
        search_results = self.vector_db.search(
            collection_name=collection_name,
            query_vector=query_embedding,
            limit=top_k * 2,  # Get more results for de-duplication
            score_threshold=min_score
        )

        # Convert to SearchResult objects
        results = []
        for hit in search_results:
            results.append(SearchResult(
                file_path=hit["payload"]["file_path"],
                line_start=hit["payload"]["line_start"],
                line_end=hit["payload"]["line_end"],
                content=hit["payload"]["content"],
                similarity_score=hit["score"]
            ))

        # De-duplicate by file (keep highest scoring chunk per file)
        file_best_results = {}
        for result in results:
            if result.file_path not in file_best_results:
                file_best_results[result.file_path] = result
            elif result.similarity_score > file_best_results[result.file_path].similarity_score:
                file_best_results[result.file_path] = result

        # Get de-duplicated results and sort by score
        deduplicated_results = sorted(
            file_best_results.values(),
            key=lambda r: r.similarity_score,
            reverse=True
        )

        # Limit to top_k results (max 10)
        final_results = deduplicated_results[:min(top_k, 10)]

        logger.info(
            f"Found {len(final_results)} results "
            f"(from {len(results)} total matches)"
        )

        return final_results

    def get_file_tree(
        self,
        workspace_path: str,
        exclude_patterns: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Build hierarchical file tree structure for workspace.

        Args:
            workspace_path: Root directory of the workspace
            exclude_patterns: List of glob patterns for files/dirs to exclude
                            (default: node_modules, venv, .git, etc.)

        Returns:
            Hierarchical dictionary representation of file tree with structure:
            {
                "name": "workspace_name",
                "type": "directory",
                "children": [
                    {"name": "file.py", "type": "file"},
                    {
                        "name": "subdir",
                        "type": "directory",
                        "children": [...]
                    }
                ]
            }

        Raises:
            ValueError: If workspace_path doesn't exist
        """
        if not os.path.exists(workspace_path):
            raise ValueError(f"Workspace path does not exist: {workspace_path}")

        logger.info(f"Building file tree for: {workspace_path}")

        # Default exclude patterns if not provided
        if exclude_patterns is None:
            exclude_patterns = [
                "**/node_modules/**", "**/venv/**", "**/.venv/**",
                "**/.git/**", "**/dist/**", "**/build/**",
                "**/__pycache__/**", "**/.pytest_cache/**"
            ]

        def should_exclude(path: str, base_path: str) -> bool:
            """Check if path should be excluded based on patterns."""
            # Exclude hidden files/directories
            if os.path.basename(path).startswith('.'):
                return True

            # Get relative path for pattern matching
            rel_path = os.path.relpath(path, base_path)

            # Check against exclude patterns
            for exclude_pattern in exclude_patterns:
                pattern = exclude_pattern.replace("**/", "")
                if pattern.endswith("/**"):
                    # Directory exclusion
                    dir_pattern = pattern[:-3]
                    if dir_pattern in rel_path.split(os.sep):
                        return True
                else:
                    # File pattern exclusion
                    if glob.fnmatch.fnmatch(rel_path, pattern):
                        return True

            return False

        def build_tree(path: str, base_path: str) -> Dict[str, Any]:
            """Recursively build tree structure."""
            name = os.path.basename(path)

            if os.path.isfile(path):
                return {
                    "name": name,
                    "type": "file"
                }
            elif os.path.isdir(path):
                children = []
                try:
                    entries = sorted(os.listdir(path))
                    for entry in entries:
                        entry_path = os.path.join(path, entry)

                        # Skip excluded paths
                        if should_exclude(entry_path, base_path):
                            continue

                        child_tree = build_tree(entry_path, base_path)
                        if child_tree:
                            children.append(child_tree)

                except PermissionError:
                    logger.warning(f"Permission denied: {path}")
                    return None

                return {
                    "name": name,
                    "type": "directory",
                    "children": children
                }

            return None

        tree = build_tree(workspace_path, workspace_path)

        logger.info("File tree built successfully")

        return tree if tree else {"name": os.path.basename(workspace_path), "type": "directory", "children": []}

