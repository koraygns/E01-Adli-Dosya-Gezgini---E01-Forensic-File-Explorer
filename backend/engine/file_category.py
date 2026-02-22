"""
Dosya kategorizasyonu: thumbnail pipeline öncesi sınıflandırma.
Sadece NORMAL_MEDIA thumbnail kuyruğuna girer; ZERO_BYTE ve UNSUPPORTED grid’i kirletmez.
"""
import os
from enum import Enum

from backend.engine.thumbnail.thumbnail_manager import THUMB_EXT_ALL


class FileCategory(Enum):
    """Dosya kategorisi."""
    NORMAL_MEDIA = "normal_media"   # thumbnail üretilebilir
    ZERO_BYTE = "zero_byte"         # 0 byte dosya
    UNSUPPORTED = "unsupported"      # desteklenmeyen format veya decode edilemeyen


def _extension(name: str) -> str:
    if not name or "." not in name:
        return ""
    return "." + name.rsplit(".", 1)[-1].lower()


def is_supported_media(name: str) -> bool:
    """Medya uzantısı mı."""
    return _extension(name) in THUMB_EXT_ALL


def categorize_node(node: dict) -> FileCategory:
    """Node'u kategorize et."""
    if not node:
        return FileCategory.UNSUPPORTED
    if bool(node.get("is_dir")):
        return FileCategory.NORMAL_MEDIA  # klasörler grid’de gösterilir, thumbnail yok
    size = node.get("size")
    if size is not None and int(size) == 0:
        return FileCategory.ZERO_BYTE
    name = node.get("name") or ""
    if not is_supported_media(name):
        return FileCategory.UNSUPPORTED
    return FileCategory.NORMAL_MEDIA


def categorize_file(file_path: str) -> FileCategory:
    """
    Dosya yolu ile kategorize et (path-based pipeline için).
    Okuma: sadece os.path.getsize + uzantı (forensic: evidence’a yazmaz).
    """
    if not file_path or not os.path.exists(file_path):
        return FileCategory.UNSUPPORTED
    if os.path.isdir(file_path):
        return FileCategory.NORMAL_MEDIA
    try:
        size = os.path.getsize(file_path)
    except OSError:
        return FileCategory.UNSUPPORTED
    if size == 0:
        return FileCategory.ZERO_BYTE
    if not is_supported_media(file_path):
        return FileCategory.UNSUPPORTED
    return FileCategory.NORMAL_MEDIA
