"""
Dosya listesi tablo modeli. EngineSession ve Snapshot'tan veri gelir.
Sütunlar: Seç, Ad, Inode, Boyut, Tür, Değiştirilme, Erişim, Oluşturulma, Silindi.
"""
from datetime import datetime
from PyQt6.QtCore import Qt, QAbstractTableModel, QModelIndex, QFileInfo
from PyQt6.QtGui import QColor, QIcon, QPixmap
from PyQt6.QtWidgets import QApplication, QStyle, QFileIconProvider


def _ts_to_display(ts) -> str:
    if ts is None or ts == 0 or ts == -1:
        return ""
    try:
        return datetime.utcfromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OSError, TypeError):
        return str(ts)


def _extension_from_name(name: str) -> str:
    """Dosya adından uzantı."""
    if not name or not isinstance(name, str):
        return "Dosya"
    name = name.strip()
    if "." in name and not name.endswith("."):
        ext = name.rsplit(".", 1)[-1].strip()
        if ext:
            return "." + ext
    return "Dosya"


# Uzantıya göre sistem ikonu (önbellekli)
_icon_provider = None
_extension_icon_cache = {}


def _icon_for_extension(ext: str) -> QIcon:
    """Uzantıya göre sistem ikonu."""
    global _icon_provider, _extension_icon_cache
    if ext == "Dosya":
        ext = ""
    key = ext or "_generic"
    if key in _extension_icon_cache:
        return _extension_icon_cache[key]
    if _icon_provider is None:
        _icon_provider = QFileIconProvider()
    # Geçici dosya adı ile sistem ikonu al
    dummy_name = f"dummy{ext}" if ext else "dummy"
    icon = _icon_provider.icon(QFileInfo(dummy_name))
    if icon.isNull():
        icon = QApplication.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)
    _extension_icon_cache[key] = icon
    return icon


