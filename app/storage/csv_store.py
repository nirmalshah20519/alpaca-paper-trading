"""
app/storage/csv_store.py

Thread-safe, file-locked CSV persistence layer.

Design rules:
  - In-process RLock guards all in-memory operations.
  - portalocker provides inter-process file locking.
  - Atomic writes: write to a .tmp file first, then rename.
  - Never write NaN or Infinity to CSVs.

Usage
-----
    store = CsvStore()
    store.append_row(Path("data/open_orders.csv"), row_dict)
    rows = store.read_rows(Path("data/open_orders.csv"))
"""

from __future__ import annotations

import csv
import os
import threading
from pathlib import Path
from typing import Any

import portalocker

from app.utils.logger import logger
from app.core.exceptions import StorageError


class CsvStore:
    """
    Low-level CSV helper.

    All public methods acquire the in-process lock and the file lock
    before touching the file system.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def init_file(self, file_path: Path, headers: list[str]) -> None:
        """
        Create *file_path* with *headers* if it does not exist yet.
        Safe to call on every startup.
        """
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            if not file_path.exists():
                self._write_headers(file_path, headers)
                logger.info("CSV initialised: {}", file_path)
            else:
                logger.debug("CSV already exists: {}", file_path)

    def append_row(self, file_path: Path, row: dict[str, Any]) -> None:
        """
        Append a single row dict to *file_path*.

        The file must already have headers (call `init_file` first).
        Strategy: read headers first in a separate read pass, then append.
        This avoids the UnsupportedOperation error from seek on an append-mode handle.
        """
        with self._lock:
            # Step 1: read headers from the existing file.
            headers = self._read_headers(file_path)
            if not headers:
                raise StorageError(
                    f"CSV file {file_path} has no headers. Call init_file first."
                )

            # Step 2: append the row under a file lock.
            try:
                with portalocker.Lock(str(file_path), mode="a", timeout=5) as fh:
                    writer = csv.DictWriter(
                        fh,
                        fieldnames=headers,
                        extrasaction="ignore",
                        lineterminator="\n",
                    )
                    writer.writerow(row)
                    fh.flush()
            except portalocker.LockException as exc:
                raise StorageError(f"Could not acquire lock on {file_path}: {exc}") from exc

    def read_rows(self, file_path: Path) -> list[dict[str, str]]:
        """
        Read all data rows from *file_path* as a list of dicts.

        Returns an empty list if the file is empty or has only headers.
        """
        with self._lock:
            if not file_path.exists():
                return []
            try:
                with portalocker.Lock(str(file_path), mode="r", timeout=5) as fh:
                    reader = csv.DictReader(fh)
                    return [dict(row) for row in reader]
            except portalocker.LockException as exc:
                raise StorageError(f"Could not acquire lock on {file_path}: {exc}") from exc

    def rewrite_rows_atomic(
        self, file_path: Path, headers: list[str], rows: list[dict[str, Any]]
    ) -> None:
        """
        Atomically replace the contents of *file_path* with *rows*.

        Steps:
          1. Acquire an exclusive file lock on the original file.
          2. Write new content to a sibling .tmp file.
          3. Flush + fsync.
          4. Unlock + close the lock handle (Windows requires this before rename).
          5. os.replace (atomic on POSIX; best-effort on Windows).

        We open the original file with mode="a" for locking (safe on Windows)
        and write the replacement to a .tmp file, then rename.
        """
        tmp_path = file_path.with_suffix(".tmp")
        with self._lock:
            # ---- Step 1: acquire exclusive file lock ----
            try:
                lock_fh = open(str(file_path), "a", encoding="utf-8")  # noqa: WPS515
                portalocker.lock(lock_fh, portalocker.LOCK_EX)
            except (OSError, portalocker.LockException) as exc:
                raise StorageError(
                    f"Could not acquire lock for atomic rewrite of {file_path}: {exc}"
                ) from exc

            write_error: Exception | None = None
            try:
                # ---- Step 2-3: write to tmp ----
                with open(tmp_path, "w", newline="", encoding="utf-8") as tmp_fh:
                    writer = csv.DictWriter(
                        tmp_fh,
                        fieldnames=headers,
                        extrasaction="ignore",
                        lineterminator="\n",
                    )
                    writer.writeheader()
                    writer.writerows(rows)
                    tmp_fh.flush()
                    os.fsync(tmp_fh.fileno())

            except OSError as exc:
                write_error = exc
            finally:
                # ---- Step 4: MUST unlock/close before os.replace on Windows ----
                portalocker.unlock(lock_fh)
                lock_fh.close()

            if write_error is not None:
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass
                raise StorageError(
                    f"Atomic rewrite failed (write stage) for {file_path}: {write_error}"
                ) from write_error

            # ---- Step 5: atomic rename ----
            try:
                os.replace(tmp_path, file_path)
                logger.debug("Atomic rewrite completed: {}", file_path)
            except OSError as exc:
                raise StorageError(
                    f"Atomic rewrite failed (rename stage) for {file_path}: {exc}"
                ) from exc
            finally:
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _read_headers(self, file_path: Path) -> list[str]:
        """Read only the header line from *file_path*. Returns [] if not found."""
        if not file_path.exists():
            return []
        with open(file_path, "r", newline="", encoding="utf-8") as fh:
            first_line = fh.readline().strip()
        if not first_line:
            return []
        return next(csv.reader([first_line]))

    def _write_headers(self, file_path: Path, headers: list[str]) -> None:
        with open(file_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(
                fh, fieldnames=headers, lineterminator="\n"
            )
            writer.writeheader()
            fh.flush()
