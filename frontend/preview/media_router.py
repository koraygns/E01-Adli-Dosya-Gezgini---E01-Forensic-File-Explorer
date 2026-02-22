"""
Dosya türüne göre viewer seçer.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

# Viewer routing uzantıları
EXT_IMAGE = {
    ".jpg", ".jpeg", ".jpe", ".jfif", ".png", ".apng", ".bmp", ".dib",
    ".gif", ".webp", ".tiff", ".tif", ".ico", ".cur", ".ppm", ".pgm", ".pbm",
    ".pnm", ".pcx", ".tga", ".jp2", ".j2k", ".heic", ".heif",
}
EXT_VIDEO = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".wmv", ".m4v", ".flv"}
EXT_PDF = {".pdf"}
EXT_TXT = {".txt", ".log", ".csv", ".json", ".xml", ".md", ".py", ".js", ".html", ".css", ".cfg", ".ini", ".conf"}
EXT_OFFICE = {".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".odt", ".ods", ".odp"}


class ViewerType(Enum):
    IMAGE = "image"
    VIDEO = "video"
    PDF = "pdf"
    TXT = "txt"
    OFFICE = "office"
    PLACEHOLDER = "placeholder"


def _extension(name: str) -> str:
    if not name or "." not in name:
        return ""
    return "." + name.rsplit(".", 1)[-1].lower()


class MediaRouter:
    """Öğeyi ViewerType'a yönlendir."""

    @staticmethod
    def route(item: dict[str, Any] | None) -> ViewerType:
        """Bu öğe için viewer türü."""
        if not item:
            return ViewerType.PLACEHOLDER
        if item.get("is_dir"):
            return ViewerType.PLACEHOLDER
        try:
            size = item.get("size")
            if size is not None and int(size) == 0:
                return ViewerType.PLACEHOLDER
        except (TypeError, ValueError):
            pass
        name = item.get("name") or ""
        ext = _extension(name)
        if ext in EXT_IMAGE:
            return ViewerType.IMAGE
        if ext in EXT_VIDEO:
            return ViewerType.VIDEO
        if ext in EXT_PDF:
            return ViewerType.PDF
        if ext in EXT_TXT:
            return ViewerType.TXT
        if ext in EXT_OFFICE:
            return ViewerType.OFFICE
        return ViewerType.PLACEHOLDER

    @staticmethod
    def can_preview(item: dict[str, Any] | None) -> bool:
        """Gerçek viewer alır mı."""
        return MediaRouter.route(item) != ViewerType.PLACEHOLDER
