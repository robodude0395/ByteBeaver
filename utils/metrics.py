"""
In-memory metrics collection for the agent system.

Tracks latency percentiles, throughput, error rates, and session outcomes.
Provides timing helpers (context manager + decorator) for easy instrumentation.

Requirements:
    - 15.1: Track single-file generation time
    - 15.2: Track project scaffolding time
"""

import time
import threading
import logging
import functools
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------


def _percentile(sorted_values: List[float], p: float) -> float:
    """Return the *p*-th percentile from an already-sorted list (0–100)."""
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * (p / 100.0)
    f = int(k)
    c = f + 1
    if c >= len(sorted_values):
        return sorted_values[f]
    return sorted_values[f] + (k - f) * (sorted_values[c] - sorted_values[f])


# ---------------------------------------------------------------------------
# Core collector
# ---------------------------------------------------------------------------


class MetricsCollector:
    """Thread-safe, in-memory metrics store.

    Metric kinds
    -------------
    * **timing** – latency samples in seconds (e.g. ``llm_inference``)
    * **counter** – monotonically increasing integers (e.g. ``errors.llm``)
    * **gauge** – last-written value (e.g. ``active_sessions``)
    """

    def __init__(self, max_samples: int = 1000) -> None:
        self._lock = threading.Lock()
        self._max_samples = max_samples
        # timing metric name -> list of float seconds
        self._timings: Dict[str, List[float]] = {}
        # counter name -> int
        self._counters: Dict[str, int] = {}
        # gauge name -> float
        self._gauges: Dict[str, float] = {}

    # -- timing -------------------------------------------------------------

    def record_timing(self, name: str, duration: float) -> None:
        """Record a latency sample (seconds)."""
        with self._lock:
            if name not in self._timings:
                self._timings[name] = []
            samples = self._timings[name]
            samples.append(duration)
            # Keep bounded
            if len(samples) > self._max_samples:
                self._timings[name] = samples[-self._max_samples:]

    def get_timing_stats(self, name: str) -> Dict[str, float]:
        """Return p50 / p95 / p99 / count / total for a timing metric."""
        with self._lock:
            samples = list(self._timings.get(name, []))
        if not samples:
            return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "count": 0, "total": 0.0}
        samples.sort()
        return {
            "p50": round(_percentile(samples, 50), 6),
            "p95": round(_percentile(samples, 95), 6),
            "p99": round(_percentile(samples, 99), 6),
            "count": len(samples),
            "total": round(sum(samples), 6),
        }

    # -- counters -----------------------------------------------------------

    def increment(self, name: str, amount: int = 1) -> None:
        """Increment a counter."""
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + amount

    def get_counter(self, name: str) -> int:
        """Return current counter value."""
        with self._lock:
            return self._counters.get(name, 0)

    # -- gauges -------------------------------------------------------------

    def set_gauge(self, name: str, value: float) -> None:
        """Set a gauge to an absolute value."""
        with self._lock:
            self._gauges[name] = value

    def get_gauge(self, name: str) -> float:
        """Return current gauge value."""
        with self._lock:
            return self._gauges.get(name, 0.0)

    # -- helpers ------------------------------------------------------------

    @contextmanager
    def timer(self, name: str):
        """Context manager that records elapsed time under *name*.

        Usage::

            with metrics.timer("llm_inference"):
                result = llm.complete(messages)
        """
        start = time.monotonic()
        try:
            yield
        finally:
            elapsed = time.monotonic() - start
            self.record_timing(name, elapsed)

    def timed(self, name: Optional[str] = None):
        """Decorator that records elapsed time for each call.

        Usage::

            @metrics.timed("context_search")
            def search(query): ...
        """
        def decorator(fn):
            metric_name = name or f"{fn.__module__}.{fn.__qualname__}"

            @functools.wraps(fn)
            def wrapper(*args, **kwargs):
                start = time.monotonic()
                try:
                    return fn(*args, **kwargs)
                finally:
                    self.record_timing(metric_name, time.monotonic() - start)
            return wrapper
        return decorator

    # -- snapshot -----------------------------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        """Return a JSON-serialisable snapshot of all metrics."""
        with self._lock:
            timing_names = list(self._timings.keys())
            counter_copy = dict(self._counters)
            gauge_copy = dict(self._gauges)

        timings = {n: self.get_timing_stats(n) for n in timing_names}

        return {
            "timings": timings,
            "counters": counter_copy,
            "gauges": gauge_copy,
        }

    def reset(self) -> None:
        """Clear all collected metrics."""
        with self._lock:
            self._timings.clear()
            self._counters.clear()
            self._gauges.clear()


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

metrics = MetricsCollector()
"""Global metrics instance used throughout the application."""
