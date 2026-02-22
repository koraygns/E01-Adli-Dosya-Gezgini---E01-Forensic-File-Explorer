from PyQt6.QtCore import Qt, QAbstractItemModel, QModelIndex


class TreeItem:
    def __init__(self, name, inode, is_dir, size, parent=None):
        self.name = name
        self.inode = inode
        self.is_dir = is_dir
        self.size = size
        self.parent = parent
        self.children = []
        self.fetched = False  # lazy yüklendi mi

    def child_count(self):
        return len(self.children)

    def child(self, row):
        return self.children[row]

    def row(self):
        if self.parent is None:
            return 0
        return self.parent.children.index(self)


class LazyTreeModel(QAbstractItemModel):
    def __init__(self, engine_session, root_nodes, parent=None):
        super().__init__(parent)
        self.engine = engine_session
        self.root = TreeItem("ROOT", inode=None, is_dir=True, size=0, parent=None)

        # Root children ilk yükleme
        for n in root_nodes:
            item = TreeItem(n.name, n.inode, n.is_dir, n.size, parent=self.root)
            # Klasörse placeholder ekle
            if item.is_dir:
                item.children.append(TreeItem("...", inode=-1, is_dir=False, size=0, parent=item))
            self.root.children.append(item)

        self.root.fetched = True
        self.layoutChanged.emit()

    # Qt model
    def columnCount(self, parent=QModelIndex()):
        return 1

    def rowCount(self, parent=QModelIndex()):
        if not parent.isValid():
            return self.root.child_count()
        item = parent.internalPointer()
        return item.child_count()

    def index(self, row, column, parent=QModelIndex()):
        if not self.hasIndex(row, column, parent):
            return QModelIndex()

        if not parent.isValid():
            parent_item = self.root
        else:
            parent_item = parent.internalPointer()

        child_item = parent_item.child(row)
        if child_item:
            return self.createIndex(row, column, child_item)
        return QModelIndex()

    def parent(self, index):
        if not index.isValid():
            return QModelIndex()

        child_item = index.internalPointer()
        parent_item = child_item.parent

        if parent_item is None or parent_item == self.root:
            return QModelIndex()

        return self.createIndex(parent_item.row(), 0, parent_item)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        item = index.internalPointer()
        if role == Qt.ItemDataRole.DisplayRole:
            return str(item.name) if item.name else ""
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def headerData(self, section, orientation, role):
        if role == Qt.ItemDataRole.DisplayRole:
            return "Dosya Sistemi"
        return None

    def hasChildren(self, parent=QModelIndex()):
        item = self._item_from_index(parent)
        if not item.is_dir:
            return False
        # Henüz yüklenmemiş klasör: ok göster (tıklanınca fetch edilecek)
        if not item.fetched:
            return True
        # Yüklendiyse sadece altında en az bir klasör varsa ok göster (sadece dosya varsa > çıkmasın)
        return any(c.is_dir for c in item.children)

    def canFetchMore(self, parent):
        item = self._item_from_index(parent)
        # klasör ve daha önce fetch edilmemişse fetch edilebilir
        return item.is_dir and not item.fetched

    def fetchMore(self, parent):
        item = self._item_from_index(parent)
        if item.fetched or not item.is_dir or item.inode is None:
            return

        # placeholder temizle
        self.beginRemoveRows(parent, 0, item.child_count() - 1)
        item.children.clear()
        self.endRemoveRows()

        # engine'den çocukları çek
        nodes = self.engine.list_children(item.inode)

        self.beginInsertRows(parent, 0, len(nodes) - 1 if nodes else 0)
        for n in nodes:
            child = TreeItem(n.name, n.inode, n.is_dir, n.size, parent=item)
            if child.is_dir:
                child.children.append(TreeItem("...", inode=-1, is_dir=False, size=0, parent=child))
            item.children.append(child)
        self.endInsertRows()

        item.fetched = True
        # Parent satırını yeniden çiz (altında klasör yoksa > hemen kalkması için)
        self.dataChanged.emit(parent, parent, [])

    def _item_from_index(self, index):
        if index.isValid():
            return index.internalPointer()
        return self.root
