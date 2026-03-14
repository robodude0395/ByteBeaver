"""
Tests for web search tools.

Covers unit tests, property tests for result structure, and graceful failure.
"""

import time
from unittest.mock import patch, MagicMock

import pytest
from hypothesis import given, strategies as st, settings

from tools.web import WebTools, WebResult


# --- Fixtures ---

@pytest.fixture
def enabled_config():
    return {"web_search_enabled": True}


@pytest.fixture
def disabled_config():
    return {"web_search_enabled": False}


@pytest.fixture
def web_tools(enabled_config):
    return WebTools(enabled_config)


FAKE_DDGS_RESULTS = [
    {"title": "Result One", "href": "https://example.com/one", "body": "snippet one"},
    {"title": "Result Two", "href": "https://example.com/two", "body": "snippet two"},
    {"title": "Result Three", "href": "https://example.com/three", "body": "snippet three"},
]

FAKE_HTML = "<html><head><title>Page</title></head><body><p>Hello world content here</p></body></html>"


def _mock_ddgs_and_requests(ddgs_results=None, html=FAKE_HTML, scrape_error=False):
    """Helper to set up mocks for DDGS and requests.get."""
    if ddgs_results is None:
        ddgs_results = FAKE_DDGS_RESULTS

    mock_ddgs_instance = MagicMock()
    mock_ddgs_instance.text.return_value = ddgs_results
    mock_ddgs_class = MagicMock(return_value=mock_ddgs_instance)

    mock_response = MagicMock()
    mock_response.text = html

    if scrape_error:
        mock_get = MagicMock(side_effect=Exception("Connection error"))
    else:
        mock_get = MagicMock(return_value=mock_response)

    return mock_ddgs_class, mock_get


# --- Unit Tests (27.4) ---

class TestWebSearchBasic:
    """Test basic web search functionality."""

    def test_disabled_returns_empty(self, disabled_config):
        """Test that disabled web search returns empty list."""
        tools = WebTools(disabled_config)
        result = tools.web_search("python tutorial")
        assert result == []

    def test_no_config_returns_empty(self):
        """Test that no config (default disabled) returns empty list."""
        tools = WebTools()
        result = tools.web_search("python tutorial")
        assert result == []

    @patch("tools.web.time.sleep")
    @patch("tools.web.requests.get")
    @patch("tools.web.DDGS")
    def test_valid_query_returns_results(self, mock_ddgs_cls, mock_get, mock_sleep, web_tools):
        mock_ddgs_cls.return_value.text.return_value = FAKE_DDGS_RESULTS
        mock_response = MagicMock()
        mock_response.text = FAKE_HTML
        mock_get.return_value = mock_response

        results = web_tools.web_search("python tutorial")

        assert len(results) == 3
        assert all(isinstance(r, WebResult) for r in results)
        mock_ddgs_cls.return_value.text.assert_called_once_with("python tutorial", max_results=3)

    @patch("tools.web.time.sleep")
    @patch("tools.web.requests.get")
    @patch("tools.web.DDGS")
    def test_result_fields_populated(self, mock_ddgs_cls, mock_get, mock_sleep, web_tools):
        mock_ddgs_cls.return_value.text.return_value = FAKE_DDGS_RESULTS[:1]
        mock_response = MagicMock()
        mock_response.text = FAKE_HTML
        mock_get.return_value = mock_response

        results = web_tools.web_search("test")

        assert len(results) == 1
        r = results[0]
        assert r.title == "Result One"
        assert r.url == "https://example.com/one"
        assert isinstance(r.summary, str)
        assert isinstance(r.content, str)
        assert len(r.summary) <= 500
        assert len(r.content) <= 5000


