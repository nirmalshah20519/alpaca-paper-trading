"""
tests/test_thread_safety.py

Tests for BaseLoop / ThreadManager:
  - Loop starts and stops cleanly.
  - Shutdown_event stops all loops.
  - One loop failure does not crash other loops.
  - Same-job overlap is skipped (not queued).
"""

from __future__ import annotations

import threading
import time

import pytest

from app.core.state import AppState
from app.loops.base_loop import BaseLoop


# ---------------------------------------------------------------------------
# Concrete test loops
# ---------------------------------------------------------------------------

class CountingLoop(BaseLoop):
    """Increments a counter on each successful run_once()."""

    def __init__(self, app_state: AppState, interval_seconds: int = 1) -> None:
        super().__init__("CountingLoop", interval_seconds, app_state)
        self.count = 0

    def run_once(self) -> None:
        self.count += 1


class FailingLoop(BaseLoop):
    """Always raises an exception in run_once()."""

    def __init__(self, app_state: AppState) -> None:
        super().__init__("FailingLoop", 1, app_state)
        self.attempts = 0

    def run_once(self) -> None:
        self.attempts += 1
        raise RuntimeError("Simulated loop failure")


class SlowLoop(BaseLoop):
    """Sleeps longer than its interval to trigger overlap prevention."""

    def __init__(self, app_state: AppState) -> None:
        super().__init__("SlowLoop", 1, app_state)
        self.started_count = 0

    def run_once(self) -> None:
        self.started_count += 1
        time.sleep(5)  # Deliberately slow


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBaseLoopStartStop:

    def test_loop_starts_and_stops(self):
        state = AppState()
        loop = CountingLoop(state, interval_seconds=1)

        loop.start()
        assert loop.is_running()

        time.sleep(0.1)
        state.request_shutdown()
        loop._thread.join(timeout=5)

        assert not loop.is_running()

    def test_loop_runs_at_least_once(self):
        state = AppState()
        loop = CountingLoop(state, interval_seconds=60)  # long interval

        loop.start()
        time.sleep(0.3)  # Give it time to run run_once() immediately

        state.request_shutdown()
        loop._thread.join(timeout=5)

        assert loop.count >= 1

    def test_loop_does_not_run_after_shutdown(self):
        state = AppState()
        state.request_shutdown()  # Shutdown before starting

        loop = CountingLoop(state, interval_seconds=1)
        loop.start()
        time.sleep(0.3)

        # Thread should exit almost immediately since shutdown_event is set.
        loop._thread.join(timeout=5)
        assert not loop.is_running()


class TestLoopFailureIsolation:

    def test_failing_loop_keeps_retrying_without_crashing(self):
        """
        A loop that raises every cycle should keep looping (exception isolated),
        not terminate the thread.
        """
        state = AppState()
        loop = FailingLoop(state)

        loop.start()
        time.sleep(2.5)  # Allow multiple cycles

        state.request_shutdown()
        loop._thread.join(timeout=5)

        # Should have attempted at least 2 cycles despite always failing.
        assert loop.attempts >= 2

    def test_one_loop_failure_does_not_stop_other_loops(self):
        """
        FailingLoop and CountingLoop run independently.
        FailingLoop always crashes; CountingLoop should still accumulate counts.
        """
        state = AppState()
        failing = FailingLoop(state)
        counter = CountingLoop(state, interval_seconds=1)

        failing.start()
        counter.start()

        time.sleep(2.5)

        state.request_shutdown()
        failing._thread.join(timeout=5)
        counter._thread.join(timeout=5)

        assert not failing.is_running()
        assert not counter.is_running()
        # CountingLoop should have run despite FailingLoop crashing continuously.
        assert counter.count >= 1


class TestOverlapPrevention:

    def test_slow_loop_skips_next_cycle_while_still_running(self):
        """
        SlowLoop.run_once() takes 5 s but interval is 1 s.
        The second cycle should be skipped (non-blocking lock fails),
        so started_count should stay at 1 during the first 3 seconds.
        """
        state = AppState()
        loop = SlowLoop(state)

        loop.start()
        time.sleep(3)  # Wait 3 s — only 1 cycle should have started

        state.request_shutdown()
        loop._thread.join(timeout=10)

        # run_once started exactly once (second cycle was skipped)
        assert loop.started_count == 1


class TestShutdownEvent:

    def test_shutdown_event_stops_all_loops(self):
        """Setting the shared shutdown_event should stop all loops."""
        state = AppState()
        loops = [CountingLoop(state, interval_seconds=60) for _ in range(3)]

        for loop in loops:
            loop.start()

        time.sleep(0.2)
        state.request_shutdown()

        for loop in loops:
            loop._thread.join(timeout=5)
            assert not loop.is_running()

    def test_interruptible_sleep_exits_early(self):
        """
        A loop sleeping for 60 s should exit within ~1 s when shutdown is set.
        """
        state = AppState()
        loop = CountingLoop(state, interval_seconds=60)

        loop.start()
        time.sleep(0.3)  # Let it run once

        start = time.monotonic()
        state.request_shutdown()
        loop._thread.join(timeout=5)
        elapsed = time.monotonic() - start

        assert elapsed < 3.0, f"Loop took {elapsed:.1f}s to stop — interruptible sleep not working"
