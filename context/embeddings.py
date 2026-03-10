"""
Embedding model wrapper for generating semantic embeddings.

This module provides a wrapper class for the sentence-transformers library,
specifically configured for the bge-small-en-v1.5 model.
"""

from typing import List, Union
import logging
import numpy as np
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


class EmbeddingModel:
    """Wrapper class for generating embeddings using sentence-transformers."""

    def __init__(self, model_path: str = "BAAI/bge-small-en-v1.5"):
        """
        Initialize the embedding model.

        Args:
            model_path: Path to the model (local path or HuggingFace model ID)
                       Default is "BAAI/bge-small-en-v1.5" which will download
                       from HuggingFace if not cached locally.

        Raises:
            Exception: If model fails to load
        """
        try:
            logger.info(f"Loading embedding model from {model_path}")
            self.model = SentenceTransformer(model_path)
            self.vector_size = self.model.get_sentence_embedding_dimension()
            logger.info(
                f"Loaded embedding model successfully. "
                f"Vector size: {self.vector_size}"
            )
        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            raise

    def encode(
        self,
        texts: Union[str, List[str]],
        batch_size: int = 32,
        normalize: bool = True,
        show_progress: bool = False
    ) -> np.ndarray:
        """
        Generate embeddings for text(s).

        Args:
            texts: Single text string or list of text strings
            batch_size: Batch size for encoding (default: 32)
            normalize: If True, normalize embeddings for cosine similarity (default: True)
            show_progress: If True, show progress bar during encoding (default: False)

        Returns:
            numpy array of embeddings:
            - If texts is a string: shape (vector_size,)
            - If texts is a list: shape (len(texts), vector_size)

        Raises:
            ValueError: If texts is an empty list
        """
        # Convert single string to list for consistent processing
        is_single = isinstance(texts, str)
        if is_single:
            texts = [texts]

        # Handle empty list (but allow empty strings)
        if len(texts) == 0:
            raise ValueError("Cannot encode empty text list")

        # Generate embeddings
        logger.debug(f"Encoding {len(texts)} text(s) with batch_size={batch_size}")
        embeddings = self.model.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=normalize,
            show_progress_bar=show_progress,
            convert_to_numpy=True
        )

        # Return single embedding if input was single string
        if is_single:
            return embeddings[0]

        return embeddings

    def get_vector_size(self) -> int:
        """
        Get the dimension of the embedding vectors.

        Returns:
            Integer dimension of embedding vectors (384 for bge-small-en-v1.5)
        """
        return self.vector_size

    def encode_batch(
        self,
        texts: List[str],
        batch_size: int = 32,
        normalize: bool = True
    ) -> List[np.ndarray]:
        """
        Generate embeddings for a batch of texts.

        This is a convenience method that returns a list of individual embeddings
        rather than a single numpy array.

        Args:
            texts: List of text strings
            batch_size: Batch size for encoding (default: 32)
            normalize: If True, normalize embeddings for cosine similarity (default: True)

        Returns:
            List of numpy arrays, one per input text

        Raises:
            ValueError: If texts is empty
        """
        embeddings = self.encode(
            texts=texts,
            batch_size=batch_size,
            normalize=normalize,
            show_progress=False
        )

        # Convert to list of individual arrays
        return [embeddings[i] for i in range(len(embeddings))]
