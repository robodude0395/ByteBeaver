"""
Vector database wrapper for Qdrant.

This module provides a wrapper class for interacting with Qdrant vector database,
supporting both in-memory and persistent modes.
"""

from typing import List, Dict, Any, Optional
import logging
import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    Filter,
    SearchParams,
)

logger = logging.getLogger(__name__)


class VectorDB:
    """Wrapper class for Qdrant vector database operations."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6333,
        in_memory: bool = True,
        **kwargs
    ):
        """
        Initialize VectorDB client.

        Args:
            host: Qdrant server host (ignored if in_memory=True)
            port: Qdrant server port (ignored if in_memory=True)
            in_memory: If True, use in-memory mode for development
            **kwargs: Additional arguments for QdrantClient
        """
        if in_memory:
            self.client = QdrantClient(":memory:")
            logger.info("Initialized Qdrant in-memory mode")
        else:
            self.client = QdrantClient(host=host, port=port, **kwargs)
            logger.info(f"Connected to Qdrant at {host}:{port}")

    def create_collection(
        self,
        collection_name: str,
        vector_size: int,
        distance: str = "Cosine",
        recreate: bool = False
    ) -> None:
        """
        Create a collection for storing embeddings.

        Args:
            collection_name: Name of the collection
            vector_size: Dimension of the embedding vectors
            distance: Distance metric ("Cosine", "Euclid", or "Dot")
            recreate: If True, delete existing collection and recreate

        Raises:
            ValueError: If distance metric is invalid
        """
        # Map string distance to Qdrant Distance enum
        distance_map = {
            "Cosine": Distance.COSINE,
            "Euclid": Distance.EUCLID,
            "Dot": Distance.DOT,
        }

        if distance not in distance_map:
            raise ValueError(
                f"Invalid distance metric: {distance}. "
                f"Must be one of {list(distance_map.keys())}"
            )

        # Check if collection exists
        collections = self.client.get_collections().collections
        collection_exists = any(c.name == collection_name for c in collections)

        if collection_exists:
            if recreate:
                logger.info(f"Deleting existing collection: {collection_name}")
                self.client.delete_collection(collection_name)
            else:
                logger.info(f"Collection {collection_name} already exists")
                return

        # Create collection
        self.client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(
                size=vector_size,
                distance=distance_map[distance]
            )
        )
        logger.info(
            f"Created collection {collection_name} with vector_size={vector_size}, "
            f"distance={distance}"
        )

    def store_embeddings(
        self,
        collection_name: str,
        embeddings: List[np.ndarray],
        metadata: List[Dict[str, Any]],
        ids: Optional[List[str]] = None
    ) -> None:
        """
        Store embeddings with metadata in the collection.

        Args:
            collection_name: Name of the collection
            embeddings: List of embedding vectors
            metadata: List of metadata dictionaries (one per embedding)
            ids: Optional list of IDs for the embeddings (auto-generated if None)

        Raises:
            ValueError: If embeddings and metadata lists have different lengths
        """
        if len(embeddings) != len(metadata):
            raise ValueError(
                f"Embeddings and metadata must have same length: "
                f"{len(embeddings)} != {len(metadata)}"
            )

        # Generate IDs if not provided
        if ids is None:
            # Use integer IDs starting from current collection size
            try:
                collection_info = self.client.get_collection(collection_name)
                start_id = collection_info.points_count
            except Exception:
                start_id = 0
            ids = [start_id + i for i in range(len(embeddings))]
        else:
            # Convert string IDs to integers if they're numeric strings
            # This is needed for in-memory mode which requires UUID or int IDs
            converted_ids = []
            for id_val in ids:
                if isinstance(id_val, str) and id_val.isdigit():
                    converted_ids.append(int(id_val))
                else:
                    # For non-numeric strings, use hash to generate integer ID
                    converted_ids.append(hash(id_val) & 0x7FFFFFFF)  # Positive int
            ids = converted_ids

        # Convert numpy arrays to lists for Qdrant
        points = [
            PointStruct(
                id=point_id,
                vector=embedding.tolist() if isinstance(embedding, np.ndarray) else embedding,
                payload=meta
            )
            for point_id, embedding, meta in zip(ids, embeddings, metadata)
        ]

        # Upload points in batches
        batch_size = 100
        for i in range(0, len(points), batch_size):
            batch = points[i:i + batch_size]
            self.client.upsert(
                collection_name=collection_name,
                points=batch
            )

        logger.info(
            f"Stored {len(embeddings)} embeddings in collection {collection_name}"
        )

    def search(
        self,
        collection_name: str,
        query_vector: np.ndarray,
        limit: int = 10,
        score_threshold: float = 0.7,
        filter_conditions: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Perform similarity search in the collection.

        Args:
            collection_name: Name of the collection
            query_vector: Query embedding vector
            limit: Maximum number of results to return
            score_threshold: Minimum similarity score (0.0 to 1.0)
            filter_conditions: Optional metadata filters

        Returns:
            List of search results with 'id', 'score', and 'payload' keys
        """
        # Convert numpy array to list
        query_list = query_vector.tolist() if isinstance(query_vector, np.ndarray) else query_vector

        # Perform search using query method (newer API)
        search_result = self.client.query_points(
            collection_name=collection_name,
            query=query_list,
            limit=limit,
            score_threshold=score_threshold,
            query_filter=Filter(**filter_conditions) if filter_conditions else None
        )

        # Convert results to dictionaries
        results = [
            {
                "id": hit.id,
                "score": hit.score,
                "payload": hit.payload
            }
            for hit in search_result.points
        ]

        logger.debug(
            f"Search in {collection_name} returned {len(results)} results "
            f"(threshold={score_threshold})"
        )

        return results

    def delete_collection(self, collection_name: str) -> None:
        """
        Delete a collection.

        Args:
            collection_name: Name of the collection to delete
        """
        self.client.delete_collection(collection_name)
        logger.info(f"Deleted collection: {collection_name}")

    def collection_exists(self, collection_name: str) -> bool:
        """
        Check if a collection exists.

        Args:
            collection_name: Name of the collection

        Returns:
            True if collection exists, False otherwise
        """
        collections = self.client.get_collections().collections
        return any(c.name == collection_name for c in collections)

    def get_collection_info(self, collection_name: str) -> Dict[str, Any]:
        """
        Get information about a collection.

        Args:
            collection_name: Name of the collection

        Returns:
            Dictionary with collection information
        """
        info = self.client.get_collection(collection_name)
        return {
            "name": collection_name,
            "points_count": info.points_count,
            "vector_size": info.config.params.vectors.size,
            "distance": info.config.params.vectors.distance.name
        }
