"""
Portable FFmpeg lookup: system PATH first, then bundled third_party/ffmpeg/bin.
Cross-platform (Windows/Linux/macOS). Used for video thumbnail extraction.
"""
import os
import shutil
from pathlib import Path
from typing import Optional

# Proje kökü (4 üst klasör)
_PROJECT_ROOT: Optional[Path] = None


def _get_project_root() -> Path:
    global _PROJECT_ROOT
    if _PROJECT_ROOT is not None:
        return _PROJECT_ROOT
    _PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
    return _PROJECT_ROOT


def _bundled_ffmpeg_path() -> Path:
    """Proje içi ffmpeg yolu."""
    root = _get_project_root()
    if os.name == "nt":
        return root / "third_party" / "ffmpeg" / "bin" / "ffmpeg.exe"
    return root / "third_party" / "ffmpeg" / "bin" / "ffmpeg"


def find_ffmpeg() -> Optional[str]:
    """
    Locate ffmpeg executable for video thumbnail extraction.

    1. Try system PATH (shutil.which).
    2. Fallback to project_root/third_party/ffmpeg/bin/ffmpeg[.exe].

    Returns absolute path string, or None if not found. Caller should fail gracefully.
    """
    # 1) System PATH
    path_cmd = shutil.which("ffmpeg")
    if path_cmd:
        return path_cmd

    # 2) Bundled binary
    bundled = _bundled_ffmpeg_path()
    if bundled.is_file() and os.access(bundled, os.X_OK):
        return str(bundled)

    return None