class FileListTableModel(QAbstractTableModel):
    """Dosya listesi tablosu. checked_inodes: dışa aktarma için işaretlenenler."""

    COL_SEL, COL_NAME, COL_INODE, COL_SIZE, COL_TYPE, COL_MODIFIED, COL_ACCESSED, COL_CREATED, COL_DELETED = range(9)
    HEADERS = ("Seç", "Ad", "Inode", "Boyut", "Tür", "Değiştirilme", "Erişim", "Oluşturulma", "Silindi")

    def __init__(self, parent=None, checked_inodes: set | None = None):
        super().__init__(parent)
        self._nodes = []
        self._thumb_icons = {}
        self._checked_inodes = set() if checked_inodes is None else checked_inodes

    def set_nodes(self, nodes: list):
        self.beginResetModel()
        self._nodes = list(nodes) if nodes else []
        self.endResetModel()

    def set_thumbnail_icon(self, inode: int, path: str | None):
        """İnode için thumbnail ikonunu ayarla."""
        if path:
            try:
                pix = QPixmap(path)
                if not pix.isNull():
                    self._thumb_icons[inode] = QIcon(pix.scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                else:
                    self._thumb_icons.pop(inode, None)
            except Exception:
                self._thumb_icons.pop(inode, None)
        else:
            self._thumb_icons.pop(inode, None)
        for row in range(len(self._nodes)):
            if self._nodes[row].get("inode") == inode:
                self.dataChanged.emit(
                    self.index(row, self.COL_NAME), self.index(row, self.COL_NAME), [Qt.ItemDataRole.DecorationRole]
                )
                break

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self._nodes)

    def columnCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation != Qt.Orientation.Horizontal or role != Qt.ItemDataRole.DisplayRole:
            return None
        if 0 <= section < len(self.HEADERS):
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() < 0 or index.row() >= len(self._nodes):
            return None
        node = self._nodes[index.row()]
        col = index.column()
        if col == self.COL_SEL and role == Qt.ItemDataRole.CheckStateRole:
            ino = node.get("inode")
            return Qt.CheckState.Checked if (ino is not None and ino in self._checked_inodes) else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.DisplayRole:
            if col == self.COL_NAME:
                return node.get("name", "")
            if col == self.COL_INODE:
                ino = node.get("inode")
                return str(ino) if ino is not None else ""
            if col == self.COL_SIZE:
                s = node.get("size") or 0
                return str(s) if not node.get("is_dir") else ""
            if col == self.COL_TYPE:
                if node.get("is_dir"):
                    return "Klasör"
                return _extension_from_name(node.get("name", ""))
            if col == self.COL_MODIFIED:
                return _ts_to_display(node.get("mtime"))
            if col == self.COL_ACCESSED:
                return _ts_to_display(node.get("atime"))
            if col == self.COL_CREATED:
                return _ts_to_display(node.get("crtime") or node.get("ctime"))
            if col == self.COL_DELETED:
                return "Evet" if node.get("deleted") else "Hayır"
        if role == Qt.ItemDataRole.ToolTipRole:
            if col == self.COL_SEL:
                return "Dışarı aktarma için seç"
            if col == self.COL_NAME:
                return node.get("name", "") or ""
            if col == self.COL_INODE:
                ino = node.get("inode")
                return str(ino) if ino is not None else ""
            if col == self.COL_SIZE:
                s = node.get("size") or 0
                return str(s) if not node.get("is_dir") else ""
            if col == self.COL_TYPE:
                if node.get("is_dir"):
                    return "Klasör"
                return _extension_from_name(node.get("name", ""))
            if col == self.COL_MODIFIED:
                return _ts_to_display(node.get("mtime"))
            if col == self.COL_ACCESSED:
                return _ts_to_display(node.get("atime"))
            if col == self.COL_CREATED:
                return _ts_to_display(node.get("crtime") or node.get("ctime"))
            if col == self.COL_DELETED:
                return "Evet" if node.get("deleted") else "Hayır"
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col == self.COL_SEL:
                return int(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            if col == self.COL_NAME:
                return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            if col == self.COL_INODE:
                return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            if col == self.COL_SIZE:
                return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            if col in (self.COL_TYPE, self.COL_MODIFIED, self.COL_ACCESSED, self.COL_CREATED, self.COL_DELETED):
                return int(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ForegroundRole and col != self.COL_DELETED and col != self.COL_SEL and node.get("deleted"):
            return QColor(Qt.GlobalColor.darkRed)
        if role == Qt.ItemDataRole.DecorationRole and col == self.COL_NAME:
            inode = node.get("inode")
            if inode is not None and inode in self._thumb_icons:
                return self._thumb_icons[inode]
            if node.get("is_dir"):
                return QApplication.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
            ext = _extension_from_name(node.get("name", ""))
            return _icon_for_extension(ext)
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        f = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
        if index.column() == self.COL_SEL:
            f |= Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEditable
        return f

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid() or index.column() != self.COL_SEL or role != Qt.ItemDataRole.CheckStateRole:
            return False
        node = self._nodes[index.row()]
        ino = node.get("inode")
        if ino is None:
            return False
        if value in (Qt.CheckState.Checked, getattr(Qt.CheckState.Checked, "value", 2)):
            self._checked_inodes.add(ino)
        else:
            self._checked_inodes.discard(ino)
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole])
        return True

    def _type_for_node(self, node: dict) -> str:
        if node.get("is_dir"):
            return "Klasör"
        return _extension_from_name(node.get("name", ""))

    def _sort_key(self, node: dict, column: int):
        if column == self.COL_SEL:
            ino = node.get("inode")
            return 1 if (ino is not None and ino in self._checked_inodes) else 0
        if column == self.COL_NAME:
            return (node.get("name") or "").lower()
        if column == self.COL_INODE:
            v = node.get("inode")
            return (v is not None and v >= 0) and v or -1
        if column == self.COL_SIZE:
            return node.get("size") or 0
        if column == self.COL_TYPE:
            return self._type_for_node(node)
        if column == self.COL_MODIFIED:
            t = node.get("mtime")
            return t if t is not None and t != -1 else 0
        if column == self.COL_ACCESSED:
            t = node.get("atime")
            return t if t is not None and t != -1 else 0
        if column == self.COL_CREATED:
            t = node.get("crtime") or node.get("ctime")
            return t if t is not None and t != -1 else 0
        if column == self.COL_DELETED:
            return 1 if node.get("deleted") else 0
        return 0

    def sort(self, column: int, order=Qt.SortOrder.AscendingOrder):
        if not self._nodes or column < 0 or column >= len(self.HEADERS):
            return
        reverse = order == Qt.SortOrder.DescendingOrder
        self.layoutAboutToBeChanged.emit()
        self._nodes.sort(key=lambda n: self._sort_key(n, column), reverse=reverse)
        self.layoutChanged.emit()

    def get_node_at(self, row: int) -> dict | None:
        if 0 <= row < len(self._nodes):
            return self._nodes[row]
        return None

    def get_nodes(self) -> list:
        """Şu anki node listesi (preview koleksiyonu için)."""
        return list(self._nodes)
