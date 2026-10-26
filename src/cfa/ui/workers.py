"""Background work on QThreadPool. The UI thread never blocks on the network (PLAN §9 rule 6)."""

from __future__ import annotations

import logging
import threading
import traceback
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal

log = logging.getLogger(__name__)


class WorkerSignals(QObject):
    progress = Signal(int, int, str)
    partial = Signal(object)  # list[CollegeRecord]: results before the Common Data Sets are read
    update = Signal(object)  # CollegeRecord: one school again, now with its Common Data Set
    finished = Signal(object)
    failed = Signal(str)


class Worker(QRunnable):
    """Runs fn(progress, cancel_event) in a pool thread; exceptions become a `failed` signal."""

    def __init__(self, fn: Callable[[Callable[[int, int, str], None], threading.Event], Any]) -> None:
        super().__init__()
        self.fn = fn
        self.signals = WorkerSignals()
        self.cancel_event = threading.Event()
        self.setAutoDelete(True)

    def cancel(self) -> None:
        self.cancel_event.set()

    def run(self) -> None:
        try:
            result = self.fn(self._progress, self.cancel_event)
        except Exception as exc:  # caught, logged, shown as a toast; never crashes the app
            log.error("Background task failed: %s\n%s", type(exc).__name__, traceback.format_exc(limit=5))
            try:
                self.signals.failed.emit(f"{type(exc).__name__}: {exc}")
            except RuntimeError:
                pass
            return
        try:
            self.signals.finished.emit(result)
        except RuntimeError:  # receiver deleted during shutdown
            pass

    def emit_partial(self, records: Any) -> None:
        try:
            self.signals.partial.emit(records)
        except RuntimeError:
            pass

    def emit_update(self, record: Any) -> None:
        try:
            self.signals.update.emit(record)
        except RuntimeError:
            pass

    def _progress(self, done: int, total: int, label: str) -> None:
        try:
            self.signals.progress.emit(done, total, label)
        except RuntimeError:
            pass
