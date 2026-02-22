"""
Dosya/klasör adli inceleme (read-only).
"""
import hashlib
import pytsk3
from datetime import datetime
from typing import Any


TSK_FS_META_FLAG_UNALLOC = getattr(pytsk3, "TSK_FS_META_FLAG_UNALLOC", 0x01)
READ_CHUNK_SIZE = 65536
MAGIC_SIGNATURES = [
    (b"\xff\xd8\xff", "JPEG"),
    (b"\x89PNG\r\n\x1a\n", "PNG"),
    (b"GIF87a", "GIF"),
    (b"GIF89a", "GIF"),
    (b"%PDF", "PDF"),
    (b"PK\x03\x04", "ZIP"),
    (b"PK\x05\x06", "ZIP (empty)"),
    (b"\x1f\x8b", "GZIP"),
    (b"Rar!\x1a\x07", "RAR"),
    (b"BM", "BMP"),
    (b"\x00\x00\x00\x0c", "JPEG2000"),  # jp2
    (b"RIFF", "RIFF"),  # WAV/AVI
    (b"\x00\x00\x00\x18ftyp", "MP4"),
    (b"\x00\x00\x00\x1cftyp", "MP4"),
    (b"ID3", "MP3"),
    (b"\x00\x00\x00\x14ftyp", "MP4"),
]


def _ts_to_str(ts: Any) -> str:
    """Timestamp -> ISO string."""
    if ts is None or ts == 0 or ts == -1:
        return "-"
    try:
        return datetime.utcfromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S UTC")
    except (ValueError, OSError, TypeError):
        return str(ts)


def _get_extension(name: str) -> str:
    """Uzantı (.jpg vb.)."""
    if not name or "." not in name:
        return ""
    return "." + name.rsplit(".", 1)[-1].lower()


def _detect_type_from_magic(head: bytes) -> str:
    """Magic byte'lardan dosya türü."""
    for magic, label in MAGIC_SIGNATURES:
        if head.startswith(magic):
            return label
    return "Unknown"


