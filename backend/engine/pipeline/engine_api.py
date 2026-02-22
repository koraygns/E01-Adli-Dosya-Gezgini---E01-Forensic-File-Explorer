from backend.engine.io.ewf_reader import open_ewf_image
from backend.engine.volume.volume_parser import parse_partitions
from backend.engine.fs.lazy_tree import LazyTreeEngine
from backend.engine.metadata.inspector import ForensicInspector


class EngineSession:
    """E01 session: img açık, lazy engine hazır."""
    def __init__(self, e01_path: str):
        self.e01_path = e01_path
        self.img = open_ewf_image(e01_path)
        self.partitions = parse_partitions(self.img)

        self.data_partition = None
        # 0 boyutlu partition atlanır
        def _has_size(p):
            return getattr(p, "length", 0) and p.length > 0

        # Önce bilinen FS tiplerini dene
        for p in self.partitions:
            if not _has_size(p):
                continue
            desc = p.desc.upper()
            if any(fs in desc for fs in ["FAT", "NTFS", "EXFAT", "EXT", "HFS", "APFS"]):
                self.data_partition = p
                break

        # Mount edilebilen ilk partition
        if not self.data_partition:
            for p in self.partitions:
                if not _has_size(p):
                    continue
                try:
                    LazyTreeEngine(self.img, p.start)
                    self.data_partition = p
                    break
                except Exception:
                    continue

        # 3) RAW filesystem fallback (partition yok ama FS olabilir)
        if not self.data_partition:
            try:
                _ = LazyTreeEngine(self.img, 0)  # offset 0 dene
                self.data_partition = type("RawPartition", (), {
                    "start": 0,
                    "desc": "RAW Filesystem (no partition table)"
                })()
            except Exception:
                raise RuntimeError(
                    "Hiçbir partition mount edilemedi ve raw filesystem da açılamadı "
                    "(bozuk veya unsupported FS olabilir)."
                )

        self.lazy = LazyTreeEngine(self.img, self.data_partition.start)
        self.inspector = ForensicInspector(self.lazy.fs, self.img)

    def list_root(self):
        return self.lazy.list_directory(None)

    def list_children(self, inode: int):
        return self.lazy.list_directory(inode)

    def get_metadata(self, inode: int, name: str | None = None) -> dict | None:
        """Meta veri (inspector'dan)."""
        meta = self.inspector.get_basic_metadata(inode)
        if meta is None:
            return None
        meta["name"] = name if name is not None else meta.get("name", "")
        return meta

    def get_hashes(self, inode: int) -> dict | None:
        """MD5/SHA1 hesapla."""
        return self.inspector.compute_hashes(inode)

    def is_deleted(self, inode: int) -> bool:
        """İnode silinmiş mi."""
        return self.inspector.is_deleted(inode)

    def validate_signature(self, inode: int, name: str | None = None) -> dict | None:
        """Dosya imza kontrolü."""
        return self.inspector.validate_signature(inode, name=name)
