"""
Unit tests for embedding model.

Tests the EmbeddingModel wrapper class for sentence-transformers.
"""

import pytest
import numpy as np
from context.embeddings import EmbeddingModel


@pytest.fixture
def embedding_model():
    """Create an EmbeddingModel instance for testing."""
    # Use the default model (will download if not cached)
    return EmbeddingModel()


@pytest.fixture
def sample_texts():
    """Generate sample texts for testing."""
    return [
        "This is a test sentence about Python programming.",
        "Machine learning models require training data.",
        "The quick brown fox jumps over the lazy dog.",
        "Natural language processing is a subfield of AI.",
        "Vector embeddings capture semantic meaning."
    ]


class TestEmbeddingModelInitialization:
    """Tests for model initialization."""

    def test_model_loads_successfully(self, embedding_model):
        """Test that model loads without errors."""
        assert embedding_model.model is not None
        assert embedding_model.vector_size > 0

    def test_vector_size_is_384(self, embedding_model):
        """Test that bge-small-en-v1.5 has 384 dimensions."""
        assert embedding_model.get_vector_size() == 384


class TestEmbeddingGeneration:
    """Tests for encoding text to embeddings."""

    def test_encode_single_string(self, embedding_model):
        """Test encoding a single string."""
        text = "This is a test sentence."
        embedding = embedding_model.encode(text)

        assert isinstance(embedding, np.ndarray)
        assert embedding.shape == (384,)
        assert embedding.dtype == np.float32

    def test_encode_list_of_strings(self, embedding_model, sample_texts):
        """Test encoding a list of strings."""
        embeddings = embedding_model.encode(sample_texts)

        assert isinstance(embeddings, np.ndarray)
        assert embeddings.shape == (len(sample_texts), 384)
        assert embeddings.dtype == np.float32

    def test_encode_empty_list_raises_error(self, embedding_model):
        """Test that encoding empty list raises ValueError."""
        with pytest.raises(ValueError, match="Cannot encode empty text list"):
            embedding_model.encode([])

    def test_encode_normalization(self, embedding_model):
        """Test that embeddings are normalized when normalize=True."""
        text = "Test normalization"

        # With normalization (default)
        embedding_normalized = embedding_model.encode(text, normalize=True)
        norm = np.linalg.norm(embedding_normalized)
        assert norm == pytest.approx(1.0, rel=1e-4)

        # Without normalization
        embedding_unnormalized = embedding_model.encode(text, normalize=False)
        norm_unnormalized = np.linalg.norm(embedding_unnormalized)
        # Unnormalized might still be close to 1.0 but should be different
        # Just verify it's a valid embedding
        assert norm_unnormalized > 0

    def test_encode_batch_method(self, embedding_model, sample_texts):
        """Test encode_batch convenience method."""
        embeddings_list = embedding_model.encode_batch(sample_texts)

        assert isinstance(embeddings_list, list)
        assert len(embeddings_list) == len(sample_texts)

        for embedding in embeddings_list:
            assert isinstance(embedding, np.ndarray)
            assert embedding.shape == (384,)

    def test_encode_with_different_batch_sizes(self, embedding_model, sample_texts):
        """Test encoding with different batch sizes produces same results."""
        embeddings_batch_2 = embedding_model.encode(sample_texts, batch_size=2)
        embeddings_batch_5 = embedding_model.encode(sample_texts, batch_size=5)

        # Results should be very similar regardless of batch size (allow small numerical differences)
        np.testing.assert_allclose(embeddings_batch_2, embeddings_batch_5, rtol=1e-3, atol=1e-6)


class TestEmbeddingSimilarity:
    """Tests for semantic similarity using embeddings."""

    def test_similar_texts_have_high_similarity(self, embedding_model):
        """Test that semantically similar texts have high cosine similarity."""
        text1 = "Python is a programming language."
        text2 = "Python is used for software development."
        text3 = "The weather is sunny today."

        emb1 = embedding_model.encode(text1)
        emb2 = embedding_model.encode(text2)
        emb3 = embedding_model.encode(text3)

        # Cosine similarity (embeddings are normalized)
        similarity_1_2 = np.dot(emb1, emb2)
        similarity_1_3 = np.dot(emb1, emb3)

        # Similar texts should have higher similarity
        assert similarity_1_2 > similarity_1_3
        assert similarity_1_2 > 0.5  # Should be reasonably similar

    def test_identical_texts_have_perfect_similarity(self, embedding_model):
        """Test that identical texts have similarity of 1.0."""
        text = "This is a test sentence."

        emb1 = embedding_model.encode(text)
        emb2 = embedding_model.encode(text)

        similarity = np.dot(emb1, emb2)
        assert similarity == pytest.approx(1.0, rel=1e-5)

    def test_batch_encoding_consistency(self, embedding_model, sample_texts):
        """Test that batch encoding produces same results as individual encoding."""
        # Encode all at once
        embeddings_batch = embedding_model.encode(sample_texts)

        # Encode individually
        embeddings_individual = np.array([
            embedding_model.encode(text) for text in sample_texts
        ])

        # Should be very similar (allow small numerical differences)
        np.testing.assert_allclose(embeddings_batch, embeddings_individual, rtol=1e-3, atol=1e-6)


class TestEmbeddingModelEdgeCases:
    """Tests for edge cases and error handling."""

    def test_encode_very_long_text(self, embedding_model):
        """Test encoding very long text (should be truncated by model)."""
        # Create a very long text (much longer than model's max sequence length)
        long_text = " ".join(["word"] * 1000)

        # Should not raise error, model will truncate
        embedding = embedding_model.encode(long_text)
        assert embedding.shape == (384,)

    def test_encode_special_characters(self, embedding_model):
        """Test encoding text with special characters."""
        text = "Hello! @#$%^&*() 你好 🚀"

        embedding = embedding_model.encode(text)
        assert embedding.shape == (384,)

    def test_encode_empty_string(self, embedding_model):
        """Test encoding empty string (should work but produce generic embedding)."""
        text = ""

        embedding = embedding_model.encode(text)
        assert embedding.shape == (384,)

    def test_encode_whitespace_only(self, embedding_model):
        """Test encoding whitespace-only string."""
        text = "   \n\t  "

        embedding = embedding_model.encode(text)
        assert embedding.shape == (384,)
