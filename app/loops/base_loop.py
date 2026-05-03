"""
app/loops/base_loop.py

BaseLoop — abstract base class for all service loops.

Design rules from the plan (§6.5):
  - Every loop runs in its own daemon thread.
  - Loops run on a fixed interval, sleeping between cycles.
  - Same-job overlap is prevented with a non-blocking lock.
    If the previous cycle is still running when the next interval fires,
    the new cycle is skipped (not queued, not delayed).
  - One loop's failure must not crash other loops.
  - Shutdown is signalled via AppState.shutdown_event.
"""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod

from app.core.state import AppState
from app.utils.logger import logger


class BaseLoop(ABC):
    """
    Abstract loop. Subclass and implement :meth:`run_once`.

    Parameters
    ----------
    name : str
        Human-readable name used in log messages and thread name.
    interval_seconds : int
        How often to call :meth:`run_once`.
    app_state : AppState
        Shared service state (holds shutdown_event).
    """

    # Override in subclasses:
    interval_seconds: int = 60

    def __init__(self, name: str, interval_seconds: int, app_state: AppState) -> None:
        self.name = name
        self.interval_seconds = interval_seconds
        self.app_state = app_state

        # Prevents a cycle from running while the previous one is still active.
        self._running_lock = threading.Lock()

        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def run_once(self) -> None:
        """
        Execute one cycle of work.

        Implement all business logic here.
        Any exception raised here is caught by the loop runner
        and will NOT propagate to the thread or terminate the service.
        """

    # ------------------------------------------------------------------
    # Loop runner
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        """Internal thread target. Runs until shutdown_event is set."""
        logger.info("[{}] Loop started (interval={}s).", self.name, self.interval_seconds)

        while not self.app_state.shutdown_event.is_set():
            self._try_run_once()

            # Sleep in small increments so we can react to shutdown promptly.
            self._interruptible_sleep(self.interval_seconds)

        logger.info("[{}] Loop exiting — shutdown signal received.", self.name)

    def _try_run_once(self) -> None:
        """
        Attempt to run one cycle with overlap prevention and exception isolation.
        """
        # Non-blocking: if previous cycle is still running, skip this one.
        if not self._running_lock.acquire(blocking=False):
            logger.warning(
                "[{}] Previous cycle still running. Skipping this interval.", self.name
            )
            return

        try:
            self.run_once()
        except Exception as exc:  # noqa: BLE001
            # Exception isolation: log the error but keep the loop alive.
            logger.exception(
                "[{}] Unhandled exception in cycle (loop stays alive): {}", self.name, exc
            )
        finally:
            self._running_lock.release()

    def _interruptible_sleep(self, seconds: int) -> None:
        """
        Sleep for *seconds* but wake up early if shutdown_event is set.
        Checks the event every 0.5 s so shutdown is near-instant.
        """
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self.app_state.shutdown_event.is_set():
                return
            time.sleep(0.5)

    # ------------------------------------------------------------------
    # Thread management
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the loop in a background daemon thread."""
        if self._thread is not None and self._thread.is_alive():
            logger.warning("[{}] Loop already running.", self.name)
            return

        self._thread = threading.Thread(
            target=self._run_loop,
            name=self.name,
            daemon=True,  # dies automatically when main thread exits
        )
        self._thread.start()
        logger.debug("[{}] Thread started: id={}", self.name, self._thread.ident)

    def stop(self, timeout: float = 10.0) -> None:
        """
        Signal the loop to stop and wait for its thread to finish.

        The shutdown_event is shared across all loops, so calling this
        on any one loop notifies them all. The caller is responsible for
        sequencing stops via ThreadManager.
        """
        self.app_state.shutdown_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                logger.warning("[{}] Thread did not stop within {}s.", self.name, timeout)
            else:
                logger.info("[{}] Thread stopped cleanly.", self.name)

    def is_running(self) -> bool:
        """Return True if the background thread is alive."""
        return self._thread is not None and self._thread.is_alive()
