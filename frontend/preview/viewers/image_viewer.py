"""
Resim görüntüleyici: zoom, pan, döndürme.
"""
from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt, QTimer, QPointF, QPoint
from PyQt6.QtGui import QPixmap, QKeyEvent, QPainter
from PyQt6.QtWidgets import (
    QWidget, QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
    QVBoxLayout, QHBoxLayout, QPushButton, QFrame, QDialog, QFormLayout,
    QLabel, QScrollArea, QDialogButtonBox,
)
from backend.engine.utils.cancel_token import CancellationToken

# Toolbar stili
TOOLBAR_STYLE = """
    QFrame#previewToolbar {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 rgba(0,0,0,0.5), stop:1 rgba(0,0,0,0.95));
        border: none;
        min-height: 52px;
    }
    QPushButton {
        background-color: rgba(45,45,48,0.9);
        color: #f0f0f0;
        border: 1px solid rgba(255,255,255,0.12);
        padding: 10px 18px;
        font-size: 13px;
        border-radius: 4px;
    }
    QPushButton:hover { background-color: rgba(56,56,60,0.95); }
    QPushButton:pressed { background-color: rgba(37,37,40,0.95); }
"""
FILENAME_BAR_STYLE = """
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(0,0,0,0.7), stop:1 transparent);
    color: rgba(255,255,255,0.95);
    padding: 12px 24px;
    font-size: 14px;
    border: none;
"""


