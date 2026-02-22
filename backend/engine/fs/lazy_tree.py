import pytsk3

TSK_FS_META_FLAG_UNALLOC = getattr(pytsk3, "TSK_FS_META_FLAG_UNALLOC", 0x01)
# Volume label flag
TSK_FS_NAME_FLAG_VOLUME = getattr(pytsk3, "TSK_FS_NAME_FLAG_VOLUME", 0x01)


class LazyFSNode:
    def __init__(self, name, inode, is_dir, size):
        self.name = name
        self.inode = inode
        self.is_dir = is_dir
        self.size = size

    def __repr__(self):
        t = "DIR" if self.is_dir else "FILE"
        return f"<{t}> {self.name} ({self.inode})"


class LazyTreeEngine:
    def __init__(self, img_info, partition_start):
        self.offset = partition_start * 512
        self.fs = pytsk3.FS_Info(img_info, offset=self.offset)

    def _decode_name(self, raw):
        try:
            return raw.decode("utf-8")
        except Exception:
            try:
                return raw.decode("utf-16-le")
            except Exception:
                return raw.decode("latin-1", errors="replace")

    def list_directory(self, inode=None):
        """inode=None kök, inode=xx o klasör."""
        if inode is None:
            directory = self.fs.open_dir(path="/")
        else:
            directory = self.fs.open_dir(inode=inode)

        nodes = []

        for entry in directory:
            if not entry.info.name.name:
                continue

            name = self._decode_name(entry.info.name.name)

            if name in [".", ".."]:
                continue

            meta = entry.info.meta
            if not meta:
                continue

            is_dir = meta.type == pytsk3.TSK_FS_META_TYPE_DIR
            size = meta.size
            inode_addr = meta.addr

            node = LazyFSNode(name, inode_addr, is_dir, size)
            nodes.append(node)

        return nodes

    def get_volume_label(self):
        """Volume etiketini oku."""
        try:
            directory = self.fs.open_dir(path="/")
            for entry in directory:
                if not entry.info.name.name:
                    continue
                flags = getattr(entry.info.name, "flags", 0) or 0
                if flags & TSK_FS_NAME_FLAG_VOLUME:
                    name = self._decode_name(entry.info.name.name)
                    if name and name not in (".", ".."):
                        return name.strip() or None
                    return None
        except Exception:
            pass
        return None

    def list_directory_meta(self, inode=None):
        """list_directory gibi ama dict listesi (cache için)."""
        if inode is None:
            directory = self.fs.open_dir(path="/")
        else:
            directory = self.fs.open_dir(inode=inode)
        out = []
        for entry in directory:
            if not entry.info.name.name:
                continue
            name = self._decode_name(entry.info.name.name)
            if name in [".", ".."]:
                continue
            meta = entry.info.meta
            if not meta:
                continue
            is_dir = meta.type == pytsk3.TSK_FS_META_TYPE_DIR
            size = getattr(meta, "size", 0) or 0
            flags = getattr(meta, "flags", 0) or 0
            deleted = bool(flags & TSK_FS_META_FLAG_UNALLOC)
            out.append({
                "name": name,
                "inode": meta.addr,
                "is_dir": is_dir,
                "size": size,
                "mtime": getattr(meta, "mtime", None),
                "atime": getattr(meta, "atime", None),
                "ctime": getattr(meta, "ctime", None),
                "crtime": getattr(meta, "crtime", None),
                "flags": flags,
                "deleted": deleted,
            })
        return out


def create_lazy_engine(img_info, partition_start):
    return LazyTreeEngine(img_info, partition_start)
