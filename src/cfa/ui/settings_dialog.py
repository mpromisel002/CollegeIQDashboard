"""Settings: Scorecard API key (Windows Credential Manager via keyring), connection tests, registry reload."""

from __future__ import annotations

import asyncio

from PySide6.QtCore import QThreadPool, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cfa import config
from cfa.pipeline import health_checks
from cfa.sources.registry import Registry
from cfa.ui.workers import Worker


class SettingsDialog(QDialog):
    reload_registry = Signal()

    def __init__(self, registry: Registry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.registry = registry
        self.key = QLineEdit(config.scorecard_api_key() or "")
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("Free key from https://api.data.gov/signup")
        show = QPushButton("Show")
        show.setCheckable(True)
        show.toggled.connect(
            lambda on: self.key.setEchoMode(QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password)
        )
        key_row = QHBoxLayout()
        key_row.addWidget(self.key, 1)
        key_row.addWidget(show)

        self.health = QLabel("Not tested yet.")
        self.health.setWordWrap(True)
        test = QPushButton("Test connections")
        test.clicked.connect(self._test)
        reload_btn = QPushButton("Reload registry")
        reload_btn.clicked.connect(self.reload_registry)

        form = QFormLayout()
        form.addRow("College Scorecard API key", key_row)
        form.addRow("", QLabel("<small>Stored in Windows Credential Manager, never in a file.</small>"))
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        v = QVBoxLayout(self)
        v.addLayout(form)
        row = QHBoxLayout()
        row.addWidget(test)
        row.addWidget(reload_btn)
        row.addStretch(1)
        v.addLayout(row)
        v.addWidget(self.health)
        v.addWidget(buttons)

    def _save(self) -> None:
        if not config.set_scorecard_api_key(self.key.text().strip() or None):
            self.health.setText("Could not save the key to the system credential store.")
            return
        self.accept()

    def _test(self) -> None:
        key = self.key.text().strip() or None
        registry = self.registry
        self.health.setText("Testing…")
        worker = Worker(lambda progress, cancel: asyncio.run(health_checks(registry, key)))
        worker.signals.finished.connect(self._show_health)
        worker.signals.failed.connect(lambda msg: self.health.setText(f"Test failed: {msg}"))
        QThreadPool.globalInstance().start(worker)

    def _show_health(self, results: dict) -> None:
        lines = [
            f"<b>{src}</b>: {r.status.value} — {r.note} ({r.elapsed_s:.1f}s)" for src, r in results.items()
        ]
        self.health.setText("<br>".join(lines))
