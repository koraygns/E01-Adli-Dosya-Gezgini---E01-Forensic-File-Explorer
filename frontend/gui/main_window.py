from PyQt6.QtWidgets import (
    QMainWindow, QPushButton, QFileDialog, QTextEdit,
    QVBoxLayout, QHBoxLayout, QWidget, QTreeView, QSplitter, QApplication,
    QGroupBox, QFormLayout, QLabel, QScrollArea, QToolBar, QLineEdit,
    QTableView, QHeaderView, QSizePolicy, QListView,
    QStackedWidget, QComboBox, QStyle, QFrame, QMenuBar, QMenu, QDialog,
    QDialogButtonBox, QAbstractItemView, QMessageBox, QCheckBox, QStyleOptionViewItem,
    QProxyStyle, QTabWidget, QTabBar,     QColorDialog, QKeySequenceEdit, QListWidget,
    QListWidgetItem, QInputDialog, QStyledItemDelegate, QProgressBar,
)
from PyQt6.QtGui import (
    QStandardItemModel, QStandardItem, QAction, QIcon, QPixmap, QColor, QPalette,
    QPainter, QPen, QBrush, QFont, QPolygon, QFontMetrics, QKeyEvent, QTextDocument,
)
from PyQt6.QtCore import pyqtSignal, QObject, Qt, QTimer, QModelIndex, QSize, QEvent, QRect, QPoint, QSettings
from PyQt6.QtGui import QKeySequence, QShortcut
import threading
import os
import json
import csv
import html
import traceback
from datetime import datetime

from PyQt6.QtPrintSupport import QPrinter

from frontend.gui.explorer_models import FileListTableModel, _extension_from_name
from frontend.gui.overlay_widget import ThumbnailOverlayWidget
from frontend.gui import tag_manager
from backend.engine.file_category import FileCategory, categorize_node
from backend.engine.thumbnail.warmup import warmup_thumbnails_inode, WARMUP_COUNT_DEFAULT
from backend.engine.utils.cancel_token import CancellationToken

INODE_ROLE = Qt.ItemDataRole.UserRole
IS_DIR_ROLE = Qt.ItemDataRole.UserRole + 1
# Sanal ağaç düğümleri (navigasyon yapılmaz)
TREE_INODE_E01 = -2
TREE_INODE_PARTITION = -3
TREE_INODE_VOLUME = -4
WARMUP_DEBOUNCE_MS = 150
WARMUP_SAFETY_MS = 6000  # Overlay max 6 sn
VISIBLE_THUMB_BUFFER = 24   # Görünür alan üst/alt buffer
VISIBLE_THUMB_MAX_PER_REQUEST = 80  # Seferde max thumbnail isteği
PLACEHOLDER_TEXT = "..."
REPORT_EXTRACT_MAX_BYTES = 512 * 1024 * 1024  # Rapor dosya çıkarma limiti (512 MB)

# Tema renkleri (tek kaynak)
DESIGN_TOKENS = {
    "bg_main": "#f4f6fa",
    "bg_panel": "#ffffff",
    "bg_elevated": "#eef2f7",
    "grid_row": "#ffffff",
    "grid_row_alt": "#f5f7fb",
    "grid_hover": "#e9f0ff",
    "grid_selected": "#dbe7ff",
    "grid_selected_glow_alpha": 0,
    "header_bg": "#f1f4f9",
    "sidebar_bg": "#eef2f7",
    "inspector_bg": "#f8fafc",
    "border_subtle": "#e2e8f0",
    "border_separator": "#e6ebf2",
    "text_primary": "#1f2937",
    "text_muted": "#6b7280",
    "text_dim": "#9ca3af",
    "accent": "#3b82f6",
    "accent_soft": "#e0ebff",
    "danger_soft": "#fdeaea",
    "danger_text": "#c0392b",
    "toolbar_top": "#f8fafc",
    "toolbar_bottom": "#eef2f7",
    "log_bg": "#ffffff",
    "log_text": "#374151",
    "log_warning": "#b45309",
    "log_error": "#b91c1c",
    "sidebar_hover": "#e8f0fe",
    "scrollbar_bg": "#f1f5f9",
    "scrollbar_handle": "#cbd5e1",
    "scrollbar_handle_hover": "#94a3b8",
    "grid_style_bg": "#ffffff",
    "grid_style_alt": "#f6f8fb",
    "grid_style_selection": "#dbeafe",
    "grid_style_hover": "#eef4ff",
    "grid_style_text": "#1f2937",
    "grid_style_header": "#f1f5f9",
    "grid_style_border": "#e5e7eb",
}

def _hex_to_qcolor(hex_str: str) -> QColor:
    h = hex_str.lstrip("#")
    if len(h) == 6:
        return QColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    return QColor(0, 0, 0)


class KeyCaptureDialog(QDialog):
    """Kısayol tuşu seçimi."""
    def __init__(self, parent=None, current_key: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Kısayol tuşu")
        self._key_sequence = current_key or ""
        ly = QVBoxLayout(self)
        t = DESIGN_TOKENS
        self._label = QLabel("Atamak istediğiniz tuşa basın\n(F1, F2, Ctrl+1, vb.)")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet(f"color: {t['text_primary']}; font-size: 13px; padding: 20px;")
        ly.addWidget(self._label)
        self._key_label = QLabel(current_key or "—")
        self._key_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._key_label.setStyleSheet(f"font-weight: bold; color: {t['accent']}; font-size: 15px;")
        ly.addWidget(self._key_label)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumWidth(280)

    def showEvent(self, event):
        super().showEvent(event)
        self.setFocus(Qt.FocusReason.PopupFocusReason)

    def keyPressEvent(self, event: QKeyEvent):
        # Olayı kabul et (sistem kısayolları tetiklenmesin)
        event.accept()
        key = event.key()
        mods = event.modifiers()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Escape):
            if key == Qt.Key.Key_Escape:
                self.reject()
            return
        # Alt+F4 gibi atanmasın
        if key == Qt.Key.Key_F4 and (mods & Qt.KeyboardModifier.AltModifier):
            self._key_label.setText("(Atanamaz: Alt+F4)")
            return
        if key == Qt.Key.Key_Q and (mods & Qt.KeyboardModifier.ControlModifier):
            self._key_label.setText("(Başka tuş deneyin)")
            return
        try:
            parts = []
            if mods & Qt.KeyboardModifier.ControlModifier:
                parts.append("Ctrl+")
            if mods & Qt.KeyboardModifier.AltModifier:
                parts.append("Alt+")
            if mods & Qt.KeyboardModifier.ShiftModifier:
                parts.append("Shift+")
            if mods & Qt.KeyboardModifier.MetaModifier:
                parts.append("Meta+")
            key_only = QKeySequence(key).toString()
            if key_only:
                parts.append(key_only)
            self._key_sequence = "".join(parts)
            if not self._key_sequence:
                return
            self._key_label.setText(self._key_sequence)
            self.accept()
        except Exception:
            self._key_label.setText("—")
            self.reject()

    def get_key_sequence(self) -> str:
        return self._key_sequence or ""


class TagBarDelegate(QStyledItemDelegate):
    """Tablo sütununda etiket rengi çubuğu."""
    TAG_BAR_WIDTH = 5

    def __init__(self, get_color_fn, table_model, parent=None):
        super().__init__(parent)
        self._get_color = get_color_fn
        self._model = table_model

    def paint(self, painter, option, index):
        if self._model and 0 <= index.row() < self._model.rowCount():
            node = self._model.get_node_at(index.row())
            inode = node.get("inode") if node else None
            color = self._get_color(inode) if inode is not None and self._get_color else None
            if color:
                rect = option.rect
                bar = QRect(rect.left(), rect.top(), self.TAG_BAR_WIDTH, rect.height())
                painter.fillRect(bar, QColor(color))
        option_copy = option
        option_copy.rect = option.rect.adjusted(self.TAG_BAR_WIDTH, 0, 0, 0)
        super().paint(painter, option_copy, index)


class ListViewTagDelegate(QStyledItemDelegate):
    """Büyük simge listesinde etiket rengi çubuğu."""
    TAG_BAR_WIDTH = 4

    def __init__(self, get_color_fn, parent=None):
        super().__init__(parent)
        self._get_color = get_color_fn

    def paint(self, painter, option, index):
        inode = index.data(INODE_ROLE) if index.isValid() else None
        color = self._get_color(inode) if inode is not None and self._get_color else None
        if color:
            rect = option.rect
            bar = QRect(rect.left(), rect.top(), self.TAG_BAR_WIDTH, rect.height())
            painter.fillRect(bar, QColor(color))
        opt = option
        opt.rect = option.rect.adjusted(self.TAG_BAR_WIDTH, 0, 0, 0)
        super().paint(painter, opt, index)


