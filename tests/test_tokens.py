"""Tests for token counting and context budget management utilities."""

import tiktoken
import pytest

from utils.tokens import count_tokens, truncate_to_tokens, fit_context_to_budget


class TestCountTokens:
    """Tests for the count_tokens function."""

    def test_empty_string_returns_zero(self):
        assert count_tokens("") == 0

    def test_simple_text(self):
        result = count_tokens("hello world")
        assert result > 0

    def test_count_matches_tiktoken(self):
        """Verify our count matches tiktoken directly."""
        text = "def foo():\n    return 42\n"
        encoder = tiktoken.get_encoding("cl100k_base")
        expected = len(encoder.encode(text))
        assert count_tokens(text) == expected

    def test_longer_text_has_more_tokens(self):
        short = count_tokens("hello")
        long = count_tokens("hello world this is a longer sentence with more tokens")
        assert long > short


class TestTruncateToTokens:
    """Tests for the truncate_to_tokens function."""

    def test_short_text_unchanged(self):
        text = "hello world"
        result = truncate_to_tokens(text, 100)
        assert result == text

    def test_truncation_adds_marker(self):
        text = "word " * 500  # Many tokens
        result = truncate_to_tokens(text, 10)
        assert result.endswith("...[truncated]")
        assert len(result) < len(text)

    def test_zero_budget_returns_empty(self):
        assert truncate_to_tokens("hello", 0) == ""

    def test_negative_budget_returns_empty(self):
        assert truncate_to_tokens("hello", -5) == ""

    def test_truncated_text_fits_budget(self):
        text = "x " * 1000
        result = truncate_to_tokens(text, 50)
        # The truncated content (minus the marker) should be within budget
        encoder = tiktoken.get_encoding("cl100k_base")
        # Remove the marker to check the core content
        core = result.replace("\n...[truncated]", "")
        assert len(encoder.encode(core)) <= 50


class TestFitContextToBudget:
    """Tests for the fit_context_to_budget function."""

    def _make_context(self, n: int, content_size: int = 50) -> list:
        """Helper to create context items with controlled content size."""
        return [
            {
                "file_path": f"file_{i}.py",
                "line_start": i * 10,
                "line_end": i * 10 + 10,
                "content": f"# line {i}\n" * content_size,
                "score": 0.95 - (i * 0.05),
            }
            for i in range(n)
        ]

    def test_empty_context_returns_empty(self):
        assert fit_context_to_budget([], token_budget=3500) == []

    def test_zero_budget_returns_empty(self):
        ctx = self._make_context(3)
        assert fit_context_to_budget(ctx, token_budget=0) == []

    def test_small_context_fits_entirely(self):
        ctx = [
            {
                "file_path": "a.py",
                "line_start": 1,
                "line_end": 5,
                "content": "x = 1",
                "score": 0.9,
            }
        ]
        result = fit_context_to_budget(ctx, token_budget=3500)
        assert len(result) == 1
        assert result[0]["file_path"] == "a.py"

    def test_respects_token_budget(self):
        """Context items that exceed budget are excluded."""
        # Create items with large content
        ctx = self._make_context(20, content_size=200)
        result = fit_context_to_budget(ctx, token_budget=500)
        # Should include fewer items than input
        assert len(result) < len(ctx)
        assert len(result) > 0

    def test_preserves_order(self):
        """Items should maintain their original order (highest score first)."""
        ctx = self._make_context(5, content_size=10)
        result = fit_context_to_budget(ctx, token_budget=5000)
        for i, item in enumerate(result):
            assert item["file_path"] == f"file_{i}.py"

    def test_truncates_large_individual_chunks(self):
        """Individual chunks exceeding max_chunk_tokens get truncated."""
        ctx = [
            {
                "file_path": "big.py",
                "line_start": 1,
                "line_end": 1000,
                "content": "x = 1\n" * 5000,  # Very large
                "score": 0.9,
            }
        ]
        result = fit_context_to_budget(
            ctx, token_budget=3500, max_chunk_tokens=100
        )
        assert len(result) == 1
        # Content should be truncated
        assert len(result[0]["content"]) < len(ctx[0]["content"])

    def test_skips_empty_content(self):
        ctx = [
            {"file_path": "empty.py", "line_start": 0, "line_end": 0, "content": ""},
            {"file_path": "real.py", "line_start": 1, "line_end": 5, "content": "x = 1"},
        ]
        result = fit_context_to_budget(ctx, token_budget=3500)
        assert len(result) == 1
        assert result[0]["file_path"] == "real.py"
