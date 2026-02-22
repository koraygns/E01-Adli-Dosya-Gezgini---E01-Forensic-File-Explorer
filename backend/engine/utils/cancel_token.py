"""
Cancellation token for cooperative cancellation of background work (e.g. warmup on folder change).
Thread-safe; workers should check is_cancelled() and stop submitting new work.
"""
import threading


class CancellationToken:
    """İptal sinyali."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()