class VerticalMetaTabWidget(QWidget):
    """Meta veri paneli dikey sekmesi."""
    clicked = pyqtSignal()

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self._text = text
        self._hover = False
        self.setFixedWidth(48)
        self.setMinimumHeight(100)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Meta veri panelini aç / kapat")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def enterEvent(self, event):
        self._hover = True
        self.update()

    def leaveEvent(self, event):
        self._hover = False
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, event):
        t = DESIGN_TOKENS
        bg = t["accent_soft"] if self._hover else t["inspector_bg"]
        color = t["accent"] if self._hover else t["text_primary"]
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(bg))
        painter.setPen(QPen(QColor(t["border_subtle"]), 1))
        painter.drawLine(self.rect().right(), 0, self.rect().right(), self.rect().height())
        painter.setPen(QColor(color))
        font = QFont(self.font().family(), 9, QFont.Weight.DemiBold)
        painter.setFont(font)
        fm = QFontMetrics(font)
        w, h = self.rect().width(), self.rect().height()
        tw = fm.horizontalAdvance(self._text)
        center_x = w // 2
        # Dikey metin: tüm alanda ortada
        painter.save()
        painter.translate(center_x, (h + tw) / 2)
        painter.rotate(-90)
        painter.drawText(-tw // 2, 0, self._text)
        painter.restore()


# Ağaç girintisi
TREE_INDENT = 18

SIDEBAR_TREE_OBJECT_NAME = "sidebarTree"


class SidebarTreeProxyStyle(QProxyStyle):
    """Ağaç branch alanı gizli."""

    def subElementRect(self, element, option, widget):
        if (
            element == QStyle.SubElement.SE_TreeViewDisclosureItem
            and widget
            and getattr(widget, "objectName", lambda: "")() == SIDEBAR_TREE_OBJECT_NAME
        ):
            return QRect(0, 0, 0, 0)
        return super().subElementRect(element, option, widget)


class SidebarTreeView(QTreeView):
    """Ağaç görünümü, sadece girinti."""

    def drawBranches(self, painter, rect, index):
        # Branch alanını doldur
        bg = self.palette().color(self.backgroundRole())
        painter.fillRect(rect, bg)


class LogEmitter(QObject):
    log_signal = pyqtSignal(str)


class MainWindow(QMainWindow):
    tree_data_ready = pyqtSignal(object, object)
    hashes_ready = pyqtSignal(object)
    error_message = pyqtSignal(str)
    warmup_progress_signal = pyqtSignal(int, int, int)  # run_id, ready, total
    search_finished = pyqtSignal(str, list)  # query, results — ana thread'de sekme açmak için
    export_progress = pyqtSignal(str)
    full_report_progress = pyqtSignal(str)

    def __init__(self, case_dir: str, evidence_id: str | None = None):
        super().__init__()
        self.setWindowTitle("webdedik bilişim")
        self.case_dir = os.path.abspath(case_dir)
        self._initial_evidence_id = evidence_id
        self._snapshot_stop = False
        self.setMinimumSize(880, 520)

        self.logger = LogEmitter()
        self.logger.log_signal.connect(self.append_log)
        self.tree_data_ready.connect(self._apply_tree_model)
        self.hashes_ready.connect(self._on_hashes_ready)
        self.error_message.connect(self._show_error_message)
        self.search_finished.connect(self._on_search_finished)
        self.export_progress.connect(self.log)
        self.full_report_progress.connect(self._on_full_report_progress)

        self.engine_session = None
        self._thumb_manager = None
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.timeout.connect(self._request_visible_thumbnails)
        self.model = None
        self._selected_inode = None
        self._selected_name = None
        self._selected_is_dir = True  # dışa aktarma sadece dosya seçiliyken

        self._back_stack = []
        self._forward_stack = []
        self._current_inode = None
        self._navigate_from_history = False

        self._current_folder_nodes = []
        self._filter_show_zero_byte = False
        self._filter_types_allowed = None  # None=tümü, set=seçili türler

        self._tag_shortcuts: list[QShortcut] = []  # etiket kısayolları

        self._warmup_cancel_token = None
        self._warmup_run_id = 0
        self._warmup_debounce_timer = QTimer(self)
        self._warmup_debounce_timer.setSingleShot(True)
        self._warmup_debounce_timer.timeout.connect(self._start_warmup)
        self._warmup_safety_timer = QTimer(self)
        self._warmup_safety_timer.setSingleShot(True)
        self._warmup_safety_timer.timeout.connect(self._on_warmup_safety_timeout)
        self.warmup_progress_signal.connect(self._on_warmup_progress)
        self._preview_controller_holder = {}

        self.evidence_combo = QComboBox()
        self.evidence_combo.setMinimumWidth(220)
        self.evidence_combo.setMinimumHeight(28)
        self.evidence_combo.currentIndexChanged.connect(self._on_case_evidence_selected)

        menubar = QMenuBar(self)
        menu_file = QMenu("Dosya", self)
        act_e01 = menu_file.addAction("E01 Ekle")
        act_e01.triggered.connect(self._on_select_e01)
        self.act_build_snapshot = menu_file.addAction("Build Snapshot")
        self.act_build_snapshot.triggered.connect(self._on_build_snapshot)
        self.act_cancel_build = menu_file.addAction("Build İptal")
        self.act_cancel_build.triggered.connect(self._on_cancel_snapshot)
        self.act_cancel_build.setEnabled(False)
        act_case_open = menu_file.addAction("Case'ten Aç...")
        act_case_open.triggered.connect(self._on_menu_case_open)
        menu_file.addSeparator()
        self._act_menu_tree = menu_file.addAction("Ağaç görünümü (Tree)")
        self._act_menu_tree.setCheckable(True)
        self._act_menu_tree.setChecked(True)
        self._act_menu_tree.triggered.connect(self._on_menu_toggle_tree)
        self._act_menu_meta = menu_file.addAction("Meta veri paneli")
        self._act_menu_meta.setCheckable(True)
        self._act_menu_meta.setChecked(True)
        self._act_menu_meta.triggered.connect(self._on_menu_toggle_meta)
        self._act_menu_log = menu_file.addAction("Günlük paneli")
        self._act_menu_log.setCheckable(True)
        self._act_menu_log.setChecked(True)
        self._act_menu_log.triggered.connect(self._on_menu_toggle_log)
        menu_file.addSeparator()
        act_tag_settings = menu_file.addAction("Etiket ayarları...")
        act_tag_settings.triggered.connect(self._on_tag_settings_clicked)
        menubar.addMenu(menu_file)
        self.setMenuBar(menubar)

        self.toolbar = QToolBar()
        self.toolbar.setMovable(False)
        toolbar = self.toolbar
        self.act_back = QAction("Geri")
        self.act_back.triggered.connect(self._on_back)
        self.act_forward = QAction("İleri")
        self.act_forward.triggered.connect(self._on_forward)
        self.act_up = QAction("Yukarı")
        self.act_up.triggered.connect(self._on_up)
        self.act_refresh = QAction("Yenile")
        self.act_refresh.triggered.connect(self._on_refresh)
        toolbar.addAction(self.act_back)
        toolbar.addAction(self.act_forward)
        toolbar.addAction(self.act_up)
        toolbar.addAction(self.act_refresh)
        self.path_bar = QLineEdit()
        self.path_bar.setReadOnly(True)
        self.path_bar.setPlaceholderText(" / ")
        self.path_bar.setMinimumWidth(180)
        self.path_bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        toolbar.addWidget(QLabel(" Yol: "))
        toolbar.addWidget(self.path_bar)
        self.btn_report_full_toolbar = QPushButton("Genel Raporlama")
        self.btn_report_full_toolbar.setToolTip("Tüm dosyaları çıkar, hash hesapla, rapor oluştur (arka planda)")
        self.btn_report_full_toolbar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_report_full_toolbar.setMinimumWidth(120)
        self.btn_report_full_toolbar.clicked.connect(self._on_full_report_clicked)
        toolbar.addWidget(self.btn_report_full_toolbar)
        self.addToolBar(toolbar)

        # Arama çubuğu: toolbar'ın altında ayrı satır (alt alta), *.jpg vb. wildcard destekli
        self._search_bar_widget = self._make_search_bar_widget()
        self.search_input = self._search_bar_widget.findChild(QLineEdit, "searchInput")
        self.btn_search = self._search_bar_widget.findChild(QPushButton, "searchButton")

        self.tree = SidebarTreeView()
        self.tree.setObjectName(SIDEBAR_TREE_OBJECT_NAME)
        self.tree.setStyle(SidebarTreeProxyStyle(QApplication.style()))
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setAnimated(True)
        self.tree.setIndentation(TREE_INDENT)
        self.tree.setIconSize(QSize(20, 20))
        self.tree.setAutoExpandDelay(400)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.expanded.connect(self._on_folder_expanded)
        self.tree.clicked.connect(self._on_tree_clicked)
        self.tree.doubleClicked.connect(self._on_tree_double_clicked)
        self._tree_icon_dir = None
        # Kanıt sayısı etiketi
        self._tree_evidence_label = QLabel("")
        self._tree_evidence_label.setObjectName("treeEvidenceCount")
        self._tree_evidence_label.setStyleSheet(f"""
            QLabel#treeEvidenceCount {{
                background-color: {DESIGN_TOKENS['sidebar_bg']};
                color: {DESIGN_TOKENS['text_muted']};
                font-size: 12px;
                padding: 8px 12px;
                border: none;
                border-bottom: 1px solid {DESIGN_TOKENS['border_subtle']};
            }}
        """)
        self._tree_evidence_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sidebar_container = QWidget()
        sidebar_container.setObjectName("sidebarContainer")
        sidebar_ly = QVBoxLayout(sidebar_container)
        sidebar_ly.setContentsMargins(0, 0, 0, 0)
        sidebar_ly.setSpacing(0)
        sidebar_ly.addWidget(self._tree_evidence_label)
        sidebar_ly.addWidget(self.tree, 1)

        self._export_checked_inodes = set()
        self.file_list_model = FileListTableModel(self, self._export_checked_inodes)
        self.file_list_list_model = QStandardItemModel(self)

        self.file_table = QTableView()
        self.file_table.setObjectName("fileTable")
        self.file_table.setSortingEnabled(True)
        h = self.file_table.horizontalHeader()
        for c in range(len(FileListTableModel.HEADERS)):
            h.setSectionResizeMode(c, QHeaderView.ResizeMode.Interactive)
        h.setStretchLastSection(False)
        h.setDefaultSectionSize(100)
        h.setMinimumSectionSize(40)
        self.file_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.file_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.file_table.setAlternatingRowColors(True)
        self.file_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.file_table.verticalHeader().setDefaultSectionSize(34)
        self.file_table.setModel(self.file_list_model)
        self.file_list_model.dataChanged.connect(self._on_file_list_data_changed)
        self.file_table.doubleClicked.connect(self._on_table_double_clicked)
        self.file_table.selectionModel().selectionChanged.connect(self._on_table_selection_changed)
        self.file_table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.file_table.verticalScrollBar().valueChanged.connect(lambda: self._thumb_timer.start(150))
        self.file_table.verticalScrollBar().setSingleStep(100)
        self.file_table.viewport().installEventFilter(self)
        self._apply_file_table_palette()
        self.file_table.setCursor(Qt.CursorShape.PointingHandCursor)
        self.file_table.horizontalHeader().setSortIndicatorShown(True)
        self.file_table.setShowGrid(False)
        self.file_table.verticalHeader().setVisible(False)
        self.file_table.setWordWrap(False)
        # Kolon genişlikleri: kanıt metinleri tam görünsün (tarih/boyut/inode)
        h = self.file_table.horizontalHeader()
        h.setMinimumSectionSize(44)
        if h.count() >= 9:
            self.file_table.setColumnWidth(FileListTableModel.COL_SEL, 40)
            self.file_table.setColumnWidth(FileListTableModel.COL_NAME, 344)
            self.file_table.setColumnWidth(FileListTableModel.COL_INODE, 90)
            self.file_table.setColumnWidth(FileListTableModel.COL_SIZE, 92)
            self.file_table.setColumnWidth(FileListTableModel.COL_TYPE, 98)
            self.file_table.setColumnWidth(FileListTableModel.COL_MODIFIED, 172)
            self.file_table.setColumnWidth(FileListTableModel.COL_ACCESSED, 172)
            self.file_table.setColumnWidth(FileListTableModel.COL_CREATED, 172)
            self.file_table.setColumnWidth(FileListTableModel.COL_DELETED, 68)
        self.file_table.setItemDelegateForColumn(
            FileListTableModel.COL_NAME,
            TagBarDelegate(self._get_tag_color_for_inode, self.file_list_model, self.file_table),
        )

        self.file_list_view = QListView()
        self.file_list_view.setModel(self.file_list_list_model)
        self.file_list_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.file_list_view.setViewMode(QListView.ViewMode.ListMode)
        self.file_list_view.setUniformItemSizes(True)
        self.file_list_view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.file_list_view.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self.file_list_view.setMovement(QListView.Movement.Static)
        self.file_list_view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.file_list_view.setWordWrap(True)
        self.file_list_view.setSpacing(10)
        self.file_list_view.doubleClicked.connect(self._on_list_double_clicked)
        self.file_list_view.selectionModel().selectionChanged.connect(self._on_list_selection_changed)
        self.file_list_view.verticalScrollBar().valueChanged.connect(lambda: self._thumb_timer.start(150))
        self.file_list_view.verticalScrollBar().setSingleStep(100)
        self.file_list_view.viewport().installEventFilter(self)
        self.file_list_view.setItemDelegate(ListViewTagDelegate(self._get_tag_color_for_inode, self.file_list_view))

        self.view_stack = QStackedWidget()
        self.view_stack.addWidget(self.file_table)
        self.view_stack.addWidget(self.file_list_view)

        # Tür filtresi çubuğu
        t = DESIGN_TOKENS
        self._center_filter_bar = QFrame()
        self._center_filter_bar.setObjectName("centerFilterBar")
        self._center_filter_bar.setStyleSheet(f"""
            QFrame#centerFilterBar {{
                background-color: {t["grid_style_header"]};
                border: none;
                border-bottom: 1px solid {t["grid_style_border"]};
                padding: 0;
            }}
            QFrame#centerFilterBar QLabel {{
                color: {t["grid_style_text"]};
                font-size: 12px;
                font-weight: 600;
            }}
            QFrame#centerFilterBar QPushButton {{
                background-color: {t["bg_panel"]};
                color: {t["text_primary"]};
                border: 1px solid {t["border_subtle"]};
                border-radius: 4px;
                padding: 8px 14px;
                font-size: 12px;
                min-height: 20px;
            }}
            QFrame#centerFilterBar QPushButton:hover {{
                background-color: {t["accent_soft"]};
                border-color: {t["accent"]};
                color: {t["accent"]};
            }}
            QFrame#centerFilterBar QPushButton:disabled {{
                color: {t["text_dim"]};
            }}
        """)
        filter_bar_ly = QHBoxLayout(self._center_filter_bar)
        filter_bar_ly.setContentsMargins(12, 8, 12, 8)
        filter_bar_ly.setSpacing(10)
        filter_bar_ly.addWidget(QLabel("Tür"))
        self.btn_type_filter = QPushButton("Tüm türler")
        self.btn_type_filter.setToolTip("Hangi türleri göstereceğinizi seçin (Klasör, .jpg, .pdf vb.)")
        self.btn_type_filter.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_type_filter.clicked.connect(self._on_type_filter_clicked)
        filter_bar_ly.addWidget(self.btn_type_filter)
        filter_bar_ly.addWidget(QLabel("  "))
        self.filter_show_zero_byte = QCheckBox("0 byte göster")
        self.filter_show_zero_byte.setToolTip("0 byte dosyalarını listeye dahil et")
        self.filter_show_zero_byte.toggled.connect(self._on_filter_toggled)
        filter_bar_ly.addWidget(self.filter_show_zero_byte)
        filter_bar_ly.addWidget(QLabel("  Görünüm:"))
        self.view_mode_combo = QComboBox()
        self.view_mode_combo.addItems(["Detay", "Büyük simge"])
        self.view_mode_combo.setCurrentIndex(0)
        self.view_mode_combo.currentIndexChanged.connect(self._on_view_mode_changed)
        filter_bar_ly.addWidget(self.view_mode_combo)
        self._icon_size_label = QLabel(" Simge boyutu:")
        filter_bar_ly.addWidget(self._icon_size_label)
        self._icon_size_preference = "auto"
        self._icon_size_spacer = QLabel("  ")
        filter_bar_ly.addWidget(self._icon_size_spacer)
        self.icon_size_combo = QComboBox()
        self.icon_size_combo.addItems([
            "Otomatik", "Küçük (96 px)", "Orta (128 px)", "Büyük (160 px)", "Çok büyük (200 px)",
        ])
        self.icon_size_combo.setCurrentIndex(0)
        self.icon_size_combo.setMinimumContentsLength(16)
        self.icon_size_combo.setMinimumWidth(140)
        self.icon_size_combo.currentIndexChanged.connect(self._on_icon_size_changed)
        filter_bar_ly.addWidget(self.icon_size_combo)
        self._icon_size_label.setVisible(False)
        self._icon_size_spacer.setVisible(False)
        self.icon_size_combo.setVisible(False)
        filter_bar_ly.addStretch()
        filter_bar_ly.addWidget(QLabel(""))
        self.btn_select_all_export = QPushButton("Tümünü seç")
        self.btn_select_all_export.setToolTip("Dışarı aktarma için listedeki tüm öğeleri seç")
        self.btn_select_all_export.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_select_all_export.clicked.connect(self._on_select_all_export_clicked)
        filter_bar_ly.addWidget(self.btn_select_all_export)
        self.btn_clear_export_selection = QPushButton("Seçimi temizle")
        self.btn_clear_export_selection.setToolTip("Dışarı aktarma seçimini kaldır")
        self.btn_clear_export_selection.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear_export_selection.clicked.connect(self._on_clear_export_selection_clicked)
        filter_bar_ly.addWidget(self.btn_clear_export_selection)
        self.btn_report = QPushButton("Bölüm raporu")
        self.btn_report.setToolTip("Sadece bu klasörün raporu (HTML/PDF)")
        self.btn_report.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_report.setMinimumWidth(100)
        self.btn_report.clicked.connect(self._on_report_clicked)
        filter_bar_ly.addWidget(self.btn_report)
        self.btn_export_file = QPushButton("Dosyayı aktarma")
        self.btn_export_file.setToolTip("Checkbox ile işaretlenen dosya(ları) diske kaydet")
        self.btn_export_file.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_export_file.setMinimumWidth(115)
        self.btn_export_file.clicked.connect(self._on_export_file_clicked)
        filter_bar_ly.addWidget(self.btn_export_file)
        self.btn_tag_item = QPushButton("Etiketle")
        self.btn_tag_item.setToolTip("Seçili öğeye etiket ve not ekle")
        self.btn_tag_item.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_tag_item.setMinimumWidth(70)
        self.btn_tag_item.clicked.connect(self._on_tag_item_clicked)
        filter_bar_ly.addWidget(self.btn_tag_item)
        self._center_file_list_wrap = QWidget()
        center_wrap_ly = QVBoxLayout(self._center_file_list_wrap)
        center_wrap_ly.setContentsMargins(0, 0, 0, 0)
        center_wrap_ly.setSpacing(0)
        self._center_filter_bar.setMinimumWidth(860)
        filter_scroll = QScrollArea()
        filter_scroll.setObjectName("filterBarScroll")
        filter_scroll.setWidgetResizable(True)
        filter_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        filter_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        filter_scroll.setFrameShape(QFrame.Shape.NoFrame)
        filter_scroll.setWidget(self._center_filter_bar)
        filter_scroll.setMaximumHeight(58)
        filter_scroll.setStyleSheet("QScrollArea#filterBarScroll { background: transparent; }")
        center_wrap_ly.addWidget(filter_scroll)
        center_wrap_ly.addWidget(self.view_stack, 1)

        self._empty_state_widget = self._make_empty_state_widget()
        self.center_stack = QStackedWidget()
        self.center_stack.addWidget(self._center_file_list_wrap)   # 0: dosya listesi
        self.center_stack.addWidget(self._empty_state_widget)  # 1: boş klasör

        self.meta_name = QLabel("N/A")
        self.meta_inode = QLabel("N/A")
        self.meta_type = QLabel("N/A")
        self.meta_size = QLabel("N/A")
        self.meta_mtime = QLabel("N/A")
        self.meta_atime = QLabel("N/A")
        self.meta_ctime = QLabel("N/A")
        self.meta_crtime = QLabel("N/A")
        self.meta_deleted = QLabel("N/A")
        self.meta_md5 = QLabel("N/A")
        self.meta_sha1 = QLabel("N/A")
        _all_meta_labels = (
            self.meta_name, self.meta_inode, self.meta_type, self.meta_size,
            self.meta_mtime, self.meta_atime, self.meta_ctime, self.meta_crtime,
            self.meta_deleted, self.meta_md5, self.meta_sha1,
        )
        for lb in _all_meta_labels:
            lb.setObjectName("inspectorValue")
            lb.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lb.setWordWrap(True)
        meta_form = QFormLayout()
        meta_form.setSpacing(10)
        meta_form.setContentsMargins(16, 20, 16, 16)
        meta_form.addRow("Ad", self.meta_name)
        meta_form.addRow("Inode", self.meta_inode)
        meta_form.addRow("Tür", self.meta_type)
        meta_form.addRow("Boyut (bayt)", self.meta_size)
        meta_form.addRow("Değiştirilme (mtime)", self.meta_mtime)
        meta_form.addRow("Erişim (atime)", self.meta_atime)
        meta_form.addRow("Değişiklik (ctime)", self.meta_ctime)
        meta_form.addRow("Oluşturulma (crtime)", self.meta_crtime)
        meta_form.addRow("Silindi", self.meta_deleted)
        meta_form.addRow("MD5", self.meta_md5)
        meta_form.addRow("SHA1", self.meta_sha1)
        self.btn_hashes = QPushButton("Hash hesapla")
        self.btn_hashes.setObjectName("metaHashBtn")
        self.btn_hashes.clicked.connect(self._on_compute_hashes)
        meta_form.addRow("", self.btn_hashes)
        meta_group = QGroupBox("Dosya özellikleri")
        meta_group.setObjectName("inspectorGroup")
        meta_group.setLayout(meta_form)
        # EXIF: GPS, cihaz, tarih
        self.meta_gps = QLabel("N/A")
        self.meta_make = QLabel("N/A")
        self.meta_model = QLabel("N/A")
        self.meta_datetime_original = QLabel("N/A")
        self.meta_software = QLabel("N/A")
        self.meta_image_size = QLabel("N/A")
        for lb in (self.meta_gps, self.meta_make, self.meta_model, self.meta_datetime_original,
                   self.meta_software, self.meta_image_size):
            lb.setObjectName("inspectorValue")
            lb.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lb.setWordWrap(True)
        forensic_form = QFormLayout()
        forensic_form.setSpacing(10)
        forensic_form.setContentsMargins(16, 20, 16, 16)
        forensic_form.addRow("Konum (GPS)", self.meta_gps)
        forensic_form.addRow("Cihaz (Make)", self.meta_make)
        forensic_form.addRow("Model", self.meta_model)
        forensic_form.addRow("Çekim tarihi", self.meta_datetime_original)
        forensic_form.addRow("Yazılım", self.meta_software)
        forensic_form.addRow("Görüntü boyutu", self.meta_image_size)
        forensic_group = QGroupBox("EXIF / Medya")
        forensic_group.setObjectName("inspectorGroup")
        forensic_group.setLayout(forensic_form)
        meta_container = QWidget()
        meta_container.setObjectName("metaPanelContainer")
        meta_container_ly = QVBoxLayout(meta_container)
        meta_container_ly.setContentsMargins(12, 12, 12, 12)
        meta_container_ly.setSpacing(8)
        meta_container_ly.addWidget(meta_group)
        meta_container_ly.addWidget(forensic_group)
        meta_scroll = QScrollArea()
        meta_scroll.setObjectName("inspectorScroll")
        meta_scroll.setWidget(meta_container)
        meta_scroll.setWidgetResizable(True)
        meta_scroll.setMinimumWidth(0)
        meta_scroll.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.log_box = QTextEdit()
        self.log_box.setObjectName("logPanel")
        self.log_box.setReadOnly(True)
        self.log_box.setAcceptRichText(True)

        center_frame = QFrame()
        center_frame.setObjectName("centerPanel")
        center_ly = QVBoxLayout(center_frame)
        center_ly.setContentsMargins(0, 0, 0, 0)
        center_ly.setSpacing(0)
        self._main_tabs = QTabWidget()
        self._main_tabs.setObjectName("mainTabs")
        self._main_tabs.addTab(self.center_stack, "Dosya Gezgini")
        self._tags_tab_widget = self._make_tags_tab_widget()
        self._main_tabs.addTab(self._tags_tab_widget, "Etiketler")
        self._main_tabs.setTabsClosable(True)
        self._main_tabs.tabCloseRequested.connect(self._on_tab_close_requested)
        self._main_tabs.currentChanged.connect(self._on_main_tab_changed)
        # İlk iki sekme sabit
        self._main_tabs.tabBar().setTabButton(0, QTabBar.ButtonPosition.RightSide, None)
        self._main_tabs.tabBar().setTabButton(1, QTabBar.ButtonPosition.RightSide, None)
        center_ly.addWidget(self._main_tabs)
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._main_splitter = main_splitter
        main_splitter.addWidget(sidebar_container)
        main_splitter.addWidget(center_frame)
        main_splitter.setChildrenCollapsible(True)
        self.tree.setMinimumWidth(120)
        self.tree.setMaximumWidth(700)
        self.tree.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        sidebar_container.setMinimumWidth(0)
        sidebar_container.setMaximumWidth(700)
        self._saved_tree_width = 220
        self.view_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.center_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        center_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        center_frame.setMinimumWidth(280)

        # Meta veri paneli: dikey yazılı tab (aşağıdan yukarı) + içerik
        t = DESIGN_TOKENS
        meta_tab_widget = VerticalMetaTabWidget("Meta veri", self)
        meta_tab_widget.clicked.connect(self._on_meta_tab_clicked)
        meta_scroll.setMinimumWidth(0)
        meta_splitter = QSplitter(Qt.Orientation.Horizontal)
        meta_splitter.setChildrenCollapsible(True)
        meta_splitter.addWidget(meta_tab_widget)
        meta_splitter.addWidget(meta_scroll)
        meta_splitter.setSizes([48, 280])
        meta_splitter.setStretchFactor(0, 0)
        meta_splitter.setStretchFactor(1, 1)
        self._meta_splitter = meta_splitter
        self._meta_tab_widget = meta_tab_widget
        self._meta_scroll = meta_scroll
        meta_scroll.setMinimumWidth(200)
        main_splitter.addWidget(meta_splitter)
        main_splitter.setSizes([self._saved_tree_width, 600, 328])
        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 1)
        main_splitter.setStretchFactor(2, 0)
        main_splitter.splitterMoved.connect(self._on_main_splitter_moved)
        meta_splitter.splitterMoved.connect(self._on_meta_splitter_moved)

        # Günlük paneli (açılıp kapanır)
        LOG_TAB_H = 28
        LOG_CONTENT_DEFAULT = 150
        LOG_CONTENT_MIN = 100
        LOG_CONTENT_MAX = 320
        log_tab_btn = QPushButton("Günlük  ▼")
        log_tab_btn.setObjectName("logTabBtn")
        log_tab_btn.setFixedHeight(LOG_TAB_H)
        log_tab_btn.setToolTip("Günlük panelini aç / kapat")
        log_tab_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        log_tab_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        log_tab_btn.clicked.connect(self._on_log_tab_clicked)
        log_tab_btn.setStyleSheet(f"""
            QPushButton#logTabBtn {{
                background: {t['log_bg']};
                color: {t['text_muted']};
                border: 1px solid {t['border_subtle']};
                border-bottom: none;
                font-size: 12px;
                font-weight: 600;
                padding: 4px 16px;
            }}
            QPushButton#logTabBtn:hover {{ background: {t['accent_soft']}; color: {t['accent']}; }}
        """)
        self._report_progress_bar = QProgressBar()
        self._report_progress_bar.setObjectName("reportProgressBar")
        self._report_progress_bar.setMinimum(0)
        self._report_progress_bar.setMaximum(100)
        self._report_progress_bar.setValue(0)
        self._report_progress_bar.setTextVisible(True)
        self._report_progress_bar.setFormat("%p%")
        self._report_progress_bar.setFixedHeight(22)
        self._report_progress_label = QLabel("")
        self._report_progress_label.setObjectName("reportProgressLabel")
        report_progress_wrap = QFrame()
        report_progress_wrap.setObjectName("reportProgressWrap")
        report_progress_wrap.setMinimumHeight(40)
        report_progress_ly = QVBoxLayout(report_progress_wrap)
        report_progress_ly.setContentsMargins(8, 4, 8, 4)
        report_progress_ly.setSpacing(2)
        report_progress_ly.addWidget(self._report_progress_label)
        report_progress_ly.addWidget(self._report_progress_bar)
        report_progress_wrap.setVisible(False)
        self._report_progress_wrap = report_progress_wrap
        bottom_bar = QWidget()
        bottom_bar.setObjectName("logBottomBar")
        bottom_bar.setMinimumHeight(LOG_TAB_H)
        bottom_bar_ly = QVBoxLayout(bottom_bar)
        bottom_bar_ly.setContentsMargins(0, 0, 0, 0)
        bottom_bar_ly.setSpacing(0)
        bottom_bar_ly.addWidget(log_tab_btn)
        bottom_bar_ly.addWidget(report_progress_wrap)
        log_box_wrap = QWidget()
        log_box_wrap.setMinimumHeight(0)
        log_box_wrap.setMaximumHeight(LOG_CONTENT_MAX)
        log_box_wrap.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.log_box.setMinimumHeight(0)
        log_ly = QVBoxLayout(log_box_wrap)
        log_ly.setContentsMargins(0, 0, 0, 0)
        log_ly.addWidget(self.log_box)
        log_splitter = QSplitter(Qt.Orientation.Vertical)
        log_splitter.setChildrenCollapsible(True)
        log_splitter.addWidget(bottom_bar)
        log_splitter.addWidget(log_box_wrap)
        log_splitter.setSizes([LOG_TAB_H, LOG_CONTENT_DEFAULT])
        log_splitter.setStretchFactor(0, 0)
        log_splitter.setStretchFactor(1, 1)
        self._log_splitter = log_splitter
        self._log_tab_btn = log_tab_btn
        self._log_box_wrap = log_box_wrap
        self._log_open = True
        self._meta_open = True
        self._log_content_default = LOG_CONTENT_DEFAULT
        self._log_content_min = LOG_CONTENT_MIN
        self._log_content_max = LOG_CONTENT_MAX
        self._log_tab_h = LOG_TAB_H

        outer_splitter = QSplitter(Qt.Orientation.Vertical)
        self._outer_splitter = outer_splitter
        outer_splitter.addWidget(main_splitter)
        outer_splitter.addWidget(log_splitter)
        outer_splitter.setStretchFactor(0, 1)
        outer_splitter.setStretchFactor(1, 0)
        # Başlangıç yerleşimi
        outer_splitter.setSizes([1, LOG_TAB_H + LOG_CONTENT_DEFAULT])

        central = QWidget()
        central.setObjectName("centralWidget")
        central.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(0)
        layout.addWidget(self._search_bar_widget)
        layout.addWidget(outer_splitter, 1)
        self.setCentralWidget(central)
        self._update_export_file_button_state()
        self._register_tag_shortcuts()

        # Thumbnail overlay widget
        self._overlay = ThumbnailOverlayWidget(self)
        self._overlay.hide()

        self._apply_theme()
        self._refresh_evidence_list()
        self._update_nav_buttons()
        self._update_empty_state_visibility()
        if self._initial_evidence_id:
            QTimer.singleShot(0, lambda: self._start_tree_cached(self._initial_evidence_id))
        elif self.evidence_combo.count() > 1:
            # Case aç ile geldiyse ilk kanıtı yükle
            self.evidence_combo.setCurrentIndex(1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._overlay.isVisible():
            self._overlay.setGeometry(self.rect())

    def _on_full_report_progress(self, msg: str):
        """Rapor ilerlemesi."""
        if "Genel rapor tamamlandı" in msg or "Genel rapor hatası" in msg:
            self._report_progress_wrap.setVisible(False)
            self._report_progress_bar.setValue(0)
            if getattr(self, "_log_splitter", None) and getattr(self, "_log_content_default", None):
                self._log_splitter.setSizes([getattr(self, "_log_tab_h", 28), self._log_content_default])
            self.btn_report_full_toolbar.setEnabled(True)
            self.btn_report_full_toolbar.setText("Genel Raporlama")
            self.log(msg)
            return
        self.btn_report_full_toolbar.setEnabled(False)
        self.btn_report_full_toolbar.setText("Raporlanıyor...")
        self._report_progress_wrap.setVisible(True)
        self._report_progress_label.setText(msg)
        if getattr(self, "_log_splitter", None):
            tab_h = getattr(self, "_log_tab_h", 28)
            content_default = getattr(self, "_log_content_default", 200)
            self._log_splitter.setSizes([tab_h + 50, max(80, content_default - 50)])
        import re
        m = re.search(r"Genel rapor:\s*%(\d+)\s*\(\d+/\d+\)", msg)
        if m:
            pct = min(100, max(0, int(m.group(1))))
            self._report_progress_bar.setValue(pct)
        elif "dizin ağacı" in msg or "dosya bulundu" in msg:
            self._report_progress_bar.setValue(0)
        elif "HTML oluşturuluyor" in msg:
            self._report_progress_bar.setValue(95)

    def append_log(self, text: str):
        """Log panel renkleri."""
        lower = text.lower()
        if "hata" in lower or "error" in lower or "[hata]" in lower:
            html = f'<span style="color: {DESIGN_TOKENS["log_error"]};">{self._escape_html(text)}</span>'
        elif "uyarı" in lower or "warning" in lower or "warn" in lower:
            html = f'<span style="color: {DESIGN_TOKENS["log_warning"]};">{self._escape_html(text)}</span>'
        else:
            html = f'<span style="color: {DESIGN_TOKENS["log_text"]};">{self._escape_html(text)}</span>'
        self.log_box.append(html)

    def _escape_html(self, s: str) -> str:
        return (
            s.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    def _apply_file_table_palette(self):
        """Tablo grid stili."""
        t = DESIGN_TOKENS
        pal = QPalette()
        pal.setColor(QPalette.ColorRole.Base, _hex_to_qcolor(t["grid_style_bg"]))
        pal.setColor(QPalette.ColorRole.Window, _hex_to_qcolor(t["grid_style_bg"]))
        pal.setColor(QPalette.ColorRole.Text, _hex_to_qcolor(t["grid_style_text"]))
        pal.setColor(QPalette.ColorRole.WindowText, _hex_to_qcolor(t["grid_style_text"]))
        self.file_table.setPalette(pal)
        self.file_table.viewport().setPalette(pal)
        self.file_table.setAutoFillBackground(True)
        self.file_table.viewport().setAutoFillBackground(True)
        h = self.file_table.horizontalHeader()
        hpal = QPalette()
        hpal.setColor(QPalette.ColorRole.Button, _hex_to_qcolor(t["grid_style_header"]))
        hpal.setColor(QPalette.ColorRole.Window, _hex_to_qcolor(t["grid_style_header"]))
        hpal.setColor(QPalette.ColorRole.ButtonText, _hex_to_qcolor(t["grid_style_text"]))
        hpal.setColor(QPalette.ColorRole.WindowText, _hex_to_qcolor(t["grid_style_text"]))
        h.setPalette(hpal)
        h.setAutoFillBackground(True)

    def _make_search_bar_widget(self) -> QWidget:
        """Arama satırı widget'ı."""
        t = DESIGN_TOKENS
        wrap = QFrame()
        wrap.setObjectName("searchBarFrame")
        wrap.setStyleSheet(f"""
            QFrame#searchBarFrame {{
                background-color: {t["bg_elevated"]};
                border: none;
                border-bottom: 1px solid {t["border_subtle"]};
            }}
        """)
        ly = QHBoxLayout(wrap)
        ly.setContentsMargins(16, 12, 16, 12)
        ly.setSpacing(12)
        lbl = QLabel("Ara (dosya/klasör veya *.jpg, *rapor*):")
        lbl.setObjectName("searchBarLabel")
        lbl.setStyleSheet(f"color: {t['text_muted']}; font-size: 13px;")
        ly.addWidget(lbl)
        le = QLineEdit()
        le.setObjectName("searchInput")
        le.setPlaceholderText("Örn: rapor, *.jpg, *.pdf, *2024*")
        le.setMinimumWidth(320)
        le.setClearButtonEnabled(True)
        le.returnPressed.connect(self._on_search_triggered)
        le.setStyleSheet(f"""
            QLineEdit {{
                background-color: white;
                border: 1px solid {t['border_subtle']};
                padding: 10px 14px;
                font-size: 14px;
            }}
            QLineEdit:focus {{ border-color: {t['accent']}; }}
        """)
        ly.addWidget(le, 1)
        btn = QPushButton("Ara")
        btn.setObjectName("searchButton")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(self._on_search_triggered)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {t['accent']};
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px 24px;
                font-size: 14px;
                font-weight: 600;
            }}
            QPushButton:hover {{ background-color: #2563eb; }}
            QPushButton:pressed {{ background-color: #1d4ed8; }}
            QPushButton:disabled {{ background-color: {t['text_muted']}; color: #e5e7eb; }}
        """)
        ly.addWidget(btn)
        return wrap

    def _make_empty_state_widget(self) -> QWidget:
        """Boş klasör mesajı."""
        t = DESIGN_TOKENS
        wrap = QWidget()
        wrap.setObjectName("emptyStatePanel")
        wrap.setStyleSheet(f"""
            QWidget#emptyStatePanel {{
                background-color: {t["bg_panel"]};
            }}
        """)
        ly = QVBoxLayout(wrap)
        ly.setContentsMargins(24, 24, 24, 24)
        ly.setSpacing(16)
        ly.addStretch(1)
        icon_label = QLabel()
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon = QApplication.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        icon_label.setPixmap(icon.pixmap(64, 64))
        ly.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignCenter)
        title = QLabel("Bu klasör boş")
        title.setObjectName("emptyStateTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"""
            QLabel#emptyStateTitle {{
                color: {t["text_primary"]};
                font-size: 18px;
                font-weight: 600;
            }}
        """)
        ly.addWidget(title, 0, Qt.AlignmentFlag.AlignCenter)
        desc = QLabel("Bu klasörde dosya veya alt klasör bulunmuyor.\nBaşka bir klasöre giderek içeriği görüntüleyebilirsiniz.")
        desc.setObjectName("emptyStateDesc")
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setWordWrap(True)
        desc.setStyleSheet(f"""
            QLabel#emptyStateDesc {{
                color: {t["text_muted"]};
                font-size: 14px;
                line-height: 1.4;
            }}
        """)
        ly.addWidget(desc, 0, Qt.AlignmentFlag.AlignCenter)
        ly.addStretch(1)
        return wrap

    def _make_tags_tab_widget(self) -> QWidget:
        """Etiketler sekmesi (türe göre gruplu)."""
        t = DESIGN_TOKENS
        wrap = QWidget()
        wrap.setObjectName("tagsTab")
        ly = QVBoxLayout(wrap)
        ly.setContentsMargins(12, 12, 12, 12)
        self._tags_list = QListWidget()
        self._tags_list.setObjectName("tagsList")
        self._tags_list.setStyleSheet(f"""
            QListWidget#tagsList {{
                background-color: {t["bg_panel"]};
                border: 1px solid {t["border_subtle"]};
                font-size: 13px;
            }}
        """)
        ly.addWidget(QLabel("Etiketli öğeler (kanıt bazında):"))
        ly.addWidget(self._tags_list, 1)
        return wrap

    def _refresh_tags_tab(self):
        """Etiket sekmesini doldur."""
        self._tags_list.clear()
        defs = tag_manager.load_definitions()
        assignments = tag_manager.get_assignments_for_evidence(
            getattr(self.engine_session, "evidence_id", None) or ""
        )
        if not assignments:
            self._tags_list.addItem("Henüz etiketlenmiş öğe yok. Dosya Gezgini'nde bir öğe seçip \"Etiketle\" ile ekleyin.")
            return
        by_tag = {}
        for a in assignments:
            name = a.get("tag_name") or "?"
            by_tag.setdefault(name, []).append(a)
        for tag_name in [d["name"] for d in defs if d.get("name") in by_tag]:
            color = tag_manager.get_tag_color(defs, tag_name)
            header = QListWidgetItem(f"  {tag_name}")
            header.setBackground(QColor(color))
            header.setForeground(QColor("#fff" if QColor(color).lightness() < 128 else "#111"))
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            self._tags_list.addItem(header)
            for a in by_tag[tag_name]:
                path = self._get_path_for_inode(a.get("inode")) or f"inode {a.get('inode')}"
                note = (a.get("note") or "").strip()
                text = path + (f" — {note}" if note else "")
                self._tags_list.addItem(text)

    def _update_empty_state_visibility(self):
        """Boş/dolu duruma göre görünüm."""
        is_empty = not (self.file_list_model and self.file_list_model.rowCount() > 0)
        self.center_stack.setCurrentIndex(1 if is_empty else 0)

    def _on_tab_close_requested(self, index: int):
        """Sekme kapatma kontrolü."""
        if index <= 1:
            return
        self._main_tabs.removeTab(index)

    def _on_main_tab_changed(self, index: int):
        """Sekme değişince senkronize et."""
        if index == 0:
            idx = self.file_table.currentIndex() if self.view_stack.currentIndex() == 0 else self.file_list_view.currentIndex()
            if idx.isValid():
                node = self.file_list_model.get_node_at(idx.row())
                if node:
                    self._update_metadata_from_inode_name(node.get("inode"), node.get("name"))
                    return
            self._on_selection_changed()
            return
        if index == 1:
            self._refresh_tags_tab()
            return
        w = self._main_tabs.widget(index)
        stack = getattr(w, "_search_content_stack", None)
        lv = getattr(w, "_search_list_view", None)
        tmodel = getattr(w, "_search_table_model", None)
        if not stack:
            return
        if self.view_mode_combo.currentIndex() == 1 and lv:
            stack.setCurrentIndex(1)
            lv.setViewMode(QListView.ViewMode.IconMode)
            self._update_icon_grid_for(lv)
            if tmodel and tmodel.rowCount() > 0:
                nodes = tmodel.get_nodes()
                QTimer.singleShot(100, lambda: self._start_warmup_for_nodes(nodes))
        else:
            stack.setCurrentIndex(0)
        table = getattr(w, "_search_table", None)
        list_view = getattr(w, "_search_list_view", None)
        if tmodel:
            idx = (list_view.currentIndex() if stack.currentIndex() == 1 and list_view
                   else table.currentIndex() if table else QModelIndex())
            if idx.isValid():
                node = tmodel.get_node_at(idx.row())
                if node:
                    self._update_metadata_from_inode_name(node.get("inode"), node.get("name"))

    def _on_search_triggered(self):
        """Volume'da ara, sonuçlar yeni sekmede."""
        search_le = self._search_bar_widget.findChild(QLineEdit, "searchInput")
        search_btn = self._search_bar_widget.findChild(QPushButton, "searchButton")
        query = (search_le.text() or "").strip() if search_le else ""
        if not query:
            self.log("Arama: lütfen bir kelime veya kalıp girin (örn. *.jpg).")
            return
        if not self.engine_session:
            self.log("Arama: önce bir kanıt (E01) seçin ve ağacı yükleyin.")
            return
        if search_btn:
            search_btn.setEnabled(False)
            search_btn.setText("Aranıyor…")
        # Tüm volume'da ara
        from_inode = None
        log_callback = self.log

        def run_search():
            try:
                return self.engine_session.search_in_directory(
                    from_inode, query, log_callback=log_callback
                )
            except Exception as e:
                log_callback(f"Arama hatası: {e}")
                return []

        def on_done():
            results = []
            try:
                results = run_search()
            except Exception as e:
                log_callback(f"Arama hatası: {e}")
            finally:
                # Signal ana thread'de çalışır; QTimer.singleShot arka planda güvenilir değil
                self.search_finished.emit(query, results)

        threading.Thread(target=on_done, daemon=True).start()

    def _on_search_finished(self, query: str, results: list):
        """Arama bitti; aynı varsa geç, yoksa yeni sekme."""
        if getattr(self, "_main_tabs", None):
            for i in range(1, self._main_tabs.count()):
                w = self._main_tabs.widget(i)
                if getattr(w, "_search_query", None) == query:
                    self._main_tabs.setCurrentIndex(i)
                    search_btn = self._search_bar_widget.findChild(QPushButton, "searchButton")
                    if search_btn:
                        search_btn.setEnabled(True)
                        search_btn.setText("Ara")
                    self.log(f"Aynı arama zaten açık: \"{query}\" — mevcut sekmeye geçildi.")
                    return
        self._add_search_result_tab(query, results)
        search_btn = self._search_bar_widget.findChild(QPushButton, "searchButton")
        if search_btn:
            search_btn.setEnabled(True)
            search_btn.setText("Ara")

    def _add_search_result_tab(self, query: str, results: list):
        """Arama sonuçlarını yeni sekmede göster."""
        if results is None:
            results = []
        if not getattr(self, "_main_tabs", None):
            return
        for n in results:
            n["category"] = categorize_node(n)
        # 0 byte filtresi
        show_zero = self.filter_show_zero_byte.isChecked()
        filtered = [n for n in results if n.get("category") != FileCategory.ZERO_BYTE or show_zero]
        title = (query[:24] + "…") if len(query) > 24 else query
        t = DESIGN_TOKENS

        container = QWidget()
        container.setObjectName("searchResultTab")
        container._search_query = query
        container.setStyleSheet(f"""
            QWidget#searchResultTab {{ background-color: {t['bg_panel']}; }}
        """)
        ly = QVBoxLayout(container)
        ly.setContentsMargins(0, 0, 0, 0)
        ly.setSpacing(0)

        # Üst bilgi çubuğu: arama terimi + sonuç sayısı
        header = QFrame()
        header.setObjectName("searchResultHeader")
        header.setStyleSheet(f"""
            QFrame#searchResultHeader {{
                background-color: {t['bg_elevated']};
                border: none;
                border-bottom: 1px solid {t['border_subtle']};
                padding: 10px 16px;
            }}
        """)
        header_ly = QHBoxLayout(header)
        header_ly.setContentsMargins(12, 8, 12, 8)
        header_ly.setSpacing(12)
        lbl_title = QLabel(f"Arama: \"{query}\"")
        lbl_title.setStyleSheet(f"color: {t['text_primary']}; font-size: 13px; font-weight: 600;")
        header_ly.addWidget(lbl_title)
        lbl_count = QLabel(f"{len(filtered)} sonuç")
        lbl_count.setStyleSheet(f"color: {t['text_muted']}; font-size: 12px;")
        header_ly.addWidget(lbl_count)
        header_ly.addStretch(1)
        ly.addWidget(header)

        if not filtered:
            # Sonuç yok
            empty = QWidget()
            empty_ly = QVBoxLayout(empty)
            empty_ly.setContentsMargins(24, 48, 24, 48)
            empty_ly.addStretch(1)
            msg = "Bu aramada eşleşme yok." if not results else "0 byte filtresi açık değil; eşleşen 0 byte dosyalar gizlendi. \"0 byte göster\" işaretleyerek tekrar arayın."
            lbl_empty = QLabel(msg)
            lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_empty.setWordWrap(True)
            lbl_empty.setStyleSheet(f"color: {t['text_muted']}; font-size: 14px;")
            empty_ly.addWidget(lbl_empty, 0, Qt.AlignmentFlag.AlignCenter)
            empty_ly.addStretch(1)
            ly.addWidget(empty, 1)
        else:
            # Detay ve büyük simge görünümleri
            search_content_stack = QStackedWidget()
            style = QApplication.style()
            icon_dir = style.standardIcon(QStyle.StandardPixmap.SP_DirIcon)
            icon_file = style.standardIcon(QStyle.StandardPixmap.SP_FileIcon)

            model = FileListTableModel(self, set())
            model.set_nodes(filtered)
            search_list_model = QStandardItemModel(self)
            for n in filtered:
                name = n.get("name", "")
                is_dir = bool(n.get("is_dir"))
                inode = n.get("inode")
                item = QStandardItem(icon_dir if is_dir else icon_file, name)
                item.setData(inode, INODE_ROLE)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                search_list_model.appendRow(item)

            table = QTableView()
            table.setObjectName("fileTable")
            table.setSortingEnabled(True)
            table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
            table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            table.setAlternatingRowColors(True)
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            table.verticalHeader().setDefaultSectionSize(34)
            table.verticalHeader().setVisible(False)
            table.setShowGrid(False)
            table.setCursor(Qt.CursorShape.PointingHandCursor)
            table.setModel(model)
            h = table.horizontalHeader()
            for c in range(len(FileListTableModel.HEADERS)):
                h.setSectionResizeMode(c, QHeaderView.ResizeMode.Interactive)
            table.setColumnWidth(FileListTableModel.COL_SEL, 40)
            table.setColumnWidth(FileListTableModel.COL_NAME, 344)
            table.setColumnWidth(FileListTableModel.COL_INODE, 90)
            table.setColumnWidth(FileListTableModel.COL_SIZE, 92)
            table.setColumnWidth(FileListTableModel.COL_TYPE, 98)
            table.setColumnWidth(FileListTableModel.COL_MODIFIED, 172)
            table.setColumnWidth(FileListTableModel.COL_ACCESSED, 172)
            table.setColumnWidth(FileListTableModel.COL_CREATED, 172)
            table.setColumnWidth(FileListTableModel.COL_DELETED, 68)
            self._apply_file_table_palette_to(table)
            table.viewport().installEventFilter(self)
            table.verticalScrollBar().valueChanged.connect(lambda: self._thumb_timer.start(150))

            list_view = QListView()
            list_view.setModel(search_list_model)
            list_view.setViewMode(QListView.ViewMode.IconMode)
            list_view.setIconSize(QSize(96, 96))
            list_view.setSpacing(12)
            list_view.setUniformItemSizes(True)
            list_view.setWordWrap(True)
            list_view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            list_view.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
            list_view.setMovement(QListView.Movement.Static)
            list_view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
            list_view.setCursor(Qt.CursorShape.PointingHandCursor)
            list_view.viewport().installEventFilter(self)
            list_view.verticalScrollBar().valueChanged.connect(lambda: self._thumb_timer.start(150))

            def on_double_click(idx):
                if not idx.isValid():
                    return
                node = model.get_node_at(idx.row())
                if not node:
                    return
                if node.get("is_dir"):
                    self._navigate_to(node["inode"])
                    self._main_tabs.setCurrentIndex(0)
                else:
                    self._open_preview_for_nodes(model.get_nodes(), idx.row())

            table.doubleClicked.connect(on_double_click)
            list_view.doubleClicked.connect(on_double_click)

            def _on_search_selection():
                if self._main_tabs.currentWidget() is not container:
                    return
                idx = table.currentIndex() if stack.currentIndex() == 0 else list_view.currentIndex()
                if not idx.isValid():
                    return
                node = model.get_node_at(idx.row())
                if not node:
                    return
                self._update_metadata_from_inode_name(node.get("inode"), node.get("name"))
            stack = search_content_stack
            table.selectionModel().selectionChanged.connect(_on_search_selection)
            list_view.selectionModel().selectionChanged.connect(_on_search_selection)

            search_content_stack.addWidget(table)
            search_content_stack.addWidget(list_view)
            container._search_table_model = model
            container._search_list_model = search_list_model
            container._search_table = table
            container._search_list_view = list_view
            container._search_content_stack = search_content_stack

            # Görünüm combo ile senkron: Büyük simge seçiliyse list view göster + akıllı grid
            if self.view_mode_combo.currentIndex() == 1:
                search_content_stack.setCurrentIndex(1)
                list_view.setViewMode(QListView.ViewMode.IconMode)
                self._update_icon_grid_for(list_view)
                QTimer.singleShot(150, lambda: self._start_warmup_for_nodes(filtered))
            else:
                search_content_stack.setCurrentIndex(0)

            ly.addWidget(search_content_stack, 1)

        self._main_tabs.addTab(container, title)
        self._main_tabs.setCurrentIndex(self._main_tabs.count() - 1)
        self.log(f"Arama tamamlandı: \"{query}\" — {len(filtered)} sonuç gösteriliyor.")

    def _apply_file_table_palette_to(self, table: QTableView):
        """Arama sekmesi tablo stili."""
        t = DESIGN_TOKENS
        pal = QPalette()
        pal.setColor(QPalette.ColorRole.Base, _hex_to_qcolor(t["grid_style_bg"]))
        pal.setColor(QPalette.ColorRole.Window, _hex_to_qcolor(t["grid_style_bg"]))
        pal.setColor(QPalette.ColorRole.Text, _hex_to_qcolor(t["grid_style_text"]))
        pal.setColor(QPalette.ColorRole.WindowText, _hex_to_qcolor(t["grid_style_text"]))
        table.setPalette(pal)
        table.viewport().setPalette(pal)
        table.setAutoFillBackground(True)
        table.viewport().setAutoFillBackground(True)
        h = table.horizontalHeader()
        hpal = QPalette()
        hpal.setColor(QPalette.ColorRole.Button, _hex_to_qcolor(t["grid_style_header"]))
        hpal.setColor(QPalette.ColorRole.Window, _hex_to_qcolor(t["grid_style_header"]))
        hpal.setColor(QPalette.ColorRole.ButtonText, _hex_to_qcolor(t["grid_style_text"]))
        h.setPalette(hpal)
        h.setAutoFillBackground(True)

    def _open_preview_for_nodes(self, nodes: list, index: int):
        """Önizleme (node listesi + indeks)."""
        if not self.engine_session or not nodes or index < 0 or index >= len(nodes):
            return
        from frontend.preview import CollectionModel, PreviewController
        collection = CollectionModel(nodes, current_index=index)
        controller = self._preview_controller_holder.get("controller")
        if controller is None:
            controller = PreviewController(
                self.engine_session,
                self.case_dir,
                getattr(self.engine_session, "evidence_id", None) or self._initial_evidence_id or "",
                parent_widget=self,
            )
            controller.set_on_preview_close(self._on_preview_closed)
            self._preview_controller_holder["controller"] = controller
        controller.set_collection(collection)
        controller.open_at_index(index)

    def _apply_theme(self):
        """Ana tema stilleri."""
        t = DESIGN_TOKENS
        self.setStyleSheet(f"""
            *:focus {{ outline: none; }}
            QPushButton:focus, QToolButton:focus, QCheckBox:focus, QComboBox:focus, QLineEdit:focus, QSpinBox:focus, QAbstractItemView:focus {{ outline: none; }}
            QMainWindow {{ background-color: {t["bg_main"]}; }}
            QMenuBar {{ background-color: {t["bg_elevated"]}; color: {t["text_primary"]}; padding: 2px 0; font-size: 13px; }}
            QMenuBar::item {{ padding: 6px 12px; }}
            QMenuBar::item:selected {{ background-color: {t["accent_soft"]}; color: {t["accent"]}; }}
            QMenu {{ background-color: {t["bg_elevated"]}; color: {t["text_primary"]}; padding: 4px; border: 1px solid {t["border_subtle"]}; }}
            QMenu::item:selected {{ background-color: {t["accent_soft"]}; color: {t["accent"]}; }}

            QToolBar {{
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {t["toolbar_top"]}, stop:1 {t["toolbar_bottom"]});
                color: {t["text_primary"]};
                padding: 12px 14px;
                spacing: 12px;
                border: none;
                border-bottom: 1px solid {t["border_subtle"]};
            }}
            QToolBar QLabel {{ color: {t["text_muted"]}; font-size: 13px; }}
            QToolBar QLineEdit {{
                background-color: {t["bg_elevated"]};
                color: {t["text_primary"]};
                border: 1px solid {t["border_subtle"]};
                padding: 6px 10px;
                min-height: 24px;
                font-size: 13px;
            }}
            QToolBar QComboBox {{
                background-color: {t["bg_elevated"]};
                color: {t["text_primary"]};
                border: 1px solid {t["border_subtle"]};
                padding: 6px 10px;
                min-width: 100px;
                min-height: 24px;
                font-size: 13px;
            }}
            QToolBar QComboBox:hover {{ border-color: {t["accent"]}; }}
            QToolBar QComboBox::drop-down {{ border: none; }}
            QToolBar QToolButton:hover {{ background-color: {t["accent_soft"]}; color: {t["accent"]}; }}
            QToolBar QToolButton:checked {{ background-color: {t["accent_soft"]}; color: {t["accent"]}; }}
            QFrame#filterFrame {{ background-color: transparent; padding: 6px 12px; }}
            QFrame#filterFrame QCheckBox {{ color: {t["text_muted"]}; font-size: 12px; }}
            QFrame#filterFrame QCheckBox:checked {{ color: {t["text_primary"]}; }}

            QTabWidget#mainTabs {{ background-color: {t["bg_panel"]}; border: none; }}
            QTabWidget#mainTabs::pane {{
                border: none;
                border-top: 1px solid {t["border_subtle"]};
                background-color: {t["bg_panel"]};
                top: -1px;
            }}
            QTabBar::tab {{ padding: 10px 16px; margin-right: 2px; background-color: {t["bg_elevated"]}; color: {t["text_muted"]}; }}
            QTabBar::tab:selected {{ color: {t["text_primary"]}; font-weight: 600; background-color: {t["bg_panel"]}; border-bottom: 2px solid {t["accent"]}; }}
            QTabBar::tab:hover:!selected {{ background-color: {t["sidebar_hover"]}; }}

            QTreeView#sidebarTree {{
                background-color: {t["sidebar_bg"]};
                color: {t["text_primary"]};
                border: none;
                outline: none;
                font-size: 13px;
                padding: 4px 0;
            }}
            QTreeView#sidebarTree::item {{
                padding: 6px 8px 6px 6px;
                height: 32px;
                margin: 1px 8px 1px 4px;
            }}
            QTreeView#sidebarTree::item:hover {{
                background-color: {t["sidebar_hover"]};
                color: {t["text_primary"]};
            }}
            QTreeView#sidebarTree::item:selected {{
                background-color: {t["accent_soft"]};
                color: {t["text_primary"]};
            }}
            QTreeView#sidebarTree::item:selected:hover {{
                background-color: {t["accent_soft"]};
                color: {t["text_primary"]};
            }}
            QTreeView#sidebarTree::branch {{
                width: 0;
                min-width: 0;
                max-width: 0;
                padding: 0;
                margin: 0;
                border: none;
                background-color: {t["sidebar_bg"]};
            }}

            QFrame#centerPanel {{ background-color: {t["bg_panel"]}; border: none; border-left: 1px solid {t["border_separator"]}; }}

            QTableView#fileTable {{
                background-color: {t["grid_style_bg"]};
                alternate-background-color: {t["grid_style_alt"]};
                color: {t["grid_style_text"]};
                font-family: Inter, "Segoe UI", system-ui, sans-serif;
                font-size: 13px;
                font-weight: 500;
                border: none;
                gridline-color: {t["grid_style_border"]};
            }}
            QTableView#fileTable::item {{
                padding: 10px;
                color: {t["grid_style_text"]};
            }}
            QTableView#fileTable::item:hover {{
                background-color: {t["grid_style_hover"]};
                color: {t["grid_style_text"]};
            }}
            QTableView#fileTable::item:selected {{
                background-color: {t["grid_style_selection"]};
                color: {t["grid_style_text"]};
            }}
            QTableView#fileTable::item:focus {{
                outline: 2px solid {t["accent"]};
            }}

            QHeaderView {{ background-color: {t["grid_style_header"]}; }}
            QHeaderView::section {{
                background-color: {t["grid_style_header"]};
                color: {t["grid_style_text"]};
                padding: 10px 12px;
                border: none;
                border-bottom: 1px solid {t["grid_style_border"]};
                border-right: 1px solid {t["grid_style_border"]};
                font-size: 13px;
                font-weight: 600;
                font-family: Inter, "Segoe UI", system-ui, sans-serif;
            }}
            QHeaderView::section:hover {{ background-color: {t["grid_style_hover"]}; }}

            QListView {{ background-color: {t["bg_panel"]}; color: {t["text_primary"]}; }}
            QListView::item:hover {{ background-color: {t["grid_hover"]}; }}
            QListView::item:selected {{ background-color: {t["grid_selected"]}; }}

            QDockWidget {{ background-color: {t["inspector_bg"]}; }}
            QDockWidget::title {{
                background-color: {t["inspector_bg"]};
                color: {t["text_primary"]};
                padding: 12px 12px;
                border-bottom: 1px solid {t["border_separator"]};
                font-weight: 600;
                font-size: 13px;
            }}
            QDockWidget#inspectorDock {{ background-color: {t["inspector_bg"]}; }}
            QDockWidget#inspectorDock::title {{ background-color: {t["inspector_bg"]}; color: {t["text_primary"]}; }}

            QDockWidget#logDock {{ background-color: {t["log_bg"]}; }}
            QDockWidget#logDock::title {{ background-color: {t["log_bg"]}; color: {t["text_muted"]}; border-bottom: 1px solid {t["border_separator"]}; }}

            QWidget#metaPanelContainer {{
                background-color: {t["inspector_bg"]};
            }}
            QScrollArea#inspectorScroll {{
                border: none;
                background-color: {t["inspector_bg"]};
            }}
            QScrollArea#inspectorScroll > QWidget#viewport {{
                background-color: transparent;
            }}
            QScrollArea#inspectorScroll QWidget#metaPanelContainer {{
                background-color: transparent;
            }}
            QGroupBox#inspectorGroup {{
                font-size: 12px;
                color: {t["text_primary"]};
                background-color: {t["bg_panel"]};
                border: 1px solid {t["border_subtle"]};
                border-left: 2px solid {t["border_separator"]};
                margin-top: 14px;
                padding: 0 0 4px 0;
            }}
            QGroupBox#inspectorGroup:first-child {{ margin-top: 0; }}
            QGroupBox#inspectorGroup::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 14px;
                padding: 6px 10px 8px 10px;
                color: {t["text_muted"]};
                font-weight: 600;
                font-size: 11px;
                letter-spacing: 0.5px;
            }}
            QGroupBox#inspectorGroup QFormLayout QWidget {{
                min-height: 22px;
            }}
            QFormLayout QLabel {{
                color: {t["text_muted"]};
                font-weight: 500;
                font-size: 12px;
            }}
            QLabel#inspectorValue {{
                color: {t["text_primary"]};
                font-weight: 500;
                font-size: 13px;
                padding: 2px 0;
            }}
            QPushButton#metaHashBtn {{
                background-color: {t["bg_elevated"]};
                color: {t["text_primary"]};
                border: 1px solid {t["border_subtle"]};
                padding: 8px 16px;
                font-weight: 500;
                font-size: 12px;
            }}
            QPushButton#metaHashBtn:hover {{
                background-color: {t["accent_soft"]};
                border-color: {t["border_separator"]};
                color: {t["accent"]};
            }}
            QPushButton#metaHashBtn:pressed {{
                background-color: {t["accent_soft"]};
            }}
            QPushButton#metaHashBtn:disabled {{
                background-color: {t["inspector_bg"]};
                color: {t["text_muted"]};
                border-color: {t["border_subtle"]};
            }}

            QTextEdit#logPanel {{
                background-color: {t["log_bg"]};
                color: {t["log_text"]};
                border: none;
                font-family: Consolas, "Courier New", monospace;
                font-size: 12px;
            }}

            QLabel {{ color: {t["text_primary"]}; font-size: 13px; font-family: Inter, "Segoe UI", system-ui, sans-serif; }}
            QFormLayout QLabel {{ color: {t["text_muted"]}; font-weight: 500; font-size: 13px; }}
            QLabel#inspectorValue {{ color: {t["text_primary"]}; font-weight: 500; }}

            QPushButton {{
                background-color: transparent;
                color: {t["text_primary"]};
                border: 1px solid {t["border_subtle"]};
                padding: 8px 16px;
                font-size: 13px;
            }}
            QPushButton:hover {{ background-color: {t["accent_soft"]}; border-color: {t["accent"]}; color: {t["accent"]}; }}
            QPushButton:pressed {{ background-color: {t["accent_soft"]}; }}
            QPushButton#btnCancel {{ background-color: transparent; color: {t["text_primary"]}; }}

            QSplitter::handle {{ background-color: {t["border_subtle"]}; width: 1px; }}

            QScrollBar:vertical {{
                background-color: {t["scrollbar_bg"]};
                width: 10px;
                margin: 0;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background-color: {t["scrollbar_handle"]};
                min-height: 24px;
            }}
            QScrollBar::handle:vertical:hover {{ background-color: {t["scrollbar_handle_hover"]}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar:horizontal {{
                background-color: {t["scrollbar_bg"]};
                height: 10px;
                margin: 0;
                border: none;
            }}
            QScrollBar::handle:horizontal {{
                background-color: {t["scrollbar_handle"]};
                min-width: 24px;
            }}
            QScrollBar::handle:horizontal:hover {{ background-color: {t["scrollbar_handle_hover"]}; }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

            QWidget#centralWidget {{ background-color: {t["bg_main"]}; }}

            QFrame#reportProgressWrap {{
                background: {t["accent_soft"]};
                border: 1px solid {t["border_subtle"]};
                border-radius: 6px;
            }}
            QProgressBar#reportProgressBar {{
                border: 1px solid {t["border_subtle"]};
                border-radius: 4px;
                text-align: center;
                background: {t["bg_panel"]};
            }}
            QProgressBar#reportProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {t["accent"]}, stop:1 {t["accent_soft"]});
                border-radius: 3px;
            }}
        """)

    def _activity_log_path(self) -> str | None:
        """Case log yolu."""
        if not getattr(self, "case_dir", None):
            return None
        return os.path.join(self.case_dir, "activity.log")

    def log(self, text: str):
        """Log mesajı (UI + case activity.log)."""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] {text}"
        self.logger.log_signal.emit(line)
        path = self._activity_log_path()
        if path:
            try:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError:
                pass

    def _show_error_message(self, message: str):
        QMessageBox.critical(self, "Hata", message)

    def closeEvent(self, event):
        if self._thumb_manager:
            self._thumb_manager.shutdown()
            self._thumb_manager = None
        super().closeEvent(event)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Resize:
            if obj is self.file_table.viewport() or obj is self.file_list_view.viewport():
                self._thumb_timer.start(150)
                if self.view_mode_combo.currentIndex() == 1:
                    self._update_icon_grid_for(self.file_list_view)
            else:
                for i in range(1, getattr(self, "_main_tabs", None) and self._main_tabs.count() or 0):
                    w = self._main_tabs.widget(i)
                    st = getattr(w, "_search_table", None)
                    slv = getattr(w, "_search_list_view", None)
                    if st and obj is st.viewport():
                        self._thumb_timer.start(150)
                        break
                    if slv and obj is slv.viewport():
                        self._thumb_timer.start(150)
                        self._update_icon_grid_for(slv)
                        break
        return super().eventFilter(obj, event)

    def _get_path_for_inode(self, inode) -> str:
        if not self.engine_session:
            return "/"
        if inode is None:
            return "/"
        parts = []
        cur = inode
        while cur is not None:
            node = self.engine_session.snapshot.get_node(cur)
            if not node:
                break
            parts.append(node.get("name") or "")
            cur = node.get("parent_inode")
        return "/" + "/".join(reversed(parts)) if parts else "/"

    def _update_nav_buttons(self):
        self.act_back.setEnabled(bool(self._back_stack))
        self.act_forward.setEnabled(bool(self._forward_stack))
        self.act_up.setEnabled(
            self.engine_session is not None and self._current_inode is not None
        )

    def _refresh_evidence_list(self):
        """Kanıt listesini doldur."""
        self.evidence_combo.blockSignals(True)
        self.evidence_combo.clear()
        self.evidence_combo.addItem("— Case'ten kanıt seç veya yeni E01 ekle —", None)
        case_abs = os.path.abspath(self.case_dir)
        evidence_dir = os.path.join(case_abs, "evidence")
        added_ids = set()

        try:
            from backend.engine.case.case_manager import CaseManager
            from backend.engine.evidence.evidence_manager import EvidenceManager
            cm = CaseManager()
            if cm.validate_structure(case_abs):
                case_data = cm.open_case(case_abs)
                em = EvidenceManager()
                for eid in case_data.get("evidence_ids") or []:
                    if eid in added_ids:
                        continue
                    try:
                        manifest = em.load_evidence_manifest(case_abs, eid)
                        path = manifest.get("normalized_path") or manifest.get("original_e01_path") or ""
                        label = os.path.basename(path) if path else eid[:8]
                        self.evidence_combo.addItem(label, eid)
                        added_ids.add(eid)
                    except Exception:
                        self.evidence_combo.addItem(eid[:8] + "...", eid)
                        added_ids.add(eid)
        except Exception:
            pass

        if os.path.isdir(evidence_dir):
            for name in os.listdir(evidence_dir):
                if name in added_ids:
                    continue
                manifest_path = os.path.join(evidence_dir, name, "manifest.json")
                if os.path.isfile(manifest_path):
                    try:
                        import json
                        with open(manifest_path, "r", encoding="utf-8") as f:
                            manifest = json.load(f)
                        path = manifest.get("normalized_path") or manifest.get("original_e01_path") or ""
                        label = os.path.basename(path) if path else name[:8]
                        self.evidence_combo.addItem(label, name)
                        added_ids.add(name)
                    except Exception:
                        self.evidence_combo.addItem(name[:8] + "...", name)
                        added_ids.add(name)

        self.evidence_combo.setCurrentIndex(0)
        self.evidence_combo.blockSignals(False)

    def _on_case_evidence_selected(self, index: int):
        """Seçilen kanıtı yükle."""
        if index <= 0:
            return
        evidence_id = self.evidence_combo.currentData()
        if evidence_id and isinstance(evidence_id, str):
            self._start_tree_cached(evidence_id)

    def _on_menu_case_open(self):
        """Case'ten kanıt seç."""
        self._refresh_evidence_list()
        d = QDialog(self)
        d.setWindowTitle("Case'ten Kanıt Aç")
        ly = QVBoxLayout(d)
        ly.addWidget(QLabel("Kanıt seçin:"))
        combo = QComboBox()
        for i in range(1, self.evidence_combo.count()):
            combo.addItem(self.evidence_combo.itemText(i), self.evidence_combo.itemData(i))
        if combo.count() == 0:
            combo.addItem("(Kanıt yok)", None)
        ly.addWidget(combo)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(d.accept)
        btns.rejected.connect(d.reject)
        ly.addWidget(btns)
        if d.exec() == QDialog.DialogCode.Accepted and combo.count() > 0:
            eid = combo.currentData()
            if eid and isinstance(eid, str):
                self._start_tree_cached(eid)

    def _ensure_thumb_manager(self):
        if self._thumb_manager is not None or self.engine_session is None:
            return
        try:
            cache_dir = self.engine_session.evidence_manager.get_cache_dir(
                self.engine_session.case_dir, self.engine_session.evidence_id
            )
            os.makedirs(cache_dir, exist_ok=True)
            thumb_dir = os.path.join(cache_dir, "thumbnails")
            from backend.engine.thumbnail import ThumbnailManager
            self._thumb_manager = ThumbnailManager(self.engine_session, thumb_dir)
            self.log("Thumbnail yöneticisi oluşturuldu; önbellek klasörü hazır.")
        except Exception as e:
            self._thumb_manager = None
            import logging
            logging.getLogger(__name__).warning("Thumbnail manager oluşturulamadı: %s", e)

    def _on_thumbnail_ready(self, inode: int, path: str | None):
        """Büyük simge ikonunu güncelle."""
        if inode is None or not path:
            return
        if self.view_mode_combo.currentIndex() != 1:
            return
        try:
            pix = QPixmap(path)
            if pix.isNull():
                return
            # Simge boyutuna göre ölçekle
            size = 160
            if getattr(self, "_icon_size_preference", "auto") != "auto":
                size = int(self._icon_size_preference)
            elif self.file_list_view and self.file_list_view.viewMode() == QListView.ViewMode.IconMode:
                size = max(96, self.file_list_view.iconSize().width())
            scaled = pix.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            icon = QIcon(scaled)
            inode_int = int(inode)
            # Dosya listesi
            if self.file_list_list_model:
                for row in range(self.file_list_list_model.rowCount()):
                    item = self.file_list_list_model.item(row)
                    if item and int(item.data(INODE_ROLE) or -1) == inode_int:
                        item.setIcon(icon)
                        idx = self.file_list_list_model.index(row, 0)
                        self.file_list_list_model.dataChanged.emit(idx, idx, [Qt.ItemDataRole.DecorationRole])
                        if self.view_stack.currentWidget() is self.file_list_view:
                            self.file_list_view.viewport().update()
                        break
            # Arama sekmeleri
            for i in range(1, self._main_tabs.count()):
                w = self._main_tabs.widget(i)
                tmodel = getattr(w, "_search_table_model", None)
                lmodel = getattr(w, "_search_list_model", None)
                if tmodel:
                    tmodel.set_thumbnail_icon(inode_int, path)
                if lmodel:
                    for row in range(lmodel.rowCount()):
                        item = lmodel.item(row)
                        if item and int(item.data(INODE_ROLE) or -1) == inode_int:
                            item.setIcon(icon)
                            idx = lmodel.index(row, 0)
                            lmodel.dataChanged.emit(idx, idx, [Qt.ItemDataRole.DecorationRole])
                            lv = getattr(w, "_search_list_view", None)
                            if lv:
                                lv.viewport().update()
                            break
        except Exception:
            pass

    def _request_visible_thumbnails(self):
        """Görünür öğeler için thumbnail iste."""
        if self.view_mode_combo.currentIndex() != 1:
            return
        if not self.engine_session:
            return
        self._ensure_thumb_manager()
        if not self._thumb_manager:
            return

        # Arama sekmesi kontrolü
        if self._main_tabs.currentIndex() > 0:
            w = self._main_tabs.currentWidget()
            tmodel = getattr(w, "_search_table_model", None)
            list_view = getattr(w, "_search_list_view", None)
            if not tmodel or not list_view or list_view.model().rowCount() == 0:
                return
            total = tmodel.rowCount()
            vp = list_view.viewport()
        else:
            tmodel = self.file_list_model
            list_view = self.file_list_view
            total = tmodel.rowCount()
            if not total:
                return
            vp = list_view.viewport()

        visible_rows = []
        if vp and vp.rect().isValid():
            r = vp.rect()
            for y in (0, r.height() // 3, 2 * r.height() // 3, max(0, r.height() - 1)):
                for x in (0, r.width() // 2, max(0, r.width() - 1)):
                    idx = list_view.indexAt(QPoint(x, y))
                    if idx.isValid():
                        visible_rows.append(idx.row())
            if visible_rows:
                start_row = max(0, min(visible_rows) - VISIBLE_THUMB_BUFFER)
                end_row = min(total - 1, max(visible_rows) + VISIBLE_THUMB_BUFFER)
            else:
                top_left = r.topLeft()
                bottom_right = r.bottomRight()
                first_idx = list_view.indexAt(top_left)
                last_idx = list_view.indexAt(bottom_right)
                start_row = max(0, (first_idx.row() if first_idx.isValid() else 0) - VISIBLE_THUMB_BUFFER)
                end_row = min(total - 1, (last_idx.row() if last_idx.isValid() else total - 1) + VISIBLE_THUMB_BUFFER)
        else:
            start_row, end_row = 0, total - 1
        if not visible_rows and start_row == 0 and end_row == total - 1 and total > VISIBLE_THUMB_MAX_PER_REQUEST:
            sb = list_view.verticalScrollBar()
            if sb and sb.maximum() > 0:
                pct = sb.value() / max(1, sb.maximum())
                start_row = int(pct * max(0, total - VISIBLE_THUMB_MAX_PER_REQUEST))
                end_row = min(total - 1, start_row + VISIBLE_THUMB_MAX_PER_REQUEST + VISIBLE_THUMB_BUFFER)
        start_row = max(0, start_row)
        end_row = min(total - 1, end_row)
        if start_row > end_row:
            return
        requested = 0
        for row in range(start_row, end_row + 1):
            if requested >= VISIBLE_THUMB_MAX_PER_REQUEST:
                break
            node = tmodel.get_node_at(row)
            if not node:
                continue
            if node.get("category") != FileCategory.NORMAL_MEDIA:
                continue
            inode = node.get("inode")
            if inode is None:
                continue
            inode = int(inode)
            name = node.get("name", "")
            is_dir = bool(node.get("is_dir"))
            if not self._thumb_manager.should_thumbnail(inode, name, is_dir):
                continue

            def make_callback(ino):
                def cb(path):
                    QTimer.singleShot(0, lambda: self._on_thumbnail_ready(ino, path))
                return cb

            size = node.get("size")
            self._thumb_manager.request_thumbnail(
                inode, make_callback(inode), name=name, is_dir=is_dir, size=size
            )
            requested += 1

    def _load_table_for_inode(self, inode):
        if self._warmup_cancel_token:
            self._warmup_cancel_token.cancel()
            self._warmup_cancel_token = None
        self._warmup_debounce_timer.stop()

        if not self.engine_session:
            self.file_list_model.set_nodes([])
            self._sync_list_model([])
            self._current_folder_nodes = []
            self._update_empty_state_visibility()
            return
        self.log(f"Klasör yükleniyor (inode={inode})…")
        if hasattr(self.engine_session, "list_children_cached"):
            self.engine_session.list_children_cached(inode, log_callback=self.log)
        else:
            self.engine_session.list_children(inode)
        rows = self.engine_session.snapshot.get_children(inode)
        for n in rows:
            n["category"] = categorize_node(n)
        self._current_folder_nodes = list(rows)
        self._filter_show_zero_byte = self.filter_show_zero_byte.isChecked()
        self._apply_filter()
        self.log(f"Klasör yüklendi: {len(rows)} öğe listelendi.")
        if self._current_folder_nodes:
            self._warmup_debounce_timer.start(WARMUP_DEBOUNCE_MS)

    def _start_warmup(self):
        self._warmup_cancel_token = CancellationToken()
        self._warmup_run_id += 1
        run_id = self._warmup_run_id
        self._ensure_thumb_manager()
        if not self._thumb_manager or not self._current_folder_nodes:
            return

        # Cache varsa overlay gösterme
        warmup_count = WARMUP_COUNT_DEFAULT
        ready = 0
        total = 0
        for n in self._current_folder_nodes:
            if n.get("category") != FileCategory.NORMAL_MEDIA or n.get("is_dir"):
                continue
            inode = n.get("inode")
            name = n.get("name") or ""
            if not self._thumb_manager.should_thumbnail(inode, name, False):
                continue
            total += 1
            if self._thumb_manager.has_thumbnail(int(inode)):
                ready += 1
        if total > 0 and ready >= min(warmup_count, total):
            self.log(f"Thumbnail önbellekte hazır ({ready}/{total}), overlay atlandı.")
            QTimer.singleShot(0, self._request_visible_thumbnails)
            return

        self.log(f"Thumbnail hazırlığı başlatılıyor: {total} medya dosyası (hedef: {min(warmup_count, total)}).")
        self._overlay.setGeometry(self.rect())
        self._overlay.raise_()
        self._overlay.show_overlay()
        self._warmup_safety_timer.start(WARMUP_SAFETY_MS)
        token = self._warmup_cancel_token
        nodes = list(self._current_folder_nodes)
        thumb_manager = self._thumb_manager

        def progress_cb(ready_count: int, total_count: int):
            if token.is_cancelled():
                return
            self.warmup_progress_signal.emit(run_id, ready_count, total_count)

        def run():
            warmup_thumbnails_inode(
                nodes,
                thumb_manager,
                warmup_count=warmup_count,
                cancel_token=token,
                progress_callback=progress_cb,
            )

        threading.Thread(target=run, daemon=True).start()

    def _start_warmup_for_nodes(self, nodes: list):
        """Node listesinde thumbnail warmup + overlay."""
        if not nodes:
            QTimer.singleShot(0, self._request_visible_thumbnails)
            return
        self._ensure_thumb_manager()
        if not self._thumb_manager:
            QTimer.singleShot(0, self._request_visible_thumbnails)
            return
        self._warmup_cancel_token = CancellationToken()
        self._warmup_run_id += 1
        run_id = self._warmup_run_id
        warmup_count = WARMUP_COUNT_DEFAULT
        ready = 0
        total = 0
        for n in nodes:
            if n.get("category") != FileCategory.NORMAL_MEDIA or n.get("is_dir"):
                continue
            inode = n.get("inode")
            name = n.get("name") or ""
            if not self._thumb_manager.should_thumbnail(inode, name, False):
                continue
            total += 1
            if self._thumb_manager.has_thumbnail(int(inode)):
                ready += 1
        if total > 0 and ready >= min(warmup_count, total):
            self.log(f"Thumbnail önbellekte hazır ({ready}/{total}), overlay atlandı.")
            QTimer.singleShot(0, self._request_visible_thumbnails)
            return
        self.log(f"Thumbnail hazırlığı başlatılıyor: {total} medya dosyası (hedef: {min(warmup_count, total)}).")
        self._overlay.setGeometry(self.rect())
        self._overlay.raise_()
        self._overlay.show_overlay()
        self._warmup_safety_timer.start(WARMUP_SAFETY_MS)
        token = self._warmup_cancel_token
        thumb_manager = self._thumb_manager

        def progress_cb(ready_count: int, total_count: int):
            if token.is_cancelled():
                return
            self.warmup_progress_signal.emit(run_id, ready_count, total_count)

        def run():
            warmup_thumbnails_inode(
                list(nodes),
                thumb_manager,
                warmup_count=warmup_count,
                cancel_token=token,
                progress_callback=progress_cb,
            )

        threading.Thread(target=run, daemon=True).start()

    def _on_icon_size_changed(self, index: int):
        """Simge boyutu değişti, listeleri güncelle."""
        if index == 0:
            self._icon_size_preference = "auto"
        else:
            sizes = (96, 128, 160, 200)
            self._icon_size_preference = sizes[index - 1] if index - 1 < len(sizes) else 160
        if self.view_mode_combo.currentIndex() != 1:
            return
        self._update_icon_grid_for(self.file_list_view)
        for i in range(1, getattr(self, "_main_tabs", None) and self._main_tabs.count() or 0):
            w = self._main_tabs.widget(i)
            lv = getattr(w, "_search_list_view", None)
            if lv:
                self._update_icon_grid_for(lv)
        # Thumbnail boyutunu güncelle
        QTimer.singleShot(0, self._request_visible_thumbnails)

    def _update_icon_grid_for(self, list_view: QListView):
        """Büyük simge hücre boyutu."""
        if not list_view or list_view.viewMode() != QListView.ViewMode.IconMode:
            return
        vp = list_view.viewport()
        if not vp:
            return
        r = vp.rect()
        w = max(260, r.width())
        spacing = 12
            # Dosya adı alanı
        text_height = 44
        if self._icon_size_preference == "auto":
            min_cell_w = 120
            max_cell_w = 240
            cols = max(2, (w + spacing) // (min_cell_w + spacing))
            cell_w = (w - spacing * (cols + 1)) // cols
            cell_w = max(min_cell_w, min(max_cell_w, cell_w))
            icon_size = min(200, max(96, cell_w - 32))
        else:
            icon_size = int(self._icon_size_preference)
            # Hücre genişliği
            min_cell_w = icon_size + 48
            cols = max(2, (w + spacing) // (min_cell_w + spacing))
            cell_w = (w - spacing * (cols + 1)) // cols
            cell_w = max(min_cell_w, cell_w)
        cell_h = icon_size + text_height
        cell_w = max(cell_w, 80)
        cell_h = max(cell_h, 100)
        list_view.setSpacing(spacing)
        list_view.setIconSize(QSize(icon_size, icon_size))
        list_view.setGridSize(QSize(cell_w + spacing, cell_h))
        list_view.setWordWrap(True)
        list_view.setUniformItemSizes(True)

    def _on_warmup_safety_timeout(self):
        if self._overlay.isVisible():
            self.log("Thumbnail hazırlığı zaman aşımı (6 sn); overlay kapatıldı, oluşan önizlemeler gösteriliyor.")
            self._overlay.hide_overlay()
            QTimer.singleShot(0, self._request_visible_thumbnails)

    def _on_warmup_progress(self, run_id: int, ready: int, total: int):
        if run_id != self._warmup_run_id:
            return
        self._overlay.update_progress(ready, total)
        if ready <= 1 and total > 0:
            QApplication.processEvents()
        if total == 0:
            self._warmup_safety_timer.stop()
            self._overlay.hide_overlay()
            QTimer.singleShot(0, self._request_visible_thumbnails)
            return
        if ready >= WARMUP_COUNT_DEFAULT or ready >= total:
            self._warmup_safety_timer.stop()
            self.log(f"Thumbnail hazırlığı tamamlandı: {ready}/{total} (başarılı veya atlanan).")
            self._overlay.hide_overlay()
            QTimer.singleShot(0, self._request_visible_thumbnails)

    def _on_filter_toggled(self):
        self._filter_show_zero_byte = self.filter_show_zero_byte.isChecked()
        self.log(f"Filtre: 0 byte göster={'evet' if self._filter_show_zero_byte else 'hayır'}.")
        self._apply_filter()

    def _node_type(self, node: dict) -> str:
        if node.get("is_dir"):
            return "Klasör"
        return _extension_from_name(node.get("name", ""))

    def _apply_filter(self):
        """Filtrelere göre listeyi güncelle."""
        if not self._current_folder_nodes:
            self.file_list_model.set_nodes([])
            self._sync_list_model([])
            self._update_empty_state_visibility()
            return
        show_zero = self._filter_show_zero_byte
        filtered = [
            n for n in self._current_folder_nodes
            if n.get("category") != FileCategory.ZERO_BYTE or show_zero
        ]
        if self._filter_types_allowed is not None:
            filtered = [n for n in filtered if self._node_type(n) in self._filter_types_allowed]
        self.file_list_model.set_nodes(filtered)
        self._sync_list_model(filtered)
        self._update_empty_state_visibility()
        self.log(f"Liste filtrelendi: {len(filtered)} öğe gösteriliyor.")

    def _on_type_filter_clicked(self):
        """Tür filtresi seçim penceresi."""
        nodes = self._current_folder_nodes or []
        types_set = set()
        for n in nodes:
            if n.get("category") == FileCategory.ZERO_BYTE and not self._filter_show_zero_byte:
                continue
            types_set.add(self._node_type(n))
        types_list = sorted(types_set, key=lambda x: (0 if x == "Klasör" else 1, x))
        if not types_list:
            self.log("Tür filtresi: bu klasörde öğe yok.")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Tür filtresi")
        dlg.setMinimumWidth(320)
        ly = QVBoxLayout(dlg)
        ly.addWidget(QLabel("Gösterilecek türleri seçin (boş bırakırsanız tümü gösterilir):"))
        checkboxes = {}
        for t in types_list:
            cb = QCheckBox(t)
            if self._filter_types_allowed is None:
                cb.setChecked(True)
            else:
                cb.setChecked(t in self._filter_types_allowed)
            checkboxes[t] = cb
            ly.addWidget(cb)
        def all_none():
            for cb in checkboxes.values():
                cb.setChecked(False)
        def all_checked():
            for cb in checkboxes.values():
                cb.setChecked(True)
        btn_ly = QHBoxLayout()
        btn_ly.addStretch()
        btn_all = QPushButton("Tümünü seç")
        btn_all.clicked.connect(all_checked)
        btn_none = QPushButton("Hiçbirini seçme")
        btn_none.clicked.connect(all_none)
        btn_ly.addWidget(btn_all)
        btn_ly.addWidget(btn_none)
        ly.addLayout(btn_ly)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        ly.addWidget(bb)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        selected = {t for t, cb in checkboxes.items() if cb.isChecked()}
        if len(selected) == len(types_list) or not selected:
            self._filter_types_allowed = None
            self.btn_type_filter.setText("Tüm türler")
            self.log("Tür filtresi: tümü gösteriliyor.")
        else:
            self._filter_types_allowed = selected
            self.btn_type_filter.setText(f"{len(selected)} tür seçili")
            self.log(f"Tür filtresi: {len(selected)} tür gösteriliyor.")
        self._apply_filter()

    def _sync_list_model(self, nodes: list):
        """Liste görünümünü ikon+isim ile doldur."""
        try:
            self.file_list_list_model.itemChanged.disconnect(self._on_list_item_check_changed)
        except Exception:
            pass
        self.file_list_list_model.removeRows(0, self.file_list_list_model.rowCount())
        style = QApplication.style()
        icon_dir = style.standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        icon_file = style.standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        checked = getattr(self, "_export_checked_inodes", set())
        for n in (nodes or []):
            name = n.get("name", "")
            is_dir = bool(n.get("is_dir"))
            inode = n.get("inode")
            item = QStandardItem(icon_dir if is_dir else icon_file, name)
            item.setData(inode, INODE_ROLE)
            item.setFlags((item.flags() & ~Qt.ItemFlag.ItemIsEditable) | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckable(True)
            item.setCheckState(Qt.CheckState.Checked if (inode is not None and inode in checked) else Qt.CheckState.Unchecked)
            self.file_list_list_model.appendRow(item)
        self.file_list_list_model.itemChanged.connect(self._on_list_item_check_changed)

    def _on_list_item_check_changed(self, item: QStandardItem):
        """Seçim değişince senkronize et."""
        if not item or not item.isCheckable():
            return
        ino = item.data(INODE_ROLE)
        if ino is None:
            return
        if item.checkState() == Qt.CheckState.Checked:
            self._export_checked_inodes.add(ino)
        else:
            self._export_checked_inodes.discard(ino)
        self._update_export_file_button_state()
        if self.file_list_model:
            for row in range(self.file_list_model.rowCount()):
                node = self.file_list_model.get_node_at(row)
                if node and node.get("inode") == ino:
                    idx = self.file_list_model.index(row, FileListTableModel.COL_SEL)
                    self.file_list_model.dataChanged.emit(idx, idx, [Qt.ItemDataRole.CheckStateRole])
                    break

    def _on_view_mode_changed(self, index: int):
        if index == 0:
            self._icon_size_label.setVisible(False)
            self._icon_size_spacer.setVisible(False)
            self.icon_size_combo.setVisible(False)
            self.view_stack.setCurrentWidget(self.file_table)
            # Arama sekmelerinde de Detay göster
            for i in range(1, self._main_tabs.count()):
                w = self._main_tabs.widget(i)
                stack = getattr(w, "_search_content_stack", None)
                if stack:
                    stack.setCurrentIndex(0)
        else:
            self._icon_size_label.setVisible(True)
            self._icon_size_spacer.setVisible(True)
            self.icon_size_combo.setVisible(True)
            self.view_stack.setCurrentWidget(self.file_list_view)
            self.file_list_view.setViewMode(QListView.ViewMode.IconMode)
            self._update_icon_grid_for(self.file_list_view)
            # Arama sekmelerinde Büyük simge
            for i in range(1, self._main_tabs.count()):
                w = self._main_tabs.widget(i)
                stack = getattr(w, "_search_content_stack", None)
                lv = getattr(w, "_search_list_view", None)
                if stack and lv:
                    stack.setCurrentIndex(1)
                    lv.setViewMode(QListView.ViewMode.IconMode)
                    self._update_icon_grid_for(lv)
            # Arama sekmesindeyse thumbnail warmup
            if self._main_tabs.currentIndex() > 0:
                w = self._main_tabs.currentWidget()
                tmodel = getattr(w, "_search_table_model", None)
                if tmodel and tmodel.rowCount() > 0:
                    nodes = tmodel.get_nodes()
                    QTimer.singleShot(100, lambda: self._start_warmup_for_nodes(nodes))
            else:
                self._thumb_timer.start(150)

    def _on_list_double_clicked(self, index):
        if not index.isValid():
            return
        row = index.row()
        node = self.file_list_model.get_node_at(row)
        if not node:
            return
        if node.get("is_dir"):
            self._navigate_to(node["inode"])
        else:
            self._open_preview_at_index(row)

    def _open_preview_at_index(self, index: int):
        """Tam ekran önizleme (sol/sağ gezinme)."""
        if not self.engine_session:
            return
        nodes = self.file_list_model.get_nodes()
        if not nodes or index < 0 or index >= len(nodes):
            return
        from frontend.preview import CollectionModel, PreviewController
        collection = CollectionModel(nodes, current_index=index)
        controller = self._preview_controller_holder.get("controller")
        if controller is None:
            controller = PreviewController(
                self.engine_session,
                self.case_dir,
                getattr(self.engine_session, "evidence_id", None) or self._initial_evidence_id or "",
                parent_widget=self,
            )
            controller.set_on_preview_close(self._on_preview_closed)
            self._preview_controller_holder["controller"] = controller
        controller.set_collection(collection)
        controller.open_at_index(index)

    def _on_preview_closed(self, index: int):
        """Önizleme kapanınca odaklan."""
        nodes = self.file_list_model.get_nodes() if self.file_list_model else []
        if not nodes or index < 0 or index >= len(nodes):
            return
        self.file_table.setCurrentIndex(self.file_list_model.index(index, 0))
        self.file_table.scrollTo(self.file_list_model.index(index, 0), QAbstractItemView.ScrollHint.PositionAtCenter)
        if self.file_list_list_model.rowCount() > index:
            idx = self.file_list_list_model.index(index, 0)
            self.file_list_view.setCurrentIndex(idx)
            self.file_list_view.scrollTo(idx, QAbstractItemView.ScrollHint.PositionAtCenter)
        if self.view_stack.currentWidget() is self.file_table:
            self.file_table.setFocus()
        else:
            self.file_list_view.setFocus()

    def _navigate_to(self, inode, add_to_history: bool = True):
        if not self.engine_session and inode is not None:
            return
        if add_to_history and not self._navigate_from_history:
            self._back_stack.append(self._current_inode)
            self._forward_stack.clear()
        self._navigate_from_history = False
        self._current_inode = inode
        self.path_bar.setText(self._get_path_for_inode(inode))
        self.log(f"Gidiliyor: inode={inode} — {self._get_path_for_inode(inode) or '/'}")
        self._load_table_for_inode(inode)
        self._update_nav_buttons()
        self._sync_tree_selection_to_inode(inode)

    def _sync_tree_selection_to_inode(self, inode):
        if not self.model or inode is None:
            self.tree.clearSelection()
            return
        idx = self._find_index_for_inode(self.model.invisibleRootItem(), inode)
        if idx.isValid():
            self.tree.selectionModel().select(idx, self.tree.selectionModel().SelectionFlag.SelectCurrent)
            self.tree.scrollTo(idx)

    def _find_index_for_inode(self, parent_item, inode):
        for r in range(parent_item.rowCount()):
            child = parent_item.child(r, 0)
            if not child:
                continue
            if child.data(INODE_ROLE) == inode:
                return self.model.indexFromItem(child)
            idx = self._find_index_for_inode(child, inode)
            if idx.isValid():
                return idx
        return QModelIndex()

    def _on_back(self):
        if not self._back_stack:
            return
        self._forward_stack.append(self._current_inode)
        prev = self._back_stack.pop()
        self._navigate_from_history = True
        self._navigate_to(prev, add_to_history=False)

    def _on_forward(self):
        if not self._forward_stack:
            return
        self._back_stack.append(self._current_inode)
        nxt = self._forward_stack.pop()
        self._navigate_from_history = True
        self._navigate_to(nxt, add_to_history=False)

    def _on_up(self):
        if self._current_inode is None:
            return
        node = self.engine_session.snapshot.get_node(self._current_inode)
        if not node:
            return
        parent = node.get("parent_inode")
        self._navigate_to(parent)

    def _on_refresh(self):
        self._load_table_for_inode(self._current_inode)

    def _on_menu_toggle_tree(self):
        if not getattr(self, "_main_splitter", None):
            return
        want_open = self._act_menu_tree.isChecked()
        sizes = self._main_splitter.sizes()
        tree_w = sizes[0]
        if want_open:
            if tree_w < 80:
                tree_w = getattr(self, "_saved_tree_width", 220)
                self._saved_tree_width = tree_w
            self._main_splitter.setSizes([tree_w, sizes[1], sizes[2]])
            self._main_splitter.widget(0).setVisible(True)
        else:
            if tree_w > 0:
                self._saved_tree_width = tree_w
            self._main_splitter.setSizes([0, sizes[1], sizes[2]])
            self._main_splitter.widget(0).setVisible(False)

    def _on_main_splitter_moved(self, pos: int, index: int):
        if index != 0:
            return
        sizes = self._main_splitter.sizes()
        tree_visible = sizes[0] > 50
        if getattr(self, "_act_menu_tree", None):
            self._act_menu_tree.blockSignals(True)
            self._act_menu_tree.setChecked(tree_visible)
            self._act_menu_tree.blockSignals(False)
        if tree_visible and sizes[0] > 0:
            self._saved_tree_width = sizes[0]

    def _on_meta_splitter_moved(self, pos: int, index: int):
        if index != 1:
            return
        sizes = self._meta_splitter.sizes()
        meta_visible = sizes[1] > 30
        self._meta_open = meta_visible
        if getattr(self, "_act_menu_meta", None):
            self._act_menu_meta.blockSignals(True)
            self._act_menu_meta.setChecked(meta_visible)
            self._act_menu_meta.blockSignals(False)

    def _on_menu_toggle_meta(self):
        if not getattr(self, "_meta_splitter", None):
            return
        want_open = self._act_menu_meta.isChecked()
        if getattr(self, "_meta_open", True) == want_open:
            return
        self._meta_open = want_open
        if self._meta_open:
            self._meta_scroll.setVisible(True)
            self._meta_splitter.setSizes([48, 280])
            self._main_splitter.setSizes([self._main_splitter.sizes()[0], self._main_splitter.sizes()[1], 328])
        else:
            self._meta_splitter.setSizes([48, 0])
            self._meta_scroll.setVisible(False)
            self._main_splitter.setSizes([self._main_splitter.sizes()[0], self._main_splitter.sizes()[1], 48])

    def _on_menu_toggle_log(self):
        if not getattr(self, "_log_splitter", None):
            return
        want_open = self._act_menu_log.isChecked()
        if getattr(self, "_log_open", True) == want_open:
            return
        self._log_open = want_open
        s = self._outer_splitter.sizes()
        total = s[0] + s[1]
        if total <= 0:
            total = max(self._outer_splitter.height(), 400)
        tab_h = getattr(self, "_log_tab_h", 28)
        default_content = getattr(self, "_log_content_default", 150)
        if self._log_open:
            self._log_box_wrap.setMinimumHeight(getattr(self, "_log_content_min", 100))
            self._log_box_wrap.setVisible(True)
            self._log_splitter.setSizes([tab_h, default_content])
            self._log_tab_btn.setText("Günlük  ▼")
            self._outer_splitter.setSizes([max(1, total - tab_h - default_content), tab_h + default_content])
        else:
            self._log_box_wrap.setMinimumHeight(0)
            self._log_splitter.setSizes([tab_h, 0])
            self._log_box_wrap.setVisible(False)
            self._log_tab_btn.setText("Günlük  ▲")
            self._outer_splitter.setSizes([max(1, total - tab_h), tab_h])

    def _on_meta_tab_clicked(self):
        if not getattr(self, "_meta_splitter", None):
            return
        self._meta_open = not getattr(self, "_meta_open", True)
        if self._meta_open:
            self._meta_scroll.setVisible(True)
            self._meta_splitter.setSizes([48, 280])
            self._main_splitter.setSizes([self._main_splitter.sizes()[0], self._main_splitter.sizes()[1], 328])
        else:
            self._meta_splitter.setSizes([48, 0])
            self._meta_scroll.setVisible(False)
            self._main_splitter.setSizes([self._main_splitter.sizes()[0], self._main_splitter.sizes()[1], 48])
        if getattr(self, "_act_menu_meta", None):
            self._act_menu_meta.blockSignals(True)
            self._act_menu_meta.setChecked(self._meta_open)
            self._act_menu_meta.blockSignals(False)

    def _on_log_tab_clicked(self):
        if not getattr(self, "_log_splitter", None):
            return
        self._log_open = not getattr(self, "_log_open", True)
        s = self._outer_splitter.sizes()
        total = s[0] + s[1]
        if total <= 0:
            total = max(self._outer_splitter.height(), 400)
        tab_h = getattr(self, "_log_tab_h", 28)
        default_content = getattr(self, "_log_content_default", 150)
        if self._log_open:
            self._log_box_wrap.setMinimumHeight(getattr(self, "_log_content_min", 100))
            self._log_box_wrap.setVisible(True)
            self._log_splitter.setSizes([tab_h, default_content])
            self._log_tab_btn.setText("Günlük  ▼")
            self._outer_splitter.setSizes([max(1, total - tab_h - default_content), tab_h + default_content])
        else:
            self._log_box_wrap.setMinimumHeight(0)
            self._log_splitter.setSizes([tab_h, 0])
            self._log_box_wrap.setVisible(False)
            self._log_tab_btn.setText("Günlük  ▲")
            self._outer_splitter.setSizes([max(1, total - tab_h), tab_h])
        if getattr(self, "_act_menu_log", None):
            self._act_menu_log.blockSignals(True)
            self._act_menu_log.setChecked(self._log_open)
            self._act_menu_log.blockSignals(False)

    def _on_tree_clicked(self, index: QModelIndex):
        """Ağaç tek tıklama."""
        if getattr(self, "_main_tabs", None) and self._main_tabs.currentIndex() > 0:
            self._main_tabs.setCurrentIndex(0)

    def _on_tree_double_clicked(self, index: QModelIndex):
        """Ağaç çift tıklama: klasöre git."""
        if getattr(self, "_main_tabs", None) and self._main_tabs.currentIndex() > 0:
            self._main_tabs.setCurrentIndex(0)
        if not index.isValid() or not self.model:
            return
        item = self.model.itemFromIndex(index)
        if not item:
            return
        inode = item.data(INODE_ROLE)
        if inode == -1:
            return  # geçici
        if not item.data(IS_DIR_ROLE):
            return
        # Sanal düğümler: sadece genişlet (E01/Partition), Volume ise genişlet ve köke git
        if inode in (TREE_INODE_E01, TREE_INODE_PARTITION):
            self.tree.expand(index)
            return
        if inode == TREE_INODE_VOLUME:
            self.tree.expand(index)
            self._navigate_to(None)
            return
        # Gerçek klasör: genişlet ve bu klasöre git
        self.tree.expand(index)
        self._navigate_to(inode)

    def _on_table_double_clicked(self, index: QModelIndex):
        if not index.isValid():
            return
        node = self.file_list_model.get_node_at(index.row())
        if not node:
            return
        if node.get("is_dir"):
            self._navigate_to(node["inode"])
        else:
            self._open_preview_at_index(index.row())

    def _show_metadata_for_selection(self):
        """Seçili öğe için metadata yenile."""
        self._update_metadata_from_inode_name(self._selected_inode, self._selected_name or "")

    def _clear_meta_panel(self, message: str = ""):
        for lb in (
            self.meta_name, self.meta_inode, self.meta_type, self.meta_size,
            self.meta_mtime, self.meta_atime, self.meta_ctime, self.meta_crtime,
            self.meta_deleted, self.meta_md5, self.meta_sha1,
            self.meta_gps, self.meta_make, self.meta_model, self.meta_datetime_original,
            self.meta_software, self.meta_image_size,
        ):
            lb.setText("N/A")
        if message:
            self.meta_name.setText(message)
            self._selected_inode = None
            self._selected_is_dir = True
        self._update_export_file_button_state()

    def _get_checked_file_nodes(self) -> list[tuple]:
        """Dışa aktarma için işaretlenen dosyaları döndür."""
        if not self.engine_session or not self.file_list_model:
            return []
        out = []
        for row in range(self.file_list_model.rowCount()):
            node = self.file_list_model.get_node_at(row)
            if not node or node.get("is_dir"):
                continue
            ino = node.get("inode")
            if ino is not None and ino in getattr(self, "_export_checked_inodes", set()):
                out.append((ino, node.get("name", "")))
        return out

    def _on_file_list_data_changed(self, top_left, bottom_right, roles):
        if top_left.column() <= FileListTableModel.COL_SEL <= bottom_right.column():
            self._update_export_file_button_state()

    def _update_export_file_button_state(self):
        """Dışa aktarma butonu durumu."""
        self.btn_export_file.setEnabled(
            bool(getattr(self, "engine_session", None) and len(self._get_checked_file_nodes()) > 0)
        )

    def _on_select_all_export_clicked(self):
        """Tümünü seç."""
        if not self.file_list_model:
            return
        for row in range(self.file_list_model.rowCount()):
            node = self.file_list_model.get_node_at(row)
            if node and node.get("inode") is not None:
                self._export_checked_inodes.add(node["inode"])
        self._refresh_export_check_column()
        self._update_export_file_button_state()
        self.log("Tümünü seç: tüm öğeler dışarı aktarma için işaretlendi.")

    def _on_clear_export_selection_clicked(self):
        """Seçimi temizle."""
        self._export_checked_inodes.clear()
        self._refresh_export_check_column()
        self._update_export_file_button_state()
        self.log("Seçim temizlendi.")

    def _refresh_export_check_column(self):
        """Seç sütununu yenile."""
        if not self.file_list_model or self.file_list_model.rowCount() == 0:
            return
        top = self.file_list_model.index(0, FileListTableModel.COL_SEL)
        bottom = self.file_list_model.index(self.file_list_model.rowCount() - 1, FileListTableModel.COL_SEL)
        self.file_list_model.dataChanged.emit(top, bottom, [Qt.ItemDataRole.CheckStateRole])
        try:
            self.file_list_list_model.itemChanged.disconnect(self._on_list_item_check_changed)
        except Exception:
            pass
        for row in range(self.file_list_list_model.rowCount()):
            item = self.file_list_list_model.item(row)
            if item and item.isCheckable():
                ino = item.data(INODE_ROLE)
                item.setCheckState(Qt.CheckState.Checked if (ino is not None and ino in self._export_checked_inodes) else Qt.CheckState.Unchecked)
        self.file_list_list_model.itemChanged.connect(self._on_list_item_check_changed)

    def _get_tag_color_for_inode(self, inode) -> str | None:
        """İnode'un etiket rengi."""
        if inode is None:
            return None
        eid = getattr(self.engine_session, "evidence_id", None) if self.engine_session else None
        return tag_manager.get_tag_color_for_inode(eid or "", inode)

    def _register_tag_shortcuts(self):
        """Etiket kısayollarını kaydet."""
        for sc in self._tag_shortcuts:
            sc.setEnabled(False)
            sc.deleteLater()
        self._tag_shortcuts.clear()
        for d in tag_manager.load_definitions():
            shortcut_str = (d.get("shortcut") or "").strip()
            if not shortcut_str:
                continue
            try:
                seq = QKeySequence(shortcut_str)
                if seq.isEmpty():
                    continue
            except Exception:
                continue
            tag_name = d.get("name", "")
            if not tag_name:
                continue
            sc = QShortcut(seq, self)
            sc.activated.connect(lambda t=tag_name: self._on_tag_shortcut_activated(t))
            self._tag_shortcuts.append(sc)

    def _on_tag_shortcut_activated(self, tag_name: str):
        """Kısayol ile etiket ekle/kaldır."""
        if self._main_tabs.currentIndex() != 0 or not self.engine_session:
            return
        inode = None
        if self.view_stack.currentIndex() == 0:
            idx = self.file_table.currentIndex()
            if idx.isValid():
                node = self.file_list_model.get_node_at(idx.row())
                if node:
                    inode = node.get("inode")
        else:
            idx = self.file_list_view.currentIndex()
            if idx.isValid():
                node = self.file_list_model.get_node_at(idx.row())
                if node:
                    inode = node.get("inode")
        if inode is None:
            self.log("Etiket: önce bir öğe seçin.")
            return
        evidence_id = getattr(self.engine_session, "evidence_id", None) or ""
        path_str = self._get_path_for_inode(inode) or ""
        if tag_manager.has_assignment(evidence_id, inode, tag_name):
            tag_manager.remove_assignment(evidence_id, inode, tag_name)
            self.log(f"Etiket kaldırıldı: etiket=\"{tag_name}\", inode={inode}, yol={path_str}")
        else:
            tag_manager.add_assignment(evidence_id, int(inode), tag_name, "")
            self.log(f"Etiket eklendi: etiket=\"{tag_name}\", inode={inode}, yol={path_str}")
        self.file_table.viewport().update()
        self.file_list_view.viewport().update()
        if self._main_tabs.currentIndex() == 1:
            self._refresh_tags_tab()

    def _on_export_list_clicked(self):
        """Listeyi CSV'ye aktar."""
        if not self.engine_session or not self.file_list_model:
            self.log("Dışarı aktarma: önce kanıt seçin ve klasör açın.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Listeyi CSV olarak kaydet", "", "CSV (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f, delimiter=";")
                w.writerow(["Yol", "Ad", "Inode", "Boyut", "Tür", "Değiştirilme", "Erişim", "Oluşturulma", "Silindi"])
                for row in range(self.file_list_model.rowCount()):
                    node = self.file_list_model.get_node_at(row)
                    if not node:
                        continue
                    ino = node.get("inode")
                    path_str = self._get_path_for_inode(ino) or ""
                    name = node.get("name", "")
                    size = node.get("size") or 0
                    if node.get("is_dir"):
                        type_str = "Klasör"
                    else:
                        type_str = _extension_from_name(name)
                    w.writerow([
                        path_str, name, ino, size, type_str,
                        node.get("mtime"), node.get("atime"), node.get("crtime") or node.get("ctime"),
                        "Evet" if node.get("deleted") else "Hayır",
                    ])
            self.log(f"Liste dışa aktarıldı: {path}")
        except Exception as e:
            self.log(f"Dışarı aktarma hatası: {e}")

    def _on_report_clicked(self):
        """Bu klasör raporu (HTML/PDF)."""
        if not self.engine_session or not self.file_list_model:
            self.log("Raporlama: önce kanıt seçin ve klasör açın.")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Bölüm Raporu — Bu Klasör")
        ly = QVBoxLayout(dlg)
        ly.addWidget(QLabel("Rapor formatı:"))
        format_html = QCheckBox("HTML (tarayıcıda açılabilir)")
        format_html.setChecked(True)
        format_pdf = QCheckBox("PDF")
        format_pdf.setChecked(True)
        ly.addWidget(format_html)
        ly.addWidget(format_pdf)
        extract_files = QCheckBox("Dosyaları rapor klasörüne çıkar (hash hesapla, linklerle AXIOM tarzı)")
        extract_files.setChecked(True)
        ly.addWidget(extract_files)
        only_tagged = QCheckBox("Sadece etiketlileri raporla ve etiketli dosyaları dışarı çıkar")
        only_tagged.setToolTip("Rapor ve dosya çıkarma yalnızca etiket atanmış öğeleri kapsar")
        ly.addWidget(only_tagged)
        ly.addWidget(QLabel("Rapor, case/reports/ altında oluşturulacaktır."))
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        ly.addWidget(bb)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        want_html = format_html.isChecked()
        want_pdf = format_pdf.isChecked()
        if not want_html and not want_pdf:
            self.log("En az bir format seçin.")
            return
        report_dir = self._create_report_folder()
        if not report_dir:
            return
        only_tagged = only_tagged.isChecked()
        tagged_inodes = set()
        if only_tagged:
            evidence_id = getattr(self.engine_session, "evidence_id", None) or ""
            for a in tag_manager.get_assignments_for_evidence(evidence_id):
                if a.get("inode") is not None:
                    tagged_inodes.add(int(a.get("inode")))
        extracted_map = {}
        if extract_files.isChecked():
            extracted_map = self._extract_section_files_to_report(report_dir, only_tagged=only_tagged, tagged_inodes=tagged_inodes)
        html_content = self._build_report_html(extracted_map=extracted_map, only_tagged=only_tagged, tagged_inodes=tagged_inodes)
        if want_html:
            index_path = os.path.join(report_dir, "index.html")
            try:
                with open(index_path, "w", encoding="utf-8") as f:
                    f.write(html_content)
                self.log(f"Rapor (HTML): {index_path}")
            except Exception as e:
                self.log(f"Rapor HTML yazılamadı: {e}")
        if want_pdf:
            pdf_path = os.path.join(report_dir, "report.pdf")
            try:
                self._html_to_pdf(html_content, pdf_path)
                self.log(f"Rapor (PDF): {pdf_path}")
            except Exception as e:
                self.log(f"Rapor PDF oluşturulamadı: {e}")
        self.log(f"Rapor klasörü: {report_dir}")

    def _extract_section_files_to_report(self, report_dir: str, only_tagged: bool = False, tagged_inodes: set | None = None) -> dict:
        """Listedeki dosyaları çıkar, hash hesapla."""
        extracted = os.path.join(report_dir, "extracted")
        os.makedirs(extracted, exist_ok=True)
        out = {}
        tagged = tagged_inodes if tagged_inodes is not None else set()
        for row in range(self.file_list_model.rowCount()):
            node = self.file_list_model.get_node_at(row)
            if not node or node.get("is_dir"):
                continue
            ino = node.get("inode")
            if ino is None:
                continue
            if only_tagged and int(ino) not in tagged:
                continue
            path_str = self._get_path_for_inode(ino) or ""
            safe_rel = path_str.replace("\\", "/").strip("/").replace("../", "_/") or "dosya"
            safe_rel = "".join(c if c.isalnum() or c in "/._-" else "_" for c in safe_rel)
            target_path = os.path.join(extracted, safe_rel)
            try:
                data = self.engine_session.read_file_content(ino, max_size=REPORT_EXTRACT_MAX_BYTES)
                if data is None:
                    continue
                os.makedirs(os.path.dirname(target_path) or ".", exist_ok=True)
                with open(target_path, "wb") as f:
                    f.write(data)
                hashes = self.engine_session.get_hashes(ino)
                md5 = (hashes or {}).get("md5") or "—"
                sha1 = (hashes or {}).get("sha1") or "—"
                rel_link = "extracted/" + safe_rel.replace("\\", "/")
                out[int(ino)] = {"rel_path": rel_link, "md5": md5, "sha1": sha1}
                self.log(f"Çıkarıldı: {safe_rel[:60]}...")
            except Exception as e:
                self.log(f"Çıkarma hatası {path_str}: {e}")
        return out

    def _on_full_report_clicked(self):
        """Genel rapor (tüm imaj, arka planda)."""
        if not self.engine_session:
            self.log("Genel Raporlama: önce kanıt seçin.")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Genel Raporlama")
        ly = QVBoxLayout(dlg)
        ly.addWidget(QLabel("İmaj dosyasındaki tüm dosyalar dışarı çıkarılacak, hash hesaplanacak ve rapor oluşturulacak. İşlem arka planda çalışır."))
        ly.addWidget(QLabel("Format:"))
        format_html = QCheckBox("HTML")
        format_html.setChecked(True)
        format_pdf = QCheckBox("PDF")
        ly.addWidget(format_html)
        ly.addWidget(format_pdf)
        extract_all = QCheckBox("Tüm dosyaları çıkar (hash ile); rapor linkleri")
        extract_all.setChecked(True)
        ly.addWidget(extract_all)
        only_tagged_full = QCheckBox("Sadece etiketlileri raporla ve etiketli dosyaları dışarı çıkar")
        only_tagged_full.setToolTip("Rapor ve dosya çıkarma yalnızca etiket atanmış öğeleri kapsar")
        ly.addWidget(only_tagged_full)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        ly.addWidget(bb)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        report_dir = self._create_report_folder()
        if not report_dir:
            return
        want_html = format_html.isChecked()
        want_pdf = format_pdf.isChecked()
        do_extract = extract_all.isChecked()
        only_tagged_full_val = only_tagged_full.isChecked()
        tagged_inodes_full = set()
        if only_tagged_full_val:
            evidence_id = getattr(self.engine_session, "evidence_id", None) or ""
            for a in tag_manager.get_assignments_for_evidence(evidence_id):
                if a.get("inode") is not None:
                    tagged_inodes_full.add(int(a.get("inode")))
        mw = self

        def worker():
            try:
                mw.full_report_progress.emit("Genel rapor: dizin ağacı yükleniyor...")
                from collections import deque
                nodes_list = []
                q = deque([None])
                while q:
                    parent = q.popleft()
                    children = mw.engine_session.snapshot.get_children(parent)
                    for node in children:
                        nodes_list.append(node)
                        if node.get("is_dir"):
                            q.append(node.get("inode"))
                file_nodes = [n for n in nodes_list if not n.get("is_dir")]
                if only_tagged_full_val and tagged_inodes_full:
                    file_nodes = [n for n in file_nodes if n.get("inode") is not None and int(n.get("inode")) in tagged_inodes_full]
                total_files = len(file_nodes)
                mw.full_report_progress.emit(f"Genel rapor: {total_files} dosya bulundu. Çıkarılıyor...")
                extracted_map = {}
                extracted = os.path.join(report_dir, "extracted")
                if do_extract:
                    os.makedirs(extracted, exist_ok=True)
                    last_pct_emitted = -1
                    for i, node in enumerate(file_nodes):
                        ino = node.get("inode")
                        path_str = mw._get_path_for_inode(ino) or ""
                        safe_rel = path_str.replace("\\", "/").strip("/").replace("../", "_/") or "dosya"
                        safe_rel = "".join(c if c.isalnum() or c in "/._-" else "_" for c in safe_rel)
                        target_path = os.path.join(extracted, safe_rel)
                        try:
                            data = mw.engine_session.read_file_content(ino, max_size=REPORT_EXTRACT_MAX_BYTES)
                            if data is not None:
                                os.makedirs(os.path.dirname(target_path) or ".", exist_ok=True)
                                with open(target_path, "wb") as f:
                                    f.write(data)
                                hashes = mw.engine_session.get_hashes(ino)
                                md5 = (hashes or {}).get("md5") or "—"
                                sha1 = (hashes or {}).get("sha1") or "—"
                                rel_link = "extracted/" + safe_rel.replace("\\", "/")
                                extracted_map[int(ino)] = {"rel_path": rel_link, "md5": md5, "sha1": sha1}
                        except Exception as e:
                            pass
                        pct = (i + 1) * 100 // total_files if total_files else 0
                        if pct >= last_pct_emitted + 2 or pct == 100 or i == 0:
                            last_pct_emitted = pct
                            mw.full_report_progress.emit(f"Genel rapor: %{pct} ({i+1}/{total_files})")
                mw.full_report_progress.emit("Genel rapor: HTML oluşturuluyor...")
                html_content = mw._build_full_report_html_from_data(
                    nodes_list, extracted_map,
                    only_tagged=only_tagged_full_val, tagged_inodes=tagged_inodes_full,
                )
                if want_html:
                    index_path = os.path.join(report_dir, "index.html")
                    with open(index_path, "w", encoding="utf-8") as f:
                        f.write(html_content)
                if want_pdf:
                    pdf_path = os.path.join(report_dir, "report.pdf")
                    doc = QTextDocument()
                    doc.setHtml(html_content)
                    printer = QPrinter()
                    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
                    printer.setOutputFileName(pdf_path)
                    doc.print(printer)
                mw.full_report_progress.emit(f"Genel rapor tamamlandı: {report_dir}")
            except Exception as e:
                mw.full_report_progress.emit(f"Genel rapor hatası: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def _create_report_folder(self) -> str | None:
        """Rapor klasörü oluştur."""
        reports_base = os.path.join(self.case_dir, "reports")
        try:
            os.makedirs(reports_base, exist_ok=True)
            stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            folder = os.path.join(reports_base, f"Rapor_{stamp}")
            os.makedirs(folder, exist_ok=True)
            return folder
        except Exception as e:
            self.log(f"Rapor klasörü oluşturulamadı: {e}")
            return None

    def _report_link_cell(self, name: str, rel_path: str, ex: dict) -> str:
        """Dosya linki (resim/video sekmede, diğerleri indir)."""
        IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif")
        VIDEO_EXTS = (".mp4", ".webm", ".avi", ".mov", ".mkv", ".wmv", ".flv", ".m4v")
        href = html.escape(rel_path.replace("\\", "/"))
        safe_name = html.escape((name or "dosya")[:80])
        if any(name.lower().endswith(e) for e in IMAGE_EXTS):
            return f'<td><a href="{href}" target="_blank" rel="noopener">Resmi aç</a></td>'
        if any(name.lower().endswith(e) for e in VIDEO_EXTS):
            return f'<td><a href="{href}" target="_blank" rel="noopener" download="{safe_name}">Videoyu indir</a></td>'
        return f'<td><a href="{href}" target="_blank" rel="noopener" download="{safe_name}">İndir</a></td>'

    def _group_nodes_by_folder(self, items: list[tuple]) -> list[tuple]:
        """Node listesini klasör yoluna göre grupla."""
        from collections import defaultdict
        by_dir = defaultdict(list)
        for node, path_str in items:
            dir_path = path_str.rsplit("/", 1)[0] if "/" in path_str else "/"
            if not dir_path:
                dir_path = "/"
            by_dir[dir_path].append((node, path_str))
        return sorted(by_dir.items(), key=lambda x: (x[0].lower(), x[0]))

    def _build_report_html(self, extracted_map: dict | None = None, only_tagged: bool = False, tagged_inodes: set | None = None) -> str:
        """Adli rapor HTML (klasörlere göre bulgular, hash)."""
        case_name = html.escape(os.path.basename(self.case_dir) or "Case")
        evidence_label = html.escape(self.evidence_combo.currentText() or "—")
        report_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        current_path = self._get_path_for_inode(self._current_inode) if self._current_inode else "/"
        current_path_esc = html.escape(current_path)
        evidence_id = getattr(self.engine_session, "evidence_id", None) or ""
        assignments = tag_manager.get_assignments_for_evidence(evidence_id)
        inode_to_tags: dict[int, list[str]] = {}
        for a in assignments:
            ino = a.get("inode")
            if ino is not None:
                inode_to_tags.setdefault(int(ino), []).append(a.get("tag_name", ""))
        tagged = tagged_inodes if tagged_inodes is not None else set()
        has_extras = bool(extracted_map)

        items = []
        for row in range(self.file_list_model.rowCount()):
            node = self.file_list_model.get_node_at(row)
            if not node:
                continue
            ino = node.get("inode")
            if only_tagged and (ino is None or int(ino) not in tagged):
                continue
            path_str = self._get_path_for_inode(ino) or ""
            items.append((node, path_str))
        folder_groups = self._group_nodes_by_folder(items)
        row_count = len(items)

        def row_cells(node, path_str, ino):
            name = node.get("name", "")
            size = node.get("size") or 0
            type_str = "Klasör" if node.get("is_dir") else _extension_from_name(name)
            mtime = node.get("mtime") or ""
            atime = node.get("atime") or ""
            ctime = node.get("crtime") or node.get("ctime") or ""
            if isinstance(mtime, (int, float)):
                try: mtime = datetime.utcfromtimestamp(int(mtime)).strftime("%Y-%m-%d %H:%M") if mtime else ""
                except Exception: mtime = str(mtime)
            if isinstance(atime, (int, float)):
                try: atime = datetime.utcfromtimestamp(int(atime)).strftime("%Y-%m-%d %H:%M") if atime else ""
                except Exception: atime = str(atime)
            if isinstance(ctime, (int, float)):
                try: ctime = datetime.utcfromtimestamp(int(ctime)).strftime("%Y-%m-%d %H:%M") if ctime else ""
                except Exception: ctime = str(ctime)
            deleted = "Evet" if node.get("deleted") else "Hayır"
            tags = ", ".join(inode_to_tags.get(int(ino), [])) if ino is not None else ""
            md5_cell = sha1_cell = link_cell = ""
            if has_extras and ino is not None and int(ino) in extracted_map:
                ex = extracted_map[int(ino)]
                md5_cell = f"<td>{html.escape(ex.get('md5', '—'))}</td>"
                sha1_cell = f"<td>{html.escape(ex.get('sha1', '—'))}</td>"
                link_cell = self._report_link_cell(name, ex.get("rel_path", ""), ex)
            elif has_extras:
                md5_cell = "<td>—</td>"
                sha1_cell = "<td>—</td>"
                link_cell = "<td>—</td>"
            base = (
                f"<tr><td>{html.escape(path_str)}</td><td>{html.escape(name)}</td><td>{ino}</td><td>{size}</td>"
                f"<td>{html.escape(type_str)}</td><td>{html.escape(str(mtime))}</td><td>{html.escape(str(atime))}</td>"
                f"<td>{html.escape(str(ctime))}</td><td>{deleted}</td><td>{html.escape(tags)}</td>"
            )
            if has_extras:
                base += md5_cell + sha1_cell + link_cell
            return base + "</tr>"

        extra_headers = "<th>MD5</th><th>SHA1</th><th>Dosya</th>" if has_extras else ""
        sections_html = []
        for folder_path, folder_items in folder_groups:
            folder_esc = html.escape(folder_path or "/")
            rows = "\n".join(row_cells(n, p, n.get("inode")) for n, p in folder_items)
            sections_html.append(f"""
<div class="section folder-section">
<h3 class="folder-title">Klasör: <code>{folder_esc}</code></h3>
<table>
<thead><tr>
<th>Yol</th><th>Ad</th><th>Inode</th><th>Boyut</th><th>Tür</th>
<th>Değiştirilme</th><th>Erişim</th><th>Oluşturulma</th><th>Silindi</th><th>Etiket</th>{extra_headers}
</tr></thead>
<tbody>
{rows}
</tbody>
</table>
</div>""")

        findings_body = "\n".join(sections_html)
        summary_esc = html.escape(f"Bu rapor, {evidence_label} kanıtı üzerinde {current_path} konumu incelenerek oluşturulmuştur. Toplam {row_count} öğe listelenmiştir.")
        scope_esc = html.escape(f"İncelenen kanıt: {evidence_label}. İncelenen konum: {current_path}. Rapor kapsamı: bu konumdaki dosya ve klasörler ile meta veri, zaman damgaları, isteğe bağlı hash (MD5/SHA1) ve etiket bilgileri.")
        method_esc = html.escape("Dijital kanıt yazılımı ile disk imajı açılmış; dosya sistemi okunmuş; dosyalar rapor klasörüne çıkarılmış ve hash değerleri hesaplanmıştır. Rapor, yazılım çıktısı olup bulguların doğrulanması için kullanılabilir.")

        html_doc = f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Dijital Adli Rapor — {case_name}</title>
<style>
:root {{ --bg: #f1f5f9; --panel: #fff; --border: #cbd5e1; --text: #0f172a; --muted: #475569; --accent: #1d4ed8; }}
* {{ box-sizing: border-box; }}
body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 24px; line-height: 1.6; }}
.report-header {{ background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 24px; margin-bottom: 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }}
.report-header h1 {{ margin: 0 0 8px 0; font-size: 1.5rem; color: var(--text); }}
.report-header .meta {{ color: var(--muted); font-size: 0.9rem; }}
.section {{ background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 20px; margin-bottom: 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }}
.section h2 {{ margin: 0 0 12px 0; font-size: 1.2rem; color: var(--text); border-bottom: 2px solid var(--border); padding-bottom: 8px; }}
.folder-section {{ margin-top: 20px; }}
.folder-title {{ font-size: 1rem; margin: 0 0 12px 0; color: var(--muted); font-weight: 600; }}
.folder-title code {{ background: #f1f5f9; padding: 2px 8px; border-radius: 4px; font-size: 0.9rem; }}
table {{ width: 100%; border-collapse: collapse; font-size: 0.8rem; }}
th {{ text-align: left; padding: 8px 10px; background: #f1f5f9; border: 1px solid var(--border); font-weight: 600; }}
td {{ padding: 6px 10px; border: 1px solid var(--border); }}
tr:nth-child(even) {{ background: #fafafa; }}
tr:hover {{ background: #f1f5f9; }}
a {{ color: var(--accent); text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
.deleted {{ color: #b91c1c; }}
.limitation {{ color: var(--muted); font-size: 0.9rem; margin-top: 8px; }}
@media print {{ body {{ background: #fff; }} .report-header, .section {{ border: 1px solid #999; box-shadow: none; }} }}
</style>
</head>
<body>
<div class="report-header">
<h1>Dijital Adli Rapor</h1>
<div class="meta">Case: {case_name} &nbsp;|&nbsp; Kanıt: {evidence_label} &nbsp;|&nbsp; Rapor tarihi: {report_date}</div>
</div>
<div class="section">
<h2>1. Özet</h2>
<p>{summary_esc}</p>
</div>
<div class="section">
<h2>2. Kapsam</h2>
<p>{scope_esc}</p>
<div class="path-breadcrumb" style="font-family: monospace; background: #f1f5f9; padding: 10px; border-radius: 4px; margin-top: 8px;">{current_path_esc}</div>
</div>
<div class="section">
<h2>3. Yöntem</h2>
<p>{method_esc}</p>
</div>
<div class="section">
<h2>4. Bulgular (Klasörlere göre)</h2>
<p>Dosya ve klasörler incelenen konumdaki klasör yapısına göre aşağıda listelenmektedir. Çıkarılan dosyalar <strong>extracted/</strong> altındadır. Resimler için &quot;Resmi aç&quot;, videolar için &quot;Videoyu indir&quot;, diğer dosyalar için &quot;İndir&quot; kullanın.</p>
{findings_body}
</div>
<div class="section">
<h2>5. Hash doğrulama</h2>
<p>Tablo içinde belirtilen MD5/SHA1 değerleri, çıkarılan dosya içerikleri üzerinden hesaplanmıştır. Bağımsız doğrulama için aynı dosyayı aynı algoritma ile hashleyebilirsiniz.</p>
</div>
<div class="section">
<h2>6. Sınırlamalar</h2>
<p class="limitation">Bu rapor, inceleme anındaki yazılım çıktısını yansıtır. Şifreli veya erişilemeyen içerikler listelenmemiş olabilir. Bulgular, kullanılan araç ve yöntemin sınırları dahilindedir.</p>
</div>
</body>
</html>"""
        return html_doc

    def _build_full_report_html_from_data(self, nodes_list: list, extracted_map: dict, only_tagged: bool = False, tagged_inodes: set | None = None) -> str:
        """Genel rapor HTML."""
        case_name = html.escape(os.path.basename(self.case_dir) or "Case")
        evidence_label = html.escape(self.evidence_combo.currentText() or "—")
        report_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        evidence_id = getattr(self.engine_session, "evidence_id", None) or ""
        assignments = tag_manager.get_assignments_for_evidence(evidence_id)
        inode_to_tags: dict[int, list[str]] = {}
        for a in assignments:
            ino = a.get("inode")
            if ino is not None:
                inode_to_tags.setdefault(int(ino), []).append(a.get("tag_name", ""))
        tagged = tagged_inodes if tagged_inodes is not None else set()

        items = []
        for node in nodes_list:
            ino = node.get("inode")
            if only_tagged and tagged and (ino is None or int(ino) not in tagged):
                continue
            path_str = self._get_path_for_inode(ino) or ""
            items.append((node, path_str))
        folder_groups = self._group_nodes_by_folder(items)
        total_count = len(items)
        has_extras = bool(extracted_map)

        def full_row_cells(node, path_str, ino):
            name = node.get("name", "")
            size = node.get("size") or 0
            type_str = "Klasör" if node.get("is_dir") else _extension_from_name(name)
            mtime = node.get("mtime") or ""
            atime = node.get("atime") or ""
            ctime = node.get("crtime") or node.get("ctime") or ""
            if isinstance(mtime, (int, float)):
                try: mtime = datetime.utcfromtimestamp(int(mtime)).strftime("%Y-%m-%d %H:%M") if mtime else ""
                except Exception: mtime = str(mtime)
            if isinstance(atime, (int, float)):
                try: atime = datetime.utcfromtimestamp(int(atime)).strftime("%Y-%m-%d %H:%M") if atime else ""
                except Exception: atime = str(atime)
            if isinstance(ctime, (int, float)):
                try: ctime = datetime.utcfromtimestamp(int(ctime)).strftime("%Y-%m-%d %H:%M") if ctime else ""
                except Exception: ctime = str(ctime)
            deleted = "Evet" if node.get("deleted") else "Hayır"
            tags = ", ".join(inode_to_tags.get(int(ino), [])) if ino is not None else ""
            md5_cell = sha1_cell = link_cell = ""
            if has_extras and ino is not None and int(ino) in extracted_map:
                ex = extracted_map[int(ino)]
                md5_cell = f"<td>{html.escape(ex.get('md5', '—'))}</td>"
                sha1_cell = f"<td>{html.escape(ex.get('sha1', '—'))}</td>"
                link_cell = self._report_link_cell(name, ex.get("rel_path", ""), ex)
            elif has_extras:
                md5_cell = "<td>—</td>"
                sha1_cell = "<td>—</td>"
                link_cell = "<td>—</td>"
            base = (
                f"<tr><td>{html.escape(path_str)}</td><td>{html.escape(name)}</td><td>{ino}</td><td>{size}</td>"
                f"<td>{html.escape(type_str)}</td><td>{html.escape(str(mtime))}</td><td>{html.escape(str(atime))}</td>"
                f"<td>{html.escape(str(ctime))}</td><td>{deleted}</td><td>{html.escape(tags)}</td>"
            )
            if has_extras:
                base += md5_cell + sha1_cell + link_cell
            return base + "</tr>"

        extra_headers = "<th>MD5</th><th>SHA1</th><th>Dosya</th>" if has_extras else ""
        sections_html = []
        for folder_path, folder_items in folder_groups:
            folder_esc = html.escape(folder_path or "/")
            rows = "\n".join(full_row_cells(n, p, n.get("inode")) for n, p in folder_items)
            sections_html.append(f"""
<div class="section folder-section">
<h3 class="folder-title">Klasör: <code>{folder_esc}</code></h3>
<table>
<thead><tr>
<th>Yol</th><th>Ad</th><th>Inode</th><th>Boyut</th><th>Tür</th>
<th>Değiştirilme</th><th>Erişim</th><th>Oluşturulma</th><th>Silindi</th><th>Etiket</th>{extra_headers}
</tr></thead>
<tbody>
{rows}
</tbody>
</table>
</div>""")
        findings_body = "\n".join(sections_html)
        summary_esc = html.escape(f"Bu rapor, {evidence_label} kanıtı üzerinde imajın tüm dizin ağacı incelenerek oluşturulmuştur. Toplam {total_count} öğe listelenmiştir.")
        scope_esc = html.escape(f"İncelenen kanıt: {evidence_label}. Kapsam: tüm dosya sistemi (isteğe bağlı filtre: sadece etiketliler). Rapor, klasörlere göre gruplanmış dosya/klasör listesi, meta veri, hash ve etiket bilgilerini içerir.")
        method_esc = html.escape("Dijital kanıt yazılımı ile disk imajı açılmış; tüm dizin ağacı taranmış; dosyalar rapor klasörüne çıkarılmış ve hash değerleri hesaplanmıştır. Rapor, bulguların doğrulanması için kullanılabilir.")

        html_doc = f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Genel Dijital Adli Rapor — {case_name}</title>
<style>
:root {{ --bg: #f1f5f9; --panel: #fff; --border: #cbd5e1; --text: #0f172a; --muted: #475569; --accent: #1d4ed8; }}
* {{ box-sizing: border-box; }}
body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 24px; line-height: 1.6; }}
.report-header {{ background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 24px; margin-bottom: 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }}
.report-header h1 {{ margin: 0 0 8px 0; font-size: 1.5rem; }}
.report-header .meta {{ color: var(--muted); font-size: 0.9rem; }}
.section {{ background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 20px; margin-bottom: 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }}
.section h2 {{ margin: 0 0 12px 0; font-size: 1.2rem; border-bottom: 2px solid var(--border); padding-bottom: 8px; }}
.folder-section {{ margin-top: 20px; }}
.folder-title {{ font-size: 1rem; margin: 0 0 12px 0; color: var(--muted); font-weight: 600; }}
.folder-title code {{ background: #f1f5f9; padding: 2px 8px; border-radius: 4px; font-size: 0.9rem; }}
table {{ width: 100%; border-collapse: collapse; font-size: 0.8rem; }}
th {{ text-align: left; padding: 8px 10px; background: #f1f5f9; border: 1px solid var(--border); font-weight: 600; }}
td {{ padding: 6px 10px; border: 1px solid var(--border); }}
tr:nth-child(even) {{ background: #fafafa; }}
tr:hover {{ background: #f1f5f9; }}
a {{ color: var(--accent); text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
.deleted {{ color: #b91c1c; }}
.limitation {{ color: var(--muted); font-size: 0.9rem; margin-top: 8px; }}
@media print {{ body {{ background: #fff; }} .report-header, .section {{ border: 1px solid #999; box-shadow: none; }} }}
</style>
</head>
<body>
<div class="report-header">
<h1>Genel Dijital Adli Rapor</h1>
<div class="meta">Case: {case_name} &nbsp;|&nbsp; Kanıt: {evidence_label} &nbsp;|&nbsp; Rapor tarihi: {report_date}</div>
<p>Toplam {total_count} öğe. Bulgular klasörlere göre aşağıda listelenmektedir.</p>
</div>
<div class="section">
<h2>1. Özet</h2>
<p>{summary_esc}</p>
</div>
<div class="section">
<h2>2. Kapsam</h2>
<p>{scope_esc}</p>
</div>
<div class="section">
<h2>3. Yöntem</h2>
<p>{method_esc}</p>
</div>
<div class="section">
<h2>4. Bulgular (Klasörlere göre)</h2>
<p>Dosyalar <strong>extracted/</strong> altındadır. Resimler için &quot;Resmi aç&quot;, videolar için &quot;Videoyu indir&quot;, diğerleri için &quot;İndir&quot; kullanın.</p>
{findings_body}
</div>
<div class="section">
<h2>5. Hash doğrulama</h2>
<p>MD5/SHA1 değerleri çıkarılan dosya içerikleri üzerinden hesaplanmıştır. Bağımsız doğrulama için aynı dosyayı aynı algoritma ile hashleyebilirsiniz.</p>
</div>
<div class="section">
<h2>6. Sınırlamalar</h2>
<p class="limitation">Bu rapor, inceleme anındaki yazılım çıktısını yansıtır. Şifreli veya erişilemeyen içerikler listelenmemiş olabilir.</p>
</div>
</body>
</html>"""
        return html_doc

    def _html_to_pdf(self, html_content: str, pdf_path: str):
        """HTML'i PDF'e çevir."""
        doc = QTextDocument()
        doc.setHtml(html_content)
        printer = QPrinter()
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(pdf_path)
        doc.print(printer)

    def _on_export_file_clicked(self):
        """Seçili dosyaları diske kaydet."""
        nodes = self._get_checked_file_nodes()
        if not nodes or not self.engine_session:
            self.log("Dosyayı aktarma: önce listeden dosya(ları) seçin (Seç kutusunu işaretleyin).")
            return
        target_dir = QFileDialog.getExistingDirectory(self, "Dosyaları kaydedecek klasörü seçin")
        if not target_dir:
            return
        session = self.engine_session
        total = len(nodes)

        def worker():
            for i, (inode, name) in enumerate(nodes):
                try:
                    pct = (i + 1) * 100 // total if total else 0
                    self.export_progress.emit(f"Dosyayı aktarma: %{pct} ({i+1}/{total}) — {name[:40]}")
                    data = session.read_file_content(inode)
                    if data is None:
                        continue
                    safe = "".join(c if c.isalnum() or c in "._- " else "_" for c in (name or f"inode_{inode}"))
                    out_path = os.path.join(target_dir, safe)
                    if os.path.exists(out_path):
                        base, ext = os.path.splitext(safe)
                        out_path = os.path.join(target_dir, f"{base}_{inode}{ext}")
                    with open(out_path, "wb") as f:
                        f.write(data)
                except Exception as e:
                    self.export_progress.emit(f"Hata ({name}): {e}")
            self.export_progress.emit(f"Dosyayı aktarma tamamlandı: {target_dir}")

        threading.Thread(target=worker, daemon=True).start()

    def _on_tag_item_clicked(self):
        """Etiket ve not ekle."""
        if not self.engine_session or self._selected_inode is None:
            self.log("Etiketle: önce bir öğe seçin.")
            return
        defs = tag_manager.load_definitions()
        if not defs:
            self.log("Etiketle: önce Etiket ayarlarından en az bir etiket tanımlayın.")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Etiket ve not ekle")
        ly = QVBoxLayout(dlg)
        ly.addWidget(QLabel("Etiket:"))
        tag_combo = QComboBox()
        for d in defs:
            tag_combo.addItem(d.get("name", "?"), d.get("name"))
        ly.addWidget(tag_combo)
        ly.addWidget(QLabel("Not (isteğe bağlı):"))
        note_edit = QLineEdit()
        note_edit.setPlaceholderText("Not yazın...")
        ly.addWidget(note_edit)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        ly.addWidget(bb)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        tag_name = tag_combo.currentData() or tag_combo.currentText()
        note = (note_edit.text() or "").strip()
        evidence_id = getattr(self.engine_session, "evidence_id", None) or ""
        tag_manager.add_assignment(evidence_id, int(self._selected_inode), tag_name, note)
        path_str = self._get_path_for_inode(self._selected_inode) or ""
        detail = f"etiket=\"{tag_name}\", inode={self._selected_inode}, yol={path_str}"
        if note:
            detail += f", not=\"{note[:80]}\"" if len(note) > 80 else f", not=\"{note}\""
        self.log(f"Etiket eklendi: {detail}")
        if self._main_tabs.currentIndex() == 1:
            self._refresh_tags_tab()

    def _on_tag_settings_clicked(self):
        """Etiket ayarları."""
        t = DESIGN_TOKENS
        dlg = QDialog(self)
        dlg.setWindowTitle("Etiket ayarları")
        dlg.setMinimumWidth(420)
        ly = QVBoxLayout(dlg)
        ly.addWidget(QLabel("Etiketler (isim, tuş, renk):"))
        tag_list = QListWidget()
        tag_list.setObjectName("tagDefList")
        tag_list.setStyleSheet(f"QListWidget#tagDefList {{ background: {t['bg_panel']}; border: 1px solid {t['border_subtle']}; }}")
        defs = tag_manager.load_definitions()
        for d in defs:
            name = d.get("name", "?")
            shortcut = d.get("shortcut", "")
            color = d.get("color", "#6b7280")
            it = QListWidgetItem(f"  {name}  |  Tuş: {shortcut or '—'}  |  ■")
            it.setBackground(QColor(color))
            it.setForeground(QColor("#fff" if QColor(color).lightness() < 128 else "#111"))
            it.setData(Qt.ItemDataRole.UserRole, d)
            tag_list.addItem(it)
        ly.addWidget(tag_list, 1)
        btn_ly = QHBoxLayout()
        add_btn = QPushButton("Ekle")
        add_btn.clicked.connect(lambda: _add_tag(defs, tag_list))
        edit_btn = QPushButton("Düzenle")
        edit_btn.clicked.connect(lambda: _edit_tag(defs, tag_list))
        remove_btn = QPushButton("Sil")
        remove_btn.clicked.connect(lambda: _remove_tag(defs, tag_list))
        btn_ly.addWidget(add_btn)
        btn_ly.addWidget(edit_btn)
        btn_ly.addWidget(remove_btn)
        btn_ly.addStretch()
        ly.addLayout(btn_ly)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        def save_and_close():
            tag_manager.save_definitions(defs)
            self._register_tag_shortcuts()
            dlg.accept()
        bb.button(QDialogButtonBox.StandardButton.Save).clicked.connect(save_and_close)
        bb.rejected.connect(dlg.reject)
        ly.addWidget(bb)

        def _add_tag(defs_ref, list_widget):
            name, ok = QInputDialog.getText(dlg, "Yeni etiket", "Etiket adı:")
            if not ok or not (name := (name or "").strip()):
                return
            color_hex = "#3b82f6"
            cd = QColorDialog(self)
            cd.setCurrentColor(QColor(color_hex))
            if cd.exec() == QColorDialog.DialogCode.Accepted:
                color_hex = cd.currentColor().name()
            key_dlg = KeyCaptureDialog(self, "")
            key_dlg.exec()
            shortcut = key_dlg.get_key_sequence()
            defs_ref.append({"name": name, "shortcut": shortcut, "color": color_hex})
            it = QListWidgetItem(f"  {name}  |  Tuş: {shortcut or '—'}  |  ■")
            it.setBackground(QColor(color_hex))
            it.setForeground(QColor("#fff" if QColor(color_hex).lightness() < 128 else "#111"))
            it.setData(Qt.ItemDataRole.UserRole, defs_ref[-1])
            list_widget.addItem(it)

        def _edit_tag(defs_ref, list_widget):
            idx = list_widget.currentRow()
            if idx < 0:
                return
            item = list_widget.item(idx)
            d = item.data(Qt.ItemDataRole.UserRole)
            if not d or d not in defs_ref:
                return
            name, ok = QInputDialog.getText(dlg, "Etiket adı", "Etiket adı:", text=d.get("name", ""))
            if not ok:
                return
            name = (name or "").strip() or d.get("name", "")
            color_hex = d.get("color", "#6b7280")
            cd = QColorDialog(self)
            cd.setCurrentColor(QColor(color_hex))
            if cd.exec() == QColorDialog.DialogCode.Accepted:
                color_hex = cd.currentColor().name()
            key_dlg = KeyCaptureDialog(self, d.get("shortcut", ""))
            key_dlg.exec()
            shortcut = key_dlg.get_key_sequence()
            d["name"] = name
            d["color"] = color_hex
            d["shortcut"] = shortcut
            item.setText(f"  {name}  |  Tuş: {shortcut or '—'}  |  ■")
            item.setBackground(QColor(color_hex))
            item.setForeground(QColor("#fff" if QColor(color_hex).lightness() < 128 else "#111"))

        def _remove_tag(defs_ref, list_widget):
            idx = list_widget.currentRow()
            if idx < 0:
                return
            item = list_widget.item(idx)
            d = item.data(Qt.ItemDataRole.UserRole)
            if d and d in defs_ref:
                defs_ref.remove(d)
            list_widget.takeItem(idx)

        dlg.exec()

    def _apply_metadata_to_panel(self, meta: dict, inode: int):
        """Meta paneli doldur."""
        def _v(k: str, d: str = "N/A") -> str:
            v = meta.get(k)
            return str(v) if v not in (None, "") else d
        self.meta_name.setText(_v("name"))
        self.meta_inode.setText(_v("inode"))
        self.meta_type.setText(_v("type"))
        self.meta_size.setText(_v("size"))
        self.meta_mtime.setText(_v("mtime"))
        self.meta_atime.setText(_v("atime"))
        self.meta_ctime.setText(_v("ctime"))
        self.meta_crtime.setText(_v("crtime"))
        try:
            if self.engine_session:
                deleted = self.engine_session.is_deleted(inode)
                self.meta_deleted.setText("Evet" if deleted else "Hayır")
            else:
                self.meta_deleted.setText("N/A")
        except Exception:
            self.meta_deleted.setText("N/A")
        forensic = meta.get("forensic") or {}
        def _f(k): v = forensic.get(k); return str(v).strip() if v else "N/A"
        gps_coords = _f("gps")
        gps_region = _f("gps_region")
        self.meta_gps.setText(f"{gps_coords} — {gps_region}" if gps_region != "N/A" and gps_coords != "N/A" else (gps_coords if gps_coords != "N/A" else gps_region))
        self.meta_make.setText(_f("make"))
        self.meta_model.setText(_f("model"))
        self.meta_datetime_original.setText(_f("datetime_original"))
        self.meta_software.setText(_f("software"))
        w, h = forensic.get("image_width"), forensic.get("image_height")
        self.meta_image_size.setText(f"{w}×{h}" if (w and h) else "N/A")

    def _update_metadata_from_inode_name(self, inode: int | None, name: str | None):
        """Meta veri getir, paneli güncelle."""
        if inode is None or not self.engine_session:
            self._clear_meta_panel("Bir dosya veya klasör seçin." if not self.engine_session else "Seçim yok.")
            return
        self._selected_inode = inode
        self._selected_name = name or ""
        meta = self.engine_session.get_metadata(inode, name=name)
        if not meta:
            self._clear_meta_panel("Meta veri yok.")
            self._selected_is_dir = True
            self._update_export_file_button_state()
            return
        self._selected_is_dir = (meta.get("type") == "Directory")
        self._apply_metadata_to_panel(meta, inode)
        self.meta_md5.setText("N/A")
        self.meta_sha1.setText("N/A")
        self._update_export_file_button_state()

    def _on_selection_changed(self):
        """Ağaç seçimi değişti."""
        if not self.model or not self.engine_session:
            self._clear_meta_panel("E01 seçin ve ağacı yükleyin.")
            return
        idx = self.tree.currentIndex()
        if not idx.isValid():
            self._clear_meta_panel("Bir dosya veya klasör seçin.")
            return
        item = self.model.itemFromIndex(idx)
        if not item:
            self._clear_meta_panel("Bir dosya veya klasör seçin.")
            return
        name = item.text() or ""
        inode = item.data(INODE_ROLE)
        if inode is None or inode == -1 or (isinstance(inode, int) and inode < 0):
            self._clear_meta_panel("Bir dosya veya klasör seçin (yer tutucu değil).")
            return
        self._update_metadata_from_inode_name(inode, name)

    def _on_table_selection_changed(self):
        """Tablo seçimi değişti."""
        if not self.engine_session or self._main_tabs.currentIndex() != 0:
            return
        idx = self.file_table.currentIndex()
        if not idx.isValid():
            return
        node = self.file_list_model.get_node_at(idx.row())
        if not node:
            return
        self._update_metadata_from_inode_name(node.get("inode"), node.get("name"))

    def _on_list_selection_changed(self):
        """Liste seçimi değişti."""
        if not self.engine_session or self._main_tabs.currentIndex() != 0:
            return
        idx = self.file_list_view.currentIndex()
        if not idx.isValid():
            return
        row = idx.row()
        item = self.file_list_list_model.item(row)
        if not item:
            return
        inode = item.data(INODE_ROLE)
        if inode is None:
            return
        node = self.file_list_model.get_node_at(row)
        name = node.get("name", "") if node else item.text() or ""
        self._update_metadata_from_inode_name(inode, name)

    def _on_compute_hashes(self):
        """Hash hesapla (arka planda)."""
        if not self.engine_session or self._selected_inode is None:
            self.log("[GUI] Önce bir dosya seçin.")
            return
        if getattr(self, "_hash_computing", False):
            return
        self._hash_computing = True
        self.btn_hashes.setEnabled(False)
        self.btn_hashes.setText("Hesaplanıyor…")
        QApplication.processEvents()
        inode = self._selected_inode
        session = self.engine_session

        def worker():
            try:
                result = session.get_hashes(inode)
                self.hashes_ready.emit(result)
            except Exception as e:
                self.log(f"[HATA] Hash: {e}")
                self.hashes_ready.emit(None)

        threading.Thread(target=worker, daemon=True).start()

    def _on_hashes_ready(self, result: dict | None):
        self._hash_computing = False
        self.btn_hashes.setEnabled(True)
        self.btn_hashes.setText("Hash hesapla")
        if result:
            self.meta_md5.setText(result.get("md5") or "N/A")
            self.meta_sha1.setText(result.get("sha1") or "N/A")
        else:
            self.meta_md5.setText("N/A")
            self.meta_sha1.setText("N/A")

    def _on_select_e01(self):
        """E01 seç, case'e ekle, ağacı aç."""
        file, _ = QFileDialog.getOpenFileName(self, "E01 Seç", "", "E01 Files (*.E01)")
        if not file:
            return
        file = os.path.normpath(os.path.abspath(file))
        self.log(f"[GUI] E01 seçildi: {file}")
        case_dir = self.case_dir
        try:
            from backend.engine.evidence.evidence_manager import EvidenceManager
            em = EvidenceManager()
            evidence_id = em.add_evidence(case_dir, file)
            self.log(f"[GUI] Case'e eklendi: {os.path.join(case_dir, 'evidence', evidence_id)}")
        except Exception as e:
            self.log(f"[HATA] Case'e eklenemedi: {e}")
            return
        self._refresh_evidence_list()
        for i in range(1, self.evidence_combo.count()):
            if self.evidence_combo.itemData(i) == evidence_id:
                self.evidence_combo.blockSignals(True)
                self.evidence_combo.setCurrentIndex(i)
                self.evidence_combo.blockSignals(False)
                break
        self._start_tree_cached(evidence_id)

    def _on_build_snapshot(self):
        if not self.engine_session:
            self.log("[GUI] Load evidence first.")
            return
        self._snapshot_stop = False
        self.act_build_snapshot.setEnabled(False)
        self.act_cancel_build.setEnabled(True)

        def worker():
            try:
                self.engine_session.build_full_snapshot(
                    stop_flag=lambda: self._snapshot_stop,
                    progress_callback=lambda msg: self.logger.log_signal.emit(msg),
                )
                if not getattr(self, "_snapshot_stop", True):
                    self.engine_session.manifest["full_snapshot_done"] = True
                    self.engine_session.save_manifest()
            finally:
                self.act_build_snapshot.setEnabled(True)
                self.act_cancel_build.setEnabled(False)

        threading.Thread(target=worker, daemon=True).start()

    def _on_cancel_snapshot(self):
        self._snapshot_stop = True
        self.log("[SNAPSHOT] Cancel requested.")

    def _on_folder_expanded(self, index: QModelIndex):
        """Klasör genişletilince çocukları yükle."""
        if not self.model or not self.engine_session:
            return
        item = self.model.itemFromIndex(index)
        if not item:
            return
        self.log(f"Klasör genişletildi: {item.text()}")
        is_dir = bool(item.data(IS_DIR_ROLE))
        if not is_dir:
            return
        # Zaten yüklü mü? (tek çocuk "..." değilse yüklü)
        if item.rowCount() != 1:
            return
        first = item.child(0, 0)
        if not first or first.text() != PLACEHOLDER_TEXT:
            return
        inode = item.data(INODE_ROLE)
        # E01 / Partition genişletilmez
        if inode in (TREE_INODE_E01, TREE_INODE_PARTITION):
            return

        try:
            if inode is None or inode == TREE_INODE_VOLUME:
                # Volume genişletilince kök klasörler yüklenir (eskiden [root] vardı)
                nodes = self.engine_session.list_root_cached(log_callback=self.log)
            elif hasattr(self.engine_session, "list_children_cached"):
                nodes = self.engine_session.list_children_cached(inode, log_callback=self.log)
            else:
                nodes = self.engine_session.list_children(inode)
        except Exception as e:
            self.log(f"Hata: Klasör açılamadı — {e}")
            return

        # Alfabetik sıra
        nodes.sort(key=lambda n: (n.name or "").lower())

        icon_dir = self._tree_folder_icon()
        item.removeRow(0)
        for n in nodes:
            if not n.is_dir:
                continue
            name = str(n.name) if n.name else ""
            child = QStandardItem(icon_dir, name)
            child.setData(n.inode, INODE_ROLE)
            child.setData(True, IS_DIR_ROLE)
            child.setFlags(child.flags() & ~Qt.ItemFlag.ItemIsEditable)
            ph = QStandardItem(PLACEHOLDER_TEXT)
            ph.setData(-1, INODE_ROLE)
            ph.setData(False, IS_DIR_ROLE)
            ph.setFlags(ph.flags() & ~Qt.ItemFlag.ItemIsEditable)
            child.appendRow(ph)
            item.appendRow(child)

        fresh_index = self.model.indexFromItem(item)
        if fresh_index.isValid():
            self.tree.expand(fresh_index)
        self.tree.viewport().update()

    def _tree_folder_icon(self):
        if self._tree_icon_dir is None:
            self._tree_icon_dir = QApplication.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        return self._tree_icon_dir

    def _apply_tree_model(self, session, root_nodes):
        """Ağaç modeli: E01 → Partition → Volume → klasörler."""
        try:
            if self._thumb_manager:
                self._thumb_manager.shutdown()
            self._thumb_manager = None
            self.engine_session = session
            icon_dir = self._tree_folder_icon()
            icon_drive = QApplication.style().standardIcon(QStyle.StandardPixmap.SP_DriveHDIcon)
            icon_part = QApplication.style().standardIcon(QStyle.StandardPixmap.SP_DriveFDIcon)
            model = QStandardItemModel(self)
            model.setHorizontalHeaderLabels(["Folders"])
            root = model.invisibleRootItem()

            # Üst seviye: E01 dosya adı
            e01_name = os.path.basename(session.e01_path)
            e01_item = QStandardItem(icon_drive, e01_name)
            e01_item.setData(TREE_INODE_E01, INODE_ROLE)
            e01_item.setData(True, IS_DIR_ROLE)
            e01_item.setFlags(e01_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            partitions = getattr(session, "partitions", None) or []
            data_part = getattr(session, "data_partition", None)
            volume_label = getattr(session, "volume_label", None) or ""

            def _size_mb(p):
                length = getattr(p, "length", None)
                if length is not None:
                    return (length * 512) / (1024 * 1024)
                return None

            def _short_fs_type(desc):
                if not desc:
                    return "Volume"
                d = (desc or "").upper()
                for fs in ("FAT32", "NTFS", "EXFAT", "FAT12", "FAT16", "EXT2", "EXT3", "EXT4", "HFS", "APFS"):
                    if fs in d:
                        return fs
                return "Volume"

            # FTK style: sadece mount ettiğimiz partisyonu göster (Partition 1). Boş partisyonlar listelenmez.
            has_unpartitioned = any(not _size_mb(p) or _size_mb(p) == 0 for p in partitions)

            if data_part and _size_mb(data_part) and _size_mb(data_part) > 0:
                p = data_part
                size_mb = _size_mb(p)
                label = f"Partition 1 [{size_mb:.0f}MB]"
                part_item = QStandardItem(icon_part, label)
                part_item.setData(TREE_INODE_PARTITION, INODE_ROLE)
                part_item.setData(True, IS_DIR_ROLE)
                part_item.setFlags(part_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

                # FTK: "Ttec [FAT32]" — volume label + short fs type; genişletilince kök klasörler list_root_cached ile doldurulacak
                short_fs = _short_fs_type(getattr(p, "desc", ""))
                vol_label = f"{volume_label} [{short_fs}]".strip() if volume_label else f"[{short_fs}]"
                vol_item = QStandardItem(icon_dir, vol_label)
                vol_item.setData(TREE_INODE_VOLUME, INODE_ROLE)
                vol_item.setData(True, IS_DIR_ROLE)
                vol_item.setFlags(vol_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                ph = QStandardItem(PLACEHOLDER_TEXT)
                ph.setData(-1, INODE_ROLE)
                ph.setData(False, IS_DIR_ROLE)
                ph.setFlags(ph.flags() & ~Qt.ItemFlag.ItemIsEditable)
                vol_item.appendRow(ph)
                part_item.appendRow(vol_item)
                # FTK: partition içinde [unallocated space] de göster
                unalloc_in_part = QStandardItem(icon_dir, "[unallocated space]")
                unalloc_in_part.setData(TREE_INODE_PARTITION, INODE_ROLE)
                unalloc_in_part.setData(False, IS_DIR_ROLE)
                unalloc_in_part.setFlags(unalloc_in_part.flags() & ~Qt.ItemFlag.ItemIsEditable)
                part_item.appendRow(unalloc_in_part)
                e01_item.appendRow(part_item)

            # FTK: "Unpartitioned Space [basic disk]" → [unallocated space]
            if has_unpartitioned:
                unpart_item = QStandardItem(icon_part, "Unpartitioned Space [basic disk]")
                unpart_item.setData(TREE_INODE_PARTITION, INODE_ROLE)
                unpart_item.setData(True, IS_DIR_ROLE)
                unpart_item.setFlags(unpart_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                unalloc = QStandardItem(icon_dir, "[unallocated space]")
                unalloc.setData(TREE_INODE_PARTITION, INODE_ROLE)
                unalloc.setData(False, IS_DIR_ROLE)
                unalloc.setFlags(unalloc.flags() & ~Qt.ItemFlag.ItemIsEditable)
                unpart_item.appendRow(unalloc)
                e01_item.appendRow(unpart_item)

            # Raw / tek partisyon yoksa tek zincir: E01 → Volume (genişletilince kök klasörler)
            if not partitions and data_part:
                short_fs = _short_fs_type(getattr(data_part, "desc", ""))
                vol_label = f"{volume_label} [{short_fs}]".strip() if volume_label else f"[{short_fs}]"
                vol_item = QStandardItem(icon_dir, vol_label)
                vol_item.setData(TREE_INODE_VOLUME, INODE_ROLE)
                vol_item.setData(True, IS_DIR_ROLE)
                vol_item.setFlags(vol_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                ph = QStandardItem(PLACEHOLDER_TEXT)
                ph.setData(-1, INODE_ROLE)
                ph.setData(False, IS_DIR_ROLE)
                ph.setFlags(ph.flags() & ~Qt.ItemFlag.ItemIsEditable)
                vol_item.appendRow(ph)
                e01_item.appendRow(vol_item)

            root.appendRow(e01_item)
            self.model = model
            self.tree.setModel(self.model)
            self.tree.selectionModel().selectionChanged.connect(self._on_selection_changed)
            self.tree.expandToDepth(2)
            QApplication.processEvents()
            self.tree.viewport().update()
            self._back_stack.clear()
            self._forward_stack.clear()
            self._navigate_to(None)
            self._update_nav_buttons()
            self._update_tree_evidence_label()
            self.log("Ağaç yüklendi (Explorer).")
            # Arama tüm volume'da çalışsın diye önbelleği doldur: tam indeks yoksa arka planda başlat
            QTimer.singleShot(500, self._maybe_start_background_indexing)
        except Exception as e:
            self.log(f"Hata: Ağaç oluşturulamadı — {e}")
            self.log(traceback.format_exc())

    def _update_tree_evidence_label(self):
        """Kanıt sayısını göster."""
        if not getattr(self, "_tree_evidence_label", None):
            return
        if not self.engine_session:
            self._tree_evidence_label.setText("")
            return
        try:
            n = self.engine_session.snapshot.count_nodes()
        except Exception:
            n = 0
        num_str = f"{n:,}".replace(",", ".")
        self._tree_evidence_label.setText(f"Toplam kanıt: {num_str}")

    def _maybe_start_background_indexing(self):
        """Volume indeksi yoksa arka planda başlat."""
        if not self.engine_session:
            return
        if self.engine_session.manifest.get("full_snapshot_done"):
            self.log("Önbellek tam (tam indeks mevcut). Arama tüm volume'da çalışır.")
            return
        if getattr(self, "_indexing_running", False):
            return
        self._indexing_running = True
        self.log("Volume indeksleniyor… Arama birkaç dakika içinde tüm dosya/klasörlerde çalışacak (E01'e tekrar dokunulmayacak).")

        def worker():
            try:
                self.engine_session.build_full_snapshot(
                    stop_flag=lambda: getattr(self, "_snapshot_stop", False),
                    progress_callback=lambda msg: self.logger.log_signal.emit(msg),
                )
                self.engine_session.manifest["full_snapshot_done"] = True
                self.engine_session.save_manifest()
            except Exception as e:
                self.logger.log_signal.emit(f"İndeksleme hatası: {e}")
            finally:
                QTimer.singleShot(0, self._on_background_indexing_done)

        threading.Thread(target=worker, daemon=True).start()

    def _on_background_indexing_done(self):
        self._indexing_running = False
        if self.engine_session and self.engine_session.manifest.get("full_snapshot_done"):
            n = self.engine_session.snapshot.count_nodes()
            self.log(f"İndeksleme tamamlandı ({n} dosya/klasör). Arama artık tüm volume'da önbellekten yapılacak.")
            self._update_tree_evidence_label()

    def _start_tree_cached(self, evidence_id: str):
        case_dir = self.case_dir
        def log_both(msg: str):
            import logging
            logging.info(msg)
            self.logger.log_signal.emit(msg)

        def worker():
            try:
                log_both("Kanıt açılıyor: imaj ve önbellek yükleniyor…")
                from backend.engine.pipeline.engine_session import EngineSession
                session = EngineSession(case_dir, evidence_id)
                root_nodes = session.list_root_cached(log_callback=log_both)
                log_both(f"Kök klasör yüklendi: {len(root_nodes)} öğe.")
                if not root_nodes:
                    log_both("Uyarı: Kök klasör boş.")
                else:
                    self.tree_data_ready.emit(session, root_nodes)
                    log_both(f"Partisyon: {session.data_partition.desc} (başlangıç={session.data_partition.start})")
            except Exception as e:
                log_both(f"Hata: {str(e)}")
                log_both(traceback.format_exc())
                err_lower = str(e).lower()
                if any(x in err_lower for x in ("segment", "parça", "missing segment", "chunk")):
                    self.error_message.emit(
                        "E01 parça dosyaları eksik.\n\n"
                        "Tüm segment dosyalarının (E01, E02, E03, ...) aynı klasörde olduğundan emin olun; "
                        "sadece ilk dosyayı (E01) eklemiş olabilirsiniz. E02, E03 vb. dosyaları da aynı klasöre koyup "
                        "kanıtı tekrar ekleyin veya case'i bu klasörden açın."
                    )

        threading.Thread(target=worker, daemon=True).start()