class ForensicInspector:
    """Dosya/klasör inceleme (read-only)."""

    def __init__(self, fs: Any, img_info: Any):
        self.fs = fs
        self.img_info = img_info

    def _open_entry(self, inode: int):
        """İnode'u dizin olarak aç, ilk girişi al."""
        if inode is None or inode < 0:
            return None, None
        try:
            directory = self.fs.open_dir(inode=inode)
            for entry in directory:
                if entry.info.meta:
                    return entry, entry.info.meta
            return None, None
        except Exception:
            return None, None

    def _get_meta_from_open_meta(self, inode: int):
        """Dosya için open_meta ile meta al."""
        if inode is None or inode < 0:
            return None, None
        try:
            if hasattr(self.fs, "open_meta"):
                f = self.fs.open_meta(inode)
                if f and getattr(f, "info", None) and getattr(f.info, "meta", None):
                    return f, f.info.meta
        except Exception:
            pass
        return None, None

    def get_basic_metadata(self, inode: int) -> dict | None:
        """Temel meta veri."""
        entry, meta = self._open_entry(inode)
        if not meta:
            entry, meta = self._get_meta_from_open_meta(inode)
        if not meta:
            return None
        try:
            is_dir = meta.type == pytsk3.TSK_FS_META_TYPE_DIR
            return {
                "inode": inode,
                "size": getattr(meta, "size", 0) or 0,
                "type": "Directory" if is_dir else "File",
                "mtime": _ts_to_str(getattr(meta, "mtime", None)),
                "atime": _ts_to_str(getattr(meta, "atime", None)),
                "ctime": _ts_to_str(getattr(meta, "ctime", None)),
                "crtime": _ts_to_str(getattr(meta, "crtime", None)),
            }
        except Exception:
            return None

    def is_deleted(self, inode: int) -> bool:
        """İnode silinmiş mi."""
        entry, meta = self._open_entry(inode)
        if not meta:
            _, meta = self._get_meta_from_open_meta(inode)
        if not meta:
            return False
        try:
            flags = getattr(meta, "flags", 0) or 0
            return bool(flags & TSK_FS_META_FLAG_UNALLOC)
        except Exception:
            return False

    def compute_hashes(self, inode: int) -> dict | None:
        """
        Compute MD5 and SHA1 of file content. Reads in chunks (forensically safe for large files).
        Returns {"md5": "...", "sha1": "..."} or None for directories/errors.
        """
        entry, meta = self._open_entry(inode)
        if not entry or not meta:
            entry, size = self._open_file(inode)
            if not entry or size <= 0:
                return None
            meta = getattr(entry, "info", None) and getattr(entry.info, "meta", None)
            if not meta:
                return None
        if meta.type == pytsk3.TSK_FS_META_TYPE_DIR:
            return None
        size = getattr(meta, "size", 0) or 0
        if size < 0:
            return None
        md5 = hashlib.md5()
        sha1 = hashlib.sha1()
        try:
            offset = 0
            while offset < size:
                to_read = min(READ_CHUNK_SIZE, size - offset)
                data = None
                if hasattr(entry, "read_random"):
                    data = entry.read_random(offset, to_read)
                elif hasattr(entry, "read"):
                    data = entry.read(offset, to_read)
                if not data:
                    break
                md5.update(data)
                sha1.update(data)
                offset += len(data)
            return {"md5": md5.hexdigest(), "sha1": sha1.hexdigest()}
        except Exception:
            return None

    def _open_file(self, inode: int):
        """İnode'dan dosya aç."""
        if inode is None or inode < 0:
            return None, 0
        try:
            if hasattr(self.fs, "open_meta"):
                f = self.fs.open_meta(inode)
                if f and getattr(f, "info", None) and getattr(f.info, "meta", None):
                    meta = f.info.meta
                    if meta.type != pytsk3.TSK_FS_META_TYPE_DIR:
                        size = getattr(meta, "size", 0) or 0
                        if size > 0:
                            return f, size
        except Exception:
            pass
        entry, meta = self._open_entry(inode)
        if not entry or not meta or meta.type == pytsk3.TSK_FS_META_TYPE_DIR:
            return None, 0
        size = getattr(meta, "size", 0) or 0
        if size <= 0:
            return None, 0
        return entry, size

    def read_file_content(self, inode: int, offset: int = 0, max_size: int | None = None) -> bytes | None:
        """
        Read file content by inode (read-only, forensic safe).
        For directories returns None. Caps read at max_size to avoid loading huge files.
        """
        entry, size = self._open_file(inode)
        if not entry or size <= 0:
            return None
        cap = (max_size or READ_CHUNK_SIZE * 4)
        to_read = min(size - offset, cap)
        if to_read <= 0:
            return b""
        try:
            if hasattr(entry, "read_random"):
                return entry.read_random(offset, to_read)
            if hasattr(entry, "read"):
                return entry.read(offset, to_read)
        except Exception:
            return None
        return None

    def validate_signature(self, inode: int, name: str | None = None) -> dict | None:
        """
        Read first 512 bytes, detect type from magic bytes, compare with filename extension.
        Returns {"extension": ".jpg", "detected_type": "JPEG", "mismatch": True/False} or None.
        """
        entry, meta = self._open_entry(inode)
        if not entry or not meta:
            return None
        if meta.type == pytsk3.TSK_FS_META_TYPE_DIR:
            return None
        try:
            if hasattr(entry, "read_random"):
                head = entry.read_random(0, 512)
            elif hasattr(entry, "read"):
                head = entry.read(0, 512)
            else:
                head = b""
            if not head:
                head = b""
            detected = _detect_type_from_magic(head)
            ext = _get_extension(name or "")
            # Uzantı-tür eşlemesi
            ext_to_type = {
                ".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".gif": "GIF",
                ".pdf": "PDF", ".zip": "ZIP", ".mp3": "MP3", ".mp4": "MP4",
                ".bmp": "BMP", ".rar": "RAR", ".gz": "GZIP", ".wav": "RIFF",
            }
            expected = ext_to_type.get(ext, "")
            mismatch = bool(ext and expected and detected != "Unknown" and detected != expected)
            return {
                "extension": ext or "-",
                "detected_type": detected,
                "mismatch": mismatch,
            }
        except Exception:
            return None

    # Gelecekte: browser_history, registry_hive vb.