class ImageViewer(QWidget):
    """
    Resim: tam ekrana sığdır, her zaman merkez odaklı; zoom/pan akıcı.
    Alt ortada şeffaf buton çubuğu.
    """

    def __init__(
        self,
        session: Any,
        item: dict[str, Any],
        cancel_token: CancellationToken,
        cache: Any,
    ):
        super().__init__()
        self.setStyleSheet("background: #0a0a0a;")
        self._session = session
        self._item = item
        self._cancel = cancel_token
        self._cache = cache
        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._fit_mode = True
        self._scene = QGraphicsScene(self)
        self._view = QGraphicsView(self)
        self._view.setStyleSheet("background: transparent; border: none;")
        self._view.setScene(self._scene)
        self._view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self._view.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self._view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._view.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._view.setFrameShape(QFrame.Shape.NoFrame)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 20)
        layout.setSpacing(0)
        self._filename_label = QLabel(self._item.get("name") or "—")
        self._filename_label.setStyleSheet(FILENAME_BAR_STYLE)
        self._filename_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._filename_label)
        layout.addWidget(self._view, 1)
        toolbar_frame = QFrame(self)
        toolbar_frame.setObjectName("previewToolbar")
        toolbar_frame.setStyleSheet(TOOLBAR_STYLE)
        toolbar_inner = QHBoxLayout(toolbar_frame)
        toolbar_inner.setContentsMargins(16, 10, 16, 10)
        toolbar_inner.setSpacing(10)
        toolbar_inner.addStretch()
        for label, slot in [
            ("Yakınlaştır", self._view_zoom_in),
            ("Uzaklaştır", self._view_zoom_out),
            ("Sola Döndür", self._view_rotate_left),
            ("Sağa Döndür", self._view_rotate_right),
            ("Ekrana Sığdır", self._view_fit),
            ("Metadata", self._show_metadata),
        ]:
            btn = QPushButton(label)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(slot)
            toolbar_inner.addWidget(btn)
        toolbar_inner.addStretch()
        layout.addWidget(toolbar_frame, 0, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)
        self._load_image()

    def _view_zoom_in(self) -> None:
        self._view.scale(1.25, 1.25)
        self._fit_mode = False

    def _view_zoom_out(self) -> None:
        self._view.scale(0.8, 0.8)
        self._fit_mode = False

    def _view_rotate_left(self) -> None:
        if self._pixmap_item:
            self._pixmap_item.setRotation(self._pixmap_item.rotation() - 90)
            self._scene.setSceneRect(self._scene.itemsBoundingRect())
            self._view.centerOn(self._pixmap_item)
        if self._fit_mode:
            QTimer.singleShot(10, self._do_fit)

    def _view_rotate_right(self) -> None:
        if self._pixmap_item:
            self._pixmap_item.setRotation(self._pixmap_item.rotation() + 90)
            self._scene.setSceneRect(self._scene.itemsBoundingRect())
            self._view.centerOn(self._pixmap_item)
        if self._fit_mode:
            QTimer.singleShot(10, self._do_fit)

    def _view_fit(self) -> None:
        self._fit_mode = True
        self._do_fit()

    def _view_actual(self) -> None:
        self._fit_mode = False
        self._view.resetTransform()
        if self._pixmap_item:
            self._pixmap_item.setRotation(0)

    def _show_metadata(self) -> None:
        inode = self._item.get("inode")
        name = self._item.get("name") or ""
        meta = None
        if inode is not None:
            meta = self._session.get_metadata(int(inode), name)
        if not meta:
            meta = {}
        meta.setdefault("name", name)
        meta.setdefault("inode", inode)
        meta.setdefault("size", self._item.get("size"))
        meta.setdefault("type", "Directory" if self._item.get("is_dir") else "File")
        for k in ("mtime", "atime", "ctime", "crtime"):
            if k not in meta and self._item.get(k) is not None:
                meta[k] = self._item.get(k)
        d = QDialog(self)
        d.setWindowTitle("Metadata")
        d.setMinimumSize(320, 200)
        d.setStyleSheet("""
            QDialog { background-color: #1a1a1c; }
            QLabel { color: #e8e8ea; }
            QPushButton { background-color: #2d2d30; color: #f0f0f0; border: 1px solid #3d3d40; padding: 8px 16px; }
            QPushButton:hover { background-color: #38383c; }
        """)
        layout = QVBoxLayout(d)
        form = QFormLayout()
        for key, value in meta.items():
            form.addRow(QLabel(str(key) + ":"), QLabel(str(value) if value is not None else "—"))
        if not meta:
            form.addRow(QLabel("—"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner.setLayout(form)
        scroll.setWidget(inner)
        scroll.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(scroll)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.rejected.connect(d.reject)
        layout.addWidget(box)
        d.exec()

    def _do_fit(self) -> None:
        if self._pixmap_item:
            self._view.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)

    def is_click_on_media_content(self, global_pos: QPoint) -> bool:
        """Tıklama resim üzerinde mi."""
        if not self._pixmap_item:
            return False
        view_pos = self._view.mapFromGlobal(global_pos)
        if not self._view.rect().contains(view_pos):
            return False
        scene_pos = self._view.mapToScene(view_pos)
        # Viewport-scene dönüşümü
        vp_t = self._view.viewportTransform()
        device_tf = vp_t.inverted()[0] if isinstance(vp_t.inverted(), tuple) else vp_t.inverted()
        item = self._scene.itemAt(scene_pos, device_tf)
        return item is self._pixmap_item or (item and item.parentItem() is self._pixmap_item)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(50, self._do_fit)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._fit_mode and self._pixmap_item:
            self._do_fit()

    def _load_image(self) -> None:
        inode = self._item.get("inode")
        if inode is None:
            return
        data = self._session.read_file_content(inode, offset=0, max_size=10 * 1024 * 1024)
        if not data or self._cancel.is_cancelled():
            return
        try:
            from PIL import Image
            import io
            from PyQt6.QtGui import QImage
            img = Image.open(io.BytesIO(data))
            img = img.convert("RGB")
            if img.mode == "RGB":
                h, w = img.height, img.width
                buf = img.tobytes("raw", "RGB")
                qimg = QImage(buf, w, h, QImage.Format.Format_RGB888)
            else:
                qimg = QImage()
            if not qimg.isNull():
                pix = QPixmap.fromImage(qimg)
                self._pixmap_item = self._scene.addPixmap(pix)
                self._pixmap_item.setTransformOriginPoint(QPointF(pix.width() / 2.0, pix.height() / 2.0))
                self._scene.setSceneRect(pix.rect())
                self._fit_mode = True
                QTimer.singleShot(0, self._do_fit)
                QTimer.singleShot(80, self._do_fit)
        except Exception:
            pass

    def toggle_fit(self) -> None:
        self._fit_mode = not self._fit_mode
        if self._fit_mode:
            self._do_fit()
        else:
            self._view.resetTransform()

    def zoom_in(self) -> None:
        self._view_zoom_in()

    def zoom_out(self) -> None:
        self._view_zoom_out()

    def fit_to_screen(self) -> None:
        self._view_fit()

    def actual_size(self) -> None:
        self._view_actual()

    def rotate_right(self) -> None:
        self._view_rotate_right()

    def rotate_left(self) -> None:
        self._view_rotate_left()

    def handle_key(self, event: QKeyEvent) -> bool:
        key = event.key()
        if key == Qt.Key.Key_Space:
            self.toggle_fit()
            return True
        if key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.zoom_in()
            return True
        if key == Qt.Key.Key_Minus:
            self.zoom_out()
            return True
        if key == Qt.Key.Key_0:
            self.fit_to_screen()
            return True
        if key == Qt.Key.Key_1:
            self.actual_size()
            return True
        if key == Qt.Key.Key_R:
            self.rotate_right()
            return True
        if key == Qt.Key.Key_L:
            self.rotate_left()
            return True
        return False
