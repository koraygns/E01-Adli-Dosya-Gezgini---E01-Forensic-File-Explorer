"""
Video thumbnail generation: ffmpeg frame extraction at 1 second.
Read-only access to evidence; never modifies source files.
Uses find_ffmpeg() for portable or system ffmpeg.
"""
import logging
import os
import subprocess

from .cache import MAX_THUMB_SIZE

logger = logging.getLogger(__name__)


def _get_ffmpeg() -> str | None:
    """Resolve ffmpeg binary (PATH or third_party)."""
    try:
        from backend.engine.io.ffmpeg_finder import find_ffmpeg
        return find_ffmpeg()
    except Exception:
        return None

# Supported video extensions (lowercase)
VIDEO_EXTENSIONS = frozenset({".mp4", ".avi", ".mkv", ".mov", ".webm"})


def _get_extension(path: str) -> str:
    if not path or "." not in os.path.basename(path):
        return ""
    return "." + path.rsplit(".", 1)[-1].lower()


def is_supported(path: str) -> bool:
    """Return True if the path has a supported video extension."""
    return _get_extension(path) in VIDEO_EXTENSIONS


def generate(
    source_path: str,
    out_path: str,
    max_size: int = MAX_THUMB_SIZE,
    time_sec: float = 1.0,
    ffmpeg_timeout: int = 15,
) -> bool:
    """
    Extract a frame at time_sec (default 1s) and save as JPEG thumbnail.
    Uses ffmpeg; scales to fit within max_size. Returns True on success.
    """
    if not os.path.isfile(source_path):
        logger.debug("Not a file: %s", source_path)
        return False
    if not is_supported(source_path):
        return False
    ffmpeg_exe = _get_ffmpeg()
    if not ffmpeg_exe:
        logger.debug("ffmpeg not found; skip video thumbnail")
        return False
    try:
        cmd = [
            ffmpeg_exe,
            "-y",
            "-ss", str(time_sec),
            "-i", source_path,
            "-vframes", "1",
            "-vf", f"scale='min({max_size},iw)':'min({max_size},ih)':force_original_aspect_ratio=decrease",
            "-f", "image2",
            out_path,
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=ffmpeg_timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if result.returncode != 0:
            logger.debug("ffmpeg failed for %s: %s", source_path, (result.stderr or b"")[:200])
            return False
        if not os.path.isfile(out_path) or os.path.getsize(out_path) == 0:
            return False
        return True
    except subprocess.TimeoutExpired:
        logger.debug("ffmpeg timeout for %s", source_path)
        return False
    except Exception as e:
        logger.debug("Video thumbnail failed for %s: %s", source_path, e)
        return False
