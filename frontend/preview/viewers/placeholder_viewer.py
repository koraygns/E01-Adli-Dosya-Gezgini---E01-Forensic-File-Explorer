"""
Desteklenmeyen / 0 byte / klasör için placeholder.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel


class PlaceholderViewer(QWidget):
    """Desteklenmeyen türler için mesaj."""

    def __init__(self, item: dict | None = None):
        super().__init__()
        layout = QVBoxLayout(self)
        self._label = QLabel(self._message_for(item))
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setWordWrap(True)
        layout.addWidget(self._label)

    @staticmethod
    def _message_for(item: dict | None) -> str:
        if not item:
            return "Öğe yok."
        if item.get("is_dir"):
            return "Klasör önizlenemez."
        try:
            size = item.get("size")
            if size is not None and int(size) == 0:
                return "0 byte dosya — içerik yok (forensic)."
        except (TypeError, ValueError):
            pass
        name = item.get("name") or ""
        return f"Desteklenmeyen format: {name}"
