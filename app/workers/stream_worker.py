"""Trade update stream worker."""

from __future__ import annotations

from app.broker.stream_adapter import AlpacaStreamAdapter
from app.core.logging import get_logger


class StreamWorker:
    """Own the reconnecting trade-update stream loop."""

    def __init__(self, stream_adapter: AlpacaStreamAdapter) -> None:
        self._stream_adapter = stream_adapter
        self._logger = get_logger(__name__)

    async def start(self) -> None:
        """Run the stream worker in the background."""
        self._logger.info("stream_worker_started")
        await self._stream_adapter.start_in_background()

    async def stop(self) -> None:
        """Stop the stream worker."""
        self._logger.info("stream_worker_stopping")
        await self._stream_adapter.stop()
