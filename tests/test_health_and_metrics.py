"""Tests for health check endpoints and metrics collection."""
import time
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from server.api import app
from utils.metrics import MetricsCollector, metrics


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def collector():
    """Fresh MetricsCollector for isolated tests."""
    return MetricsCollector()


# ===================================================================
# Task 41.1 – Health check endpoints
# ===================================================================


class TestHealthEndpoint:
    """Tests for GET /health."""

    def test_health_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_contains_status_and_timestamp(self, client):
        data = client.get("/health").json()
        assert "status" in data
        assert "timestamp" in data

    def test_health_contains_component_keys(self, client):
        data = client.get("/health").json()
        assert "components" in data
        assert "llm_server" in data["components"]
        assert "vector_db" in data["components"]

    @patch("server.api.llm_client", None)
    @patch("server.api.context_engine", None)
    def test_health_healthy_when_components_unavailable(self, client):
        """Unavailable (not initialised) components don't degrade status."""
        data = client.get("/health").json()
        assert data["status"] == "healthy"
        assert data["components"]["llm_server"] == "unavailable"
        assert data["components"]["vector_db"] == "unavailable"

    @patch("server.api._check_llm_health", return_value={"status": "unhealthy", "message": "down"})
    def test_health_degraded_when_llm_unhealthy(self, _mock, client):
        data = client.get("/health").json()
        assert data["status"] == "degraded"


class TestHealthDetailedEndpoint:
    """Tests for GET /health/detailed."""

    def test_detailed_returns_200(self, client):
        resp = client.get("/health/detailed")
        assert resp.status_code == 200

    def test_detailed_contains_full_component_info(self, client):
        data = client.get("/health/detailed").json()
        assert "components" in data
        # Detailed endpoint returns dicts, not just status strings
        for component in ("llm_server", "vector_db"):
            info = data["components"][component]
            assert isinstance(info, dict)
            assert "status" in info

    @patch("server.api.llm_client", None)
    @patch("server.api.context_engine", None)
    def test_detailed_shows_unavailable_message(self, client):
        data = client.get("/health/detailed").json()
        llm = data["components"]["llm_server"]
        assert llm["status"] == "unavailable"
        assert "message" in llm

    @patch("server.api._check_llm_health", return_value={"status": "healthy"})
    @patch("server.api._check_vector_db_health", return_value={"status": "healthy"})
    def test_detailed_healthy_when_all_ok(self, _vdb, _llm, client):
        data = client.get("/health/detailed").json()
        assert data["status"] == "healthy"


# ===================================================================
# Task 41.2 – Metrics collection
# ===================================================================


class TestMetricsCollectorTiming:
    """Tests for timing metrics."""

    def test_record_and_retrieve_timing(self, collector):
        collector.record_timing("test_op", 0.5)
        collector.record_timing("test_op", 1.0)
        stats = collector.get_timing_stats("test_op")
        assert stats["count"] == 2
        assert stats["total"] == pytest.approx(1.5)

    def test_timing_percentiles(self, collector):
        for v in range(1, 101):
            collector.record_timing("pct", float(v))
        stats = collector.get_timing_stats("pct")
        assert stats["p50"] == pytest.approx(50.5, abs=1)
        assert stats["p95"] == pytest.approx(95.05, abs=1)
        assert stats["p99"] == pytest.approx(99.01, abs=1)

    def test_empty_timing_returns_zeros(self, collector):
        stats = collector.get_timing_stats("nonexistent")
        assert stats["count"] == 0
        assert stats["p50"] == 0.0

    def test_max_samples_bounded(self):
        c = MetricsCollector(max_samples=5)
        for i in range(20):
            c.record_timing("bounded", float(i))
        stats = c.get_timing_stats("bounded")
        assert stats["count"] == 5


class TestMetricsCollectorCounters:
    """Tests for counter metrics."""

    def test_increment_counter(self, collector):
        collector.increment("errors.llm")
        collector.increment("errors.llm")
        assert collector.get_counter("errors.llm") == 2

    def test_increment_by_amount(self, collector):
        collector.increment("tokens", 100)
        collector.increment("tokens", 50)
        assert collector.get_counter("tokens") == 150

    def test_missing_counter_returns_zero(self, collector):
        assert collector.get_counter("nope") == 0


class TestMetricsCollectorGauges:
    """Tests for gauge metrics."""

    def test_set_and_get_gauge(self, collector):
        collector.set_gauge("active_sessions", 3.0)
        assert collector.get_gauge("active_sessions") == 3.0

    def test_gauge_overwrites(self, collector):
        collector.set_gauge("g", 1.0)
        collector.set_gauge("g", 9.0)
        assert collector.get_gauge("g") == 9.0

    def test_missing_gauge_returns_zero(self, collector):
        assert collector.get_gauge("missing") == 0.0


class TestMetricsTimerHelpers:
    """Tests for context manager and decorator helpers."""

    def test_timer_context_manager(self, collector):
        with collector.timer("ctx_op"):
            time.sleep(0.01)
        stats = collector.get_timing_stats("ctx_op")
        assert stats["count"] == 1
        assert stats["p50"] >= 0.005  # at least ~5ms

    def test_timed_decorator(self, collector):
        @collector.timed("dec_op")
        def do_work():
            return 42

        result = do_work()
        assert result == 42
        assert collector.get_timing_stats("dec_op")["count"] == 1


class TestMetricsSnapshot:
    """Tests for snapshot and reset."""

    def test_snapshot_structure(self, collector):
        collector.record_timing("t", 1.0)
        collector.increment("c")
        collector.set_gauge("g", 5.0)
        snap = collector.snapshot()
        assert "timings" in snap
        assert "counters" in snap
        assert "gauges" in snap
        assert snap["counters"]["c"] == 1
        assert snap["gauges"]["g"] == 5.0
        assert snap["timings"]["t"]["count"] == 1

    def test_reset_clears_all(self, collector):
        collector.record_timing("t", 1.0)
        collector.increment("c")
        collector.set_gauge("g", 1.0)
        collector.reset()
        snap = collector.snapshot()
        assert snap == {"timings": {}, "counters": {}, "gauges": {}}


class TestMetricsEndpoint:
    """Tests for GET /metrics API endpoint."""

    def test_metrics_returns_200(self, client):
        resp = client.get("/metrics")
        assert resp.status_code == 200

    def test_metrics_returns_snapshot_shape(self, client):
        data = client.get("/metrics").json()
        assert "timings" in data
        assert "counters" in data
        assert "gauges" in data
