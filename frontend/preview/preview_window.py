"""
Tam ekran önizleme penceresi.
"""
from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QStackedWidget, QLabel, QFrame,
    QApplication, QAbstractButton, QSlider, QLineEdit,
)
from PyQt6.QtGui import QKeyEvent, QShortcut, QKeySequence, QMouseEvent

if TYPE_CHECKING:
    from frontend.preview.preview_controller import PreviewController


class PreviewWindow(QMainWindow):
    """Tam ekran önizleme, klavye controller'a iletilir."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Önizleme")
        self._controller: PreviewController | None = None
        self.setObjectName("previewWindow")
        self.setStyleSheet("#previewWindow { background-color: #0a0a0a; }")
        self._stack = QStackedWidget(self)
        self._stack.setStyleSheet("background: transparent;")
        self._placeholder = QWidget(self)
        self._placeholder.setStyleSheet("background: transparent;")
        self._placeholder_layout = QVBoxLayout(self._placeholder)
        self._placeholder_label = QLabel("Yükleniyor…")
        self._placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder_label.setStyleSheet("color: rgba(255,255,255,0.9); font-size: 14px;")
        self._placeholder_layout.addWidget(self._placeholder_label)
        self._stack.addWidget(self._placeholder)
        self.setCentralWidget(self._stack)
        self.setWindowState(self.windowState() | Qt.WindowState.WindowFullScreen)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if sys.platform == "win32":
            self._try_windows_blur()

    def _try_windows_blur(self) -> None:
        """Windows blur efekti dene."""
        try:
            import ctypes
            from ctypes import wintypes
            HWND = ctypes.c_void_p
            user32 = ctypes.windll.user32
            dwm = ctypes.windll.dwmapi
            hwnd = HWND(int(self.winId()))
            WCA_ACCENT_POLICY = 19
            ACCENT_ENABLE_ACRYLICBLURBEHIND = 4
            class ACCENT_POLICY(ctypes.Structure):
                _fields_ = [("AccentState", wintypes.DWORD), ("AccentFlags", wintypes.DWORD),
                            ("GradientColor", wintypes.DWORD), ("AnimationId", wintypes.DWORD)]
            class WINDOWCOMPOSITIONATTRIBDATA(ctypes.Structure):
                _fields_ = [("Attribute", wintypes.DWORD), ("Data", ctypes.POINTER(ACCENT_POLICY)), ("SizeOfData", wintypes.ULONG)]
            policy = ACCENT_POLICY(AccentState=ACCENT_ENABLE_ACRYLICBLURBEHIND, AccentFlags=0, GradientColor=0x00000000, AnimationId=0)
            data = WINDOWCOMPOSITIONATTRIBDATA(Attribute=WCA_ACCENT_POLICY, Data=ctypes.pointer(policy), SizeOfData=ctypes.sizeof(ACCENT_POLICY))
            SetWindowCompositionAttribute = user32.SetWindowCompositionAttribute
            SetWindowCompositionAttribute.argtypes = [wintypes.HWND, ctypes.POINTER(WINDOWCOMPOSITIONATTRIBDATA)]
            SetWindowCompositionAttribute.restype = wintypes.BOOL
            if SetWindowCompositionAttribute(hwnd, ctypes.byref(data)):
                pass
        except Exception:
            pass

    def show_placeholder(self, text: str = "Yükleniyor…") -> None:
        self._placeholder_label.setText(text)
        self._stack.setCurrentWidget(self._placeholder)

    def set_controller(self, controller: PreviewController) -> None:
        self._controller = controller
        ctx = Qt.ShortcutContext.WindowShortcut
        QShortcut(QKeySequence("Escape"), self, controller.close_preview, context=ctx)
        QShortcut(QKeySequence("Left"), self, controller.go_prev, context=ctx)
        QShortcut(QKeySequence("Right"), self, controller.go_next, context=ctx)
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, watched: QWidget, event: QEvent) -> bool:
        """Klavye: önizleme penceresindeyken tuşları controller'a ilet. Tıklama: koyu alana tıklanınca kapat."""
        if not isinstance(watched, QWidget):
            return False
        # Klavye: odak child'da olsa bile Space/M/J/L/Up/Down vb. controller → viewer'a gitsin
        if (
            event.type() == QEvent.Type.KeyPress
            and isinstance(event, QKeyEvent)
            and self._controller
            and self.isVisible()
            and self.isActiveWindow()
            and (watched == self or self.isAncestorOf(watched))
        ):
            if self._controller.handle_key(event):
                return True
        if (
            event.type() == QEvent.Type.MouseButtonPress
            and isinstance(event, QMouseEvent)
            and event.button() == Qt.MouseButton.LeftButton
            and self._controller
            and (self.isAncestorOf(watched) or watched == self)
        ):
            w = QApplication.widgetAt(event.globalPosition().toPoint())
            if w is None:
                self._controller.close_preview()
                return True
            if not self.isAncestorOf(w) and w != self:
                return False
            current = w
            while current and current != self:
                if isinstance(current, (QAbstractButton, QSlider, QLineEdit)):
                    return False
                if isinstance(current, QFrame) and current.objectName() in ("videoToolbar", "previewToolbar", "documentToolbar"):
                    return False
                if isinstance(current, QWidget) and current.objectName() == "videoControlsOverlay":
                    return False
                current = current.parentWidget()
            viewer = self._stack.currentWidget()
            if viewer is not None and callable(getattr(viewer, "is_click_on_media_content", None)):
                if viewer.is_click_on_media_content(event.globalPosition().toPoint()):
                    return False
            self._controller.close_preview()
            return True
        return False

    def set_placeholder_text(self, text: str) -> None:
        self._placeholder_label.setText(text)

    def set_viewer_widget(self, widget: QWidget) -> None:
        """Viewer widget'ını değiştir."""
        while self._stack.count() > 1:
            w = self._stack.widget(1)
            self._stack.removeWidget(w)
            w.deleteLater()
        self._stack.addWidget(widget)
        self._stack.setCurrentWidget(widget)
        self.activateWindow()
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def show_error_banner(self, message: str) -> None:
        """Hata mesajı göster."""
        self.statusBar().showMessage(message, 5000)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._controller and self._controller.handle_key(event):
            event.accept()
            return
        super().keyPressEvent(event)
