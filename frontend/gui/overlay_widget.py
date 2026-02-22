"""
Thumbnail yüklenirken overlay (karartma + bekleme).
"""
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QProgressBar,
    QFrame,
    QSizePolicy,
)
from PyQt6.QtGui import QFont


class ThumbnailOverlayWidget(QFrame):
    """Yarı saydam overlay, spinner ve mesaj."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("thumbnailOverlay")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(200, 120)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet("""
            #thumbnailOverlay {
                background-color: rgba(0, 0, 0, 0.65);
                border: none;
            }
        """)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(16)

        self._spinner = QProgressBar(self)
        self._spinner.setRange(0, 0)  # belirsiz ilerleme
        self._spinner.setMinimumWidth(120)
        self._spinner.setMaximumWidth(160)
        self._spinner.setFixedHeight(6)
        self._spinner.setTextVisible(False)
        self._spinner.setStyleSheet("""
            QProgressBar {
                border: none;
                border-radius: 3px;
                background-color: rgba(255,255,255,0.2);
            }
            QProgressBar::chunk {
                background-color: rgba(255,255,255,0.9);
                border-radius: 3px;
            }
        """)
        layout.addWidget(self._spinner, 0, Qt.AlignmentFlag.AlignHCenter)

        self._label = QLabel("Thumbnails hazırlanıyor…")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont(self._label.font())
        font.setPointSize(11)
        self._label.setFont(font)
        self._label.setStyleSheet("color: rgba(255,255,255,0.95);")
        layout.addWidget(self._label, 0, Qt.AlignmentFlag.AlignHCenter)

        self._progress_label = QLabel("")
        self._progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._progress_label.setStyleSheet("color: rgba(255,255,255,0.75); font-size: 10px;")
        layout.addWidget(self._progress_label, 0, Qt.AlignmentFlag.AlignHCenter)

    def show_overlay(self) -> None:
        self._progress_label.setText("0 / …")
        self.show()
        self.raise_()

    def hide_overlay(self) -> None:
        self.hide()

    def update_progress(self, ready_count: int, total_visible: int) -> None:
        if total_visible > 0:
            self._progress_label.setText(f"{ready_count} / {total_visible}")
            self._progress_label.repaint()
        if ready_count >= total_visible and total_visible > 0:
            self._progress_label.setText("")
