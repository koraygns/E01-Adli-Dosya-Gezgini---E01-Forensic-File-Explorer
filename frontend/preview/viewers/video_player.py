"""
Video oynatıcı: play/pause, seek, ses.
"""
from __future__ import annotations

import os
import tempfile
from typing import Any

from PyQt6.QtCore import Qt, QUrl, QSize, QPoint, QRect, QTimer
from PyQt6.QtGui import QKeyEvent, QPainter, QColor, QMouseEvent
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QHBoxLayout,
    QSlider, QFrame, QToolButton, QSizePolicy, QStyle,
    QApplication, QDialog, QFormLayout, QScrollArea, QDialogButtonBox,
)

from backend.engine.utils.cancel_token import CancellationToken

try:
    from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
    from PyQt6.QtMultimediaWidgets import QVideoWidget
    _HAS_QT_MEDIA = True
except ImportError:
    _HAS_QT_MEDIA = False

MAX_VIDEO_PREVIEW_READ = 400 * 1024 * 1024  # 400 MB
BG = "#000000"
SEEK_STEP_MS = 5000
VOLUME_STEP = 0.10


def _ms_to_str(ms: int) -> str:
    sec = max(0, ms // 1000)
    h, sec = sec // 3600, sec % 3600
    m, s = sec // 60, sec % 60
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


class CenterPlayButton(QWidget):
    """Ortada play/pause butonu."""
    clicked = None

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(88, 88)
        self._playing = False
        self._style = QApplication.style()

    def set_playing(self, playing: bool) -> None:
        self._playing = bool(playing)
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(0, 0, 0, 200))
        p.setPen(QColor(255, 255, 255, 70))
        p.drawEllipse(2, 2, self.width() - 4, self.height() - 4)
        icon = (
            self._style.standardIcon(QStyle.StandardPixmap.SP_MediaPause)
            if self._playing
            else self._style.standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
        )
        sz = 40
        x = (self.width() - sz) // 2 + (4 if not self._playing else 0)
        y = (self.height() - sz) // 2
        icon.paint(p, x, y, sz, sz)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.clicked:
            self.clicked()
            event.accept()
            return
        super().mousePressEvent(event)


