import pytsk3


class FSNode:
    def __init__(self, name, path, is_dir, size):
        self.name = name
        self.path = path
        self.is_dir = is_dir
        self.size = size
        self.children = []

    def to_dict(self):
        return {
            "name": self.name,
            "path": self.path,
            "is_dir": self.is_dir,
            "size": self.size,
            "children": [c.to_dict() for c in self.children],
        }


def scan_directory(fs, directory, parent_path="/"):
    nodes = []

    for entry in directory:
        if not entry.info.name.name:
            continue

        raw_name = entry.info.name.name

        try:
            name = raw_name.decode("utf-8")
        except:
            try:
                name = raw_name.decode("utf-16-le")
            except:
                name = raw_name.decode("latin-1", errors="replace")

        if name in [".", ".."]:
            continue

        meta = entry.info.meta
        is_dir = meta and meta.type == pytsk3.TSK_FS_META_TYPE_DIR
        size = meta.size if meta else 0

        full_path = parent_path + name
        node = FSNode(name, full_path, is_dir, size)

        if is_dir:
            try:
                subdir = fs.open_dir(inode=meta.addr)
                node.children = scan_directory(fs, subdir, full_path + "/")
            except Exception:
                pass

        nodes.append(node)

    return nodes


def parse_filesystem(img_info, partition_start):
    offset = partition_start * 512

    fs = pytsk3.FS_Info(img_info, offset=offset)
    root = fs.open_dir(path="/")

    tree = scan_directory(fs, root)
    return tree