class TestHTMLScraping:
    """Test HTML scraping and content extraction."""

    @patch("tools.web.time.sleep")
    @patch("tools.web.requests.get")
    @patch("tools.web.DDGS")
    def test_extracts_text_from_html(self, mock_ddgs_cls, mock_get, mock_sleep, web_tools):
        mock_ddgs_cls.return_value.text.return_value = FAKE_DDGS_RESULTS[:1]
        mock_response = MagicMock()
        mock_response.text = "<html><body><p>Important text</p><div>More text</div></body></html>"
        mock_get.return_value = mock_response

        results = web_tools.web_search("test")

        assert len(results) == 1
        assert "Important text" in results[0].content
        assert "More text" in results[0].content

    @patch("tools.web.time.sleep")
    @patch("tools.web.requests.get")
    @patch("tools.web.DDGS")
    def test_summary_truncated_to_500(self, mock_ddgs_cls, mock_get, mock_sleep, web_tools):
        mock_ddgs_cls.return_value.text.return_value = FAKE_DDGS_RESULTS[:1]
        mock_response = MagicMock()
        mock_response.text = f"<html><body><p>{'x' * 1000}</p></body></html>"
        mock_get.return_value = mock_response

        results = web_tools.web_search("test")

        assert len(results[0].summary) <= 500

    @patch("tools.web.time.sleep")
    @patch("tools.web.requests.get")
    @patch("tools.web.DDGS")
    def test_content_truncated_to_5000(self, mock_ddgs_cls, mock_get, mock_sleep, web_tools):
        mock_ddgs_cls.return_value.text.return_value = FAKE_DDGS_RESULTS[:1]
        mock_response = MagicMock()
        mock_response.text = f"<html><body><p>{'y' * 10000}</p></body></html>"
        mock_get.return_value = mock_response

        results = web_tools.web_search("test")

        assert len(results[0].content) <= 5000


class TestRateLimiting:
    """Test rate limiting behavior."""

    @patch("tools.web.time.sleep")
    @patch("tools.web.requests.get")
    @patch("tools.web.DDGS")
    def test_max_5_searches_per_session(self, mock_ddgs_cls, mock_get, mock_sleep, web_tools):
        mock_ddgs_cls.return_value.text.return_value = FAKE_DDGS_RESULTS[:1]
        mock_response = MagicMock()
        mock_response.text = FAKE_HTML
        mock_get.return_value = mock_response

        # First 5 searches should work
        for i in range(5):
            results = web_tools.web_search(f"query {i}")
            assert len(results) == 1

        # 6th search should return empty (rate limited)
        results = web_tools.web_search("query 6")
        assert results == []

    @patch("tools.web.time.time")
    @patch("tools.web.time.sleep")
    @patch("tools.web.requests.get")
    @patch("tools.web.DDGS")
    def test_delay_between_searches(self, mock_ddgs_cls, mock_get, mock_sleep, mock_time, enabled_config):
        mock_ddgs_cls.return_value.text.return_value = FAKE_DDGS_RESULTS[:1]
        mock_response = MagicMock()
        mock_response.text = FAKE_HTML
        mock_get.return_value = mock_response

        # Simulate time: first call at t=100, second call at t=100.5 (only 0.5s elapsed)
        mock_time.side_effect = [100.0, 100.5, 100.5]

        tools = WebTools(enabled_config)
        tools.web_search("first")
        tools.web_search("second")

        # Should have slept for 1.5 seconds (2.0 - 0.5)
        mock_sleep.assert_called_once_with(pytest.approx(1.5, abs=0.1))