class VideoPlayer(QWidget):
    """
    Basit yapı: video alanı (üstte ortada play butonu) + altta sabit kontrol çubuğu.
    Sol/Sağ ok controller'da önceki/sonraki dosya; Space/M/Up/Down video için.
    """

    def __init__(
        self,
        session: Any,
        item: dict[str, Any],
        cancel_token: CancellationToken,
        cache: Any,
    ):
        super().__init__()
        self.setStyleSheet(f"background: {BG};")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(320, 200)
        self._session = session
        self._item = item
        self._cancel = cancel_token
        self._cache = cache
        self._temp_path: str | None = None
        self._player: QMediaPlayer | None = None
        self._audio: QAudioOutput | None = None
        self._video_widget: QVideoWidget | None = None
        self._user_dragging_slider = False
        self._label: QLabel | None = None
        self._seek_slider: QSlider | None = None
        self._time_label: QLabel | None = None
        self._play_btn: QToolButton | None = None
        self._mute_btn: QToolButton | None = None
        self._center_btn: CenterPlayButton | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 1) Video alanı: video widget + üstünde ortada play butonu
        video_area = QWidget(self)
        video_area.setStyleSheet(f"background: {BG};")
        video_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        area_layout = QVBoxLayout(video_area)
        area_layout.setContentsMargins(0, 0, 0, 0)
        area_layout.setSpacing(0)

        self._label = QLabel("Yükleniyor…")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet("color: rgba(255,255,255,0.8); font-size: 15px;")
        if _HAS_QT_MEDIA:
            self._player = QMediaPlayer(self)
            self._audio = QAudioOutput(self)
            self._player.setAudioOutput(self._audio)
            self._video_widget = QVideoWidget(self)
            self._video_widget.setStyleSheet("background: #000; border: none;")
            self._video_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self._player.setVideoOutput(self._video_widget)
            area_layout.addWidget(self._video_widget, 1)
            self._video_widget.hide()
        area_layout.addWidget(self._label)

        # Ortada play butonu: video_area'nın üzerine yerleştirilecek (layout'tan sonra)
        self._center_btn = CenterPlayButton(video_area)
        self._center_btn.clicked = self.toggle_play
        self._center_btn.raise_()

        layout.addWidget(video_area, 1)

        # 2) Alt kontrol çubuğu (her zaman görünür)
        if _HAS_QT_MEDIA:
            self._build_bottom_bar(layout)
            self._load_video()
        else:
            self._label.setText("Video için PyQt6-Multimedia gerekli.")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # Ortadaki play butonunu video alanının tam ortasına koy
        if self._center_btn and self._center_btn.parent():
            p = self._center_btn.parent()
            x = (p.width() - self._center_btn.width()) // 2
            y = (p.height() - self._center_btn.height()) // 2
            self._center_btn.setGeometry(x, y, self._center_btn.width(), self._center_btn.height())

    def _build_bottom_bar(self, parent_layout: QVBoxLayout) -> None:
        bar = QFrame(self)
        bar.setObjectName("videoControls")
        bar.setFixedHeight(120)
        bar.setStyleSheet("""
            QFrame#videoControls {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(0,0,0,0.5), stop:1 rgba(0,0,0,0.95));
                border: none;
            }
            QFrame#videoControls QToolButton {
                background: transparent;
                color: #f0f0f0;
                border: none;
                min-width: 44px;
                min-height: 44px;
            }
            QFrame#videoControls QToolButton:hover { background: rgba(255,255,255,0.12); }
            QFrame#videoControls QLabel#timeLabel {
                color: rgba(255,255,255,0.95);
                font-size: 12px;
                font-family: Consolas, monospace;
                min-width: 90px;
            }
            QSlider::groove:horizontal { height: 5px; background: rgba(255,255,255,0.25); border-radius: 2px; }
            QSlider::handle:horizontal { width: 14px; height: 14px; margin: -5px 0;
                background: #fff; border-radius: 7px; }
            QSlider::sub-page:horizontal { background: rgba(255,255,255,0.5); border-radius: 2px; }
        """)
        vbox = QVBoxLayout(bar)
        vbox.setContentsMargins(20, 12, 20, 14)
        vbox.setSpacing(10)
        style = QApplication.style()

        seek_row = QHBoxLayout()
        seek_row.setSpacing(12)
        self._seek_slider = QSlider(Qt.Orientation.Horizontal)
        self._seek_slider.setMinimum(0)
        self._seek_slider.setMaximum(1000)
        self._seek_slider.setValue(0)
        self._seek_slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._seek_slider.sliderPressed.connect(self._on_slider_pressed)
        self._seek_slider.sliderMoved.connect(self._on_slider_moved)
        self._seek_slider.sliderReleased.connect(self._on_slider_released)
        seek_row.addWidget(self._seek_slider, 1)
        self._time_label = QLabel("0:00 / 0:00")
        self._time_label.setObjectName("timeLabel")
        self._time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        seek_row.addWidget(self._time_label)
        vbox.addLayout(seek_row)

        row = QHBoxLayout()
        row.setSpacing(2)
        for ico, tip, slot in [
            (QStyle.StandardPixmap.SP_MediaSeekBackward, "10 sn geri", self._seek_back10),
            (None, "Oynat/Duraklat", None),
            (QStyle.StandardPixmap.SP_MediaSeekForward, "10 sn ileri", self._seek_fwd10),
        ]:
            btn = QToolButton()
            if ico is not None:
                btn.setIcon(style.standardIcon(ico))
                btn.setIconSize(QSize(22, 22))
            btn.setToolTip(tip)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            if slot is not None:
                btn.clicked.connect(slot)
            else:
                self._play_btn = btn
                self._play_btn.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
                self._play_btn.setIconSize(QSize(26, 26))
                self._play_btn.clicked.connect(self.toggle_play)
            row.addWidget(btn)
        row.addSpacing(20)
        vol_down = QToolButton()
        vol_down.setText("−")
        vol_down.setToolTip("Ses kıs")
        vol_down.setCursor(Qt.CursorShape.PointingHandCursor)
        vol_down.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        vol_down.clicked.connect(self._volume_down)
        row.addWidget(vol_down)
        self._mute_btn = QToolButton()
        self._mute_btn.setText("🔇")
        self._mute_btn.setToolTip("Sustur")
        self._mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mute_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._mute_btn.clicked.connect(self._toggle_mute)
        row.addWidget(self._mute_btn)
        vol_up = QToolButton()
        vol_up.setText("+")
        vol_up.setToolTip("Ses aç")
        vol_up.setCursor(Qt.CursorShape.PointingHandCursor)
        vol_up.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        vol_up.clicked.connect(self._volume_up)
        row.addWidget(vol_up)
        row.addStretch(1)
        meta_btn = QToolButton()
        meta_btn.setText("Metadata")
        meta_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        meta_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        meta_btn.clicked.connect(self._show_metadata)
        row.addWidget(meta_btn)
        vbox.addLayout(row)
        parent_layout.addWidget(bar)

    def _on_slider_pressed(self) -> None:
        self._user_dragging_slider = True

    def _on_slider_moved(self, value: int) -> None:
        if not self._player or not self._time_label:
            return
        d = self._player.duration()
        if d > 0:
            pos = int((value / 1000.0) * d)
            self._player.setPosition(pos)
            self._time_label.setText(f"{_ms_to_str(pos)} / {_ms_to_str(d)}")

    def _on_slider_released(self) -> None:
        self._user_dragging_slider = False
        if self._player and self._seek_slider:
            d = self._player.duration()
            if d > 0:
                pos = int((self._seek_slider.value() / 1000.0) * d)
                self._player.setPosition(pos)

    def _update_slider_from_position(self) -> None:
        if not self._player or not self._seek_slider or self._user_dragging_slider:
            return
        d = self._player.duration()
        if d <= 0:
            return
        self._seek_slider.blockSignals(True)
        self._seek_slider.setValue(int(1000 * self._player.position() / d))
        self._seek_slider.blockSignals(False)
        self._update_time_labels()

    def _update_time_labels(self) -> None:
        if not self._player or not self._time_label:
            return
        cur = _ms_to_str(self._player.position())
        total = _ms_to_str(self._player.duration())
        self._time_label.setText(f"{cur} / {total}")

    def _seek_back10(self) -> None:
        if self._player:
            self._player.setPosition(max(0, self._player.position() - 10_000))

    def _seek_fwd10(self) -> None:
        if self._player:
            d = self._player.duration()
            self._player.setPosition(min(d, self._player.position() + 10_000))

    def _volume_up(self) -> None:
        if self._audio:
            self._audio.setVolume(min(1.0, self._audio.volume() + VOLUME_STEP))

    def _volume_down(self) -> None:
        if self._audio:
            self._audio.setVolume(max(0.0, self._audio.volume() - VOLUME_STEP))

    def _toggle_mute(self) -> None:
        if self._audio:
            self._audio.setMuted(not self._audio.isMuted())
            self._mute_btn.setText("🔊" if self._audio.isMuted() else "🔇")

    def _show_metadata(self) -> None:
        inode = self._item.get("inode")
        name = self._item.get("name") or ""
        meta = self._session.get_metadata(int(inode), name) if inode is not None else {}
        meta = meta or {}
        meta.setdefault("name", name)
        meta.setdefault("inode", inode)
        meta.setdefault("size", self._item.get("size"))
        meta.setdefault("type", "Directory" if self._item.get("is_dir") else "File")
        for k in ("mtime", "atime", "ctime", "crtime"):
            if k not in meta and self._item.get(k) is not None:
                meta[k] = self._item.get(k)
        d = QDialog(self)
        d.setWindowTitle("Metadata")
        d.setMinimumSize(340, 220)
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

    def _load_video(self) -> None:
        if not _HAS_QT_MEDIA or not self._player or not self._video_widget:
            return
        inode = self._item.get("inode")
        if inode is None:
            self._label.setText("Dosya açılamadı.")
            return
        try:
            size = int(self._item.get("size") or 0)
            max_read = min(size, MAX_VIDEO_PREVIEW_READ) if size > 0 else MAX_VIDEO_PREVIEW_READ
        except (TypeError, ValueError):
            max_read = MAX_VIDEO_PREVIEW_READ
        data = self._session.read_file_content(inode, offset=0, max_size=max_read)
        if not data or self._cancel.is_cancelled():
            self._label.setText("Video okunamadı veya iptal edildi.")
            return
        root = self._cache.get_cache_root(self._session)
        ext = os.path.splitext(self._item.get("name") or "")[1] or ".mp4"
        fd, self._temp_path = tempfile.mkstemp(suffix=ext, prefix="preview_video_", dir=root)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
        self._label.hide()
        self._video_widget.show()
        self._player.positionChanged.connect(self._update_slider_from_position)
        self._player.durationChanged.connect(self._update_slider_from_position)
        self._player.durationChanged.connect(self._update_time_labels)
        self._player.playbackStateChanged.connect(self._on_playback_state_changed)
        self._player.setSource(QUrl.fromLocalFile(self._temp_path))
        self._player.play()
        if self._center_btn:
            self._center_btn.set_playing(True)

    def _on_playback_state_changed(self, state) -> None:
        style = QApplication.style()
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        if self._center_btn:
            self._center_btn.set_playing(playing)
        if self._play_btn:
            self._play_btn.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaPause if playing else QStyle.StandardPixmap.SP_MediaPlay))

    def toggle_play(self) -> None:
        if not self._player:
            return
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def is_click_on_media_content(self, global_pos: QPoint) -> bool:
        if not self._video_widget:
            return False
        r = QRect(self._video_widget.mapToGlobal(QPoint(0, 0)), self._video_widget.size())
        return r.contains(global_pos)

    def handle_key(self, event: QKeyEvent) -> bool:
        """Video klavye kontrolü."""
        key = event.key()
        if key == Qt.Key.Key_Space:
            self.toggle_play()
            return True
        if key == Qt.Key.Key_M:
            self._toggle_mute()
            return True
        if key == Qt.Key.Key_Up:
            self._volume_up()
            return True
        if key == Qt.Key.Key_Down:
            self._volume_down()
            return True
        if key == Qt.Key.Key_J:
            self._seek_back10()
            return True
        if key == Qt.Key.Key_L:
            self._seek_fwd10()
            return True
        return False

    def on_preview_close(self) -> None:
        if self._player:
            self._player.stop()
        if self._temp_path and os.path.isfile(self._temp_path):
            try:
                os.unlink(self._temp_path)
            except OSError:
                pass
            self._temp_path = None

    def closeEvent(self, event) -> None:
        self.on_preview_close()
        super().closeEvent(event)
