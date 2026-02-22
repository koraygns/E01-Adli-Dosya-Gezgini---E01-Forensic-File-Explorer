"""
Önizleme kontrolü: aç/kapa, gezinme, klavye.
"""
from __future__ import annotations

from typing import Any, Callable

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QWidget

from backend.engine.utils.cancel_token import CancellationToken
from frontend.preview.collection_model import CollectionModel
from frontend.preview.media_router import MediaRouter, ViewerType
from frontend.preview.cache_layer import CacheLayer
from frontend.preview.preview_window import PreviewWindow


class PreviewController:
    """Tam ekran önizleme kontrolü."""

    def __init__(
        self,
        session: Any,
        case_dir: str,
        evidence_id: str,
        parent_widget: QWidget | None = None,
    ):
        self.session = session
        self.case_dir = case_dir
        self.evidence_id = evidence_id
        self.parent_widget = parent_widget
        self.cache = CacheLayer(case_dir, evidence_id)
        self._collection: CollectionModel | None = None
        self._window: PreviewWindow | None = None
        self._current_viewer: QWidget | None = None
        self._cancel_token = CancellationToken()
        self._prefetch_timer = QTimer()
        self._prefetch_timer.setSingleShot(True)
        self._prefetch_timer.setInterval(100)
        self._prefetch_timer.timeout.connect(self._do_prefetch)
        self._on_tag_request: Callable[[int, str], None] | None = None
        self._on_preview_close: Callable[[int], None] | None = None

    def set_on_preview_close(self, callback: Callable[[int], None] | None) -> None:
        """Esc ile kapanınca callback."""
        self._on_preview_close = callback

    def set_collection(self, collection: CollectionModel) -> None:
        self._collection = collection

    def open_at_index(self, index: int) -> None:
        """İndeksteki öğeyi önizlemede aç."""
        if self._collection is None:
            return
        self._cancel_token.cancel()
        self._cancel_token = CancellationToken()
        self._collection.jump_to(index)
        if self._window is None:
            self._window = PreviewWindow(self.parent_widget)
            self._window.set_controller(self)
        self._window.show()
        self._load_current_item()
        self._schedule_prefetch()

    def close_preview(self) -> None:
        current_index = self._collection.current_index if self._collection else 0
        self._cancel_token.cancel()
        if self._current_viewer is not None and hasattr(self._current_viewer, "on_preview_close"):
            try:
                self._current_viewer.on_preview_close()
            except Exception:
                pass
        if self._window:
            self._window.close()
            self._window = None
        self._current_viewer = None
        if self._on_preview_close is not None:
            try:
                self._on_preview_close(current_index)
            except Exception:
                pass

    def _load_current_item(self) -> None:
        item = self._collection.get_current() if self._collection else None
        if not item:
            self._show_placeholder("Öğe yok")
            return
        viewer_type = MediaRouter.route(item)
        viewer = self._create_viewer(viewer_type, item)
        if viewer:
            if self._window:
                self._window.set_viewer_widget(viewer)
            self._current_viewer = viewer
        else:
            self._show_placeholder("Bu dosya türü için önizleyici yok")

    def _create_viewer(self, viewer_type: ViewerType, item: dict[str, Any]) -> QWidget | None:
        """Uygun viewer widget'ını oluştur."""
        if viewer_type == ViewerType.IMAGE:
            from frontend.preview.viewers.image_viewer import ImageViewer
            return ImageViewer(self.session, item, self._cancel_token, self.cache)
        if viewer_type == ViewerType.VIDEO:
            from frontend.preview.viewers.video_player import VideoPlayer
            return VideoPlayer(self.session, item, self._cancel_token, self.cache)
        if viewer_type in (ViewerType.PDF, ViewerType.TXT, ViewerType.OFFICE):
            from frontend.preview.viewers.document_viewer import DocumentViewer
            return DocumentViewer(self.session, item, viewer_type, self._cancel_token, self.cache)
        from frontend.preview.viewers.placeholder_viewer import PlaceholderViewer
        return PlaceholderViewer(item)

    def _show_placeholder(self, text: str) -> None:
        if self._window:
            self._window.show_placeholder(text)

    def _schedule_prefetch(self) -> None:
        self._prefetch_timer.stop()
        self._prefetch_timer.start()

    def _do_prefetch(self) -> None:
        """Sonraki/önceki için ön yükleme."""
        if not self._collection or self._cancel_token.is_cancelled():
            return
        curr = self._collection.get_current()
        if not curr:
            return
        ni = self._collection.next_index()
        pi = self._collection.prev_index()
        if ni is not None:
            next_item = self._collection.get_item_at(ni)
            if next_item:
                self._prefetch_item(next_item)
        if pi is not None:
            prev_item = self._collection.get_item_at(pi)
            if prev_item:
                self._prefetch_item(prev_item)

    def _prefetch_item(self, item: dict[str, Any]) -> None:
        """Prefetch genişletmek için."""
        pass

    def go_prev(self) -> None:
        """Klavye Sol ok: önceki öğe (QShortcut ile odaktan bağımsız)."""
        if self._collection is None:
            return
        if self._collection.prev() is not None:
            self._cancel_token.cancel()
            self._cancel_token = CancellationToken()
            self._load_current_item()
            self._schedule_prefetch()

    def go_next(self) -> None:
        """Klavye Sağ ok: sonraki öğe (QShortcut ile odaktan bağımsız)."""
        if self._collection is None:
            return
        if self._collection.next() is not None:
            self._cancel_token.cancel()
            self._cancel_token = CancellationToken()
            self._load_current_item()
            self._schedule_prefetch()

    def handle_key(self, event: QKeyEvent) -> bool:
        """
        Klavye: Esc, F, Space/M/J/L/Up/Down (viewer). Sol/Sağ = QShortcut ile go_prev/go_next.
        Ctrl+F önizleyiciye bırakılır (belge içi arama).
        """
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.close_preview()
            return True
        if key == Qt.Key.Key_F and (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            return False
        if key == Qt.Key.Key_F and self._window is not None:
            self._toggle_fullscreen()
            return True
        if self._current_viewer is not None and hasattr(self._current_viewer, "handle_key"):
            if self._current_viewer.handle_key(event):
                return True
        return False

    def _toggle_fullscreen(self) -> None:
        if self._window is None:
            return
        if self._window.windowState() & Qt.WindowState.WindowFullScreen:
            self._window.setWindowState(Qt.WindowState.WindowNoState)
        else:
            self._window.setWindowState(self._window.windowState() | Qt.WindowState.WindowFullScreen)