class TestGracefulFailure:
    """Test graceful failure on errors."""

    @patch("tools.web.time.sleep")
    @patch("tools.web.DDGS")
    def test_ddgs_exception_returns_empty(self, mock_ddgs_cls, mock_sleep, web_tools):
        mock_ddgs_cls.return_value.text.side_effect = Exception("API error")

        results = web_tools.web_search("test")

        assert results == []

    @patch("tools.web.time.sleep")
    @patch("tools.web.requests.get")
    @patch("tools.web.DDGS")
    def test_scrape_failure_skips_result(self, mock_ddgs_cls, mock_get, mock_sleep, web_tools):
        mock_ddgs_cls.return_value.text.return_value = FAKE_DDGS_RESULTS[:2]
        # First scrape fails, second succeeds
        mock_response = MagicMock()
        mock_response.text = FAKE_HTML
        mock_get.side_effect = [Exception("Timeout"), mock_response]

        results = web_tools.web_search("test")

        assert len(results) == 1
        assert results[0].url == "https://example.com/two"

    @patch("tools.web.time.sleep")
    @patch("tools.web.requests.get")
    @patch("tools.web.DDGS")
    def test_all_scrapes_fail_returns_empty(self, mock_ddgs_cls, mock_get, mock_sleep, web_tools):
        mock_ddgs_cls.return_value.text.return_value = FAKE_DDGS_RESULTS
        mock_get.side_effect = Exception("Network error")

        results = web_tools.web_search("test")

        assert results == []

    @patch("tools.web.time.sleep")
    @patch("tools.web.DDGS")
    def test_never_raises_exception(self, mock_ddgs_cls, mock_sleep, web_tools):
        """Ensure web_search never raises, regardless of error type."""
        mock_ddgs_cls.side_effect = RuntimeError("Unexpected crash")

        # Should not raise
        results = web_tools.web_search("test")
        assert results == []


# --- Property Tests (27.2, 27.3) ---

class TestWebSearchResultStructureProperty:
    """
    Property 15: Web Search Result Structure

    **Validates: Requirements 9.4**

    Test that all results have title, url, summary, content fields.
    """

    @given(
        titles=st.lists(st.text(min_size=1, max_size=50), min_size=1, max_size=3),
        urls=st.lists(
            st.from_regex(r"https://[a-z]+\.[a-z]+/[a-z]+", fullmatch=True),
            min_size=1,
            max_size=3,
        ),
        html_content=st.text(min_size=1, max_size=200),
    )
    @settings(max_examples=20)
    @patch("tools.web.time.sleep")
    @patch("tools.web.requests.get")
    @patch("tools.web.DDGS")
    def test_property_15_all_results_have_required_fields(
        self, mock_ddgs_cls, mock_get, mock_sleep, titles, urls, html_content
    ):
        # Build DDGS results from generated data
        count = min(len(titles), len(urls))
        ddgs_results = [
            {"title": titles[i], "href": urls[i], "body": "snippet"}
            for i in range(count)
        ]
        mock_ddgs_cls.return_value.text.return_value = ddgs_results

        mock_response = MagicMock()
        mock_response.text = f"<html><body>{html_content}</body></html>"
        mock_get.return_value = mock_response

        tools = WebTools({"web_search_enabled": True})
        results = tools.web_search("test query")

        for r in results:
            assert hasattr(r, "title") and isinstance(r.title, str)
            assert hasattr(r, "url") and isinstance(r.url, str)
            assert hasattr(r, "summary") and isinstance(r.summary, str)
            assert hasattr(r, "content") and isinstance(r.content, str)
            assert len(r.summary) <= 500
            assert len(r.content) <= 5000


class TestWebSearchGracefulFailureProperty:
    """
    Property 16: Web Search Graceful Failure

    **Validates: Requirements 9.5**

    Test that errors return empty list without raising exceptions.
    """

    @given(
        error_type=st.sampled_from([
            Exception, RuntimeError, ConnectionError, TimeoutError, ValueError, OSError
        ]),
        query=st.text(min_size=1, max_size=100),
    )
    @settings(max_examples=20)
    @patch("tools.web.time.sleep")
    @patch("tools.web.DDGS")
    def test_property_16_errors_return_empty_list(
        self, mock_ddgs_cls, mock_sleep, error_type, query
    ):
        mock_ddgs_cls.return_value.text.side_effect = error_type("simulated failure")

        tools = WebTools({"web_search_enabled": True})
        results = tools.web_search(query)

        assert isinstance(results, list)
        assert len(results) == 0
