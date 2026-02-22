"""
Önizleme meta veri paneli (salt okunur).
"""
from __future__ import annotations

from typing import Any

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QFormLayout, QLabel, QScrollArea


class MetadataPanel(QWidget):
    """Mevcut öğe meta verisi (EXIF, hash vb.)."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._form = QFormLayout()
        layout = QVBoxLayout(self)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner.setLayout(self._form)
        scroll.setWidget(inner)
        layout.addWidget(scroll)

    def set_metadata(self, meta: dict[str, Any] | None) -> None:
        """Meta veriyi göster."""
        while self._form.rowCount():
            self._form.removeRow(0)
        if not meta:
            self._form.addRow(QLabel("—"))
            return
        for key, value in (meta or {}).items():
            if value is None:
                value = "—"
            self._form.addRow(str(key), QLabel(str(value)))
