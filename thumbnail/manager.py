"""
Thumbnail manager: lazy-loading, cache-first, ThreadPoolExecutor-based generation.

Architecture (X-Ways style):
  - TreeView / directory listing → use PAGINATION (chunked listing) for 10k+ file folders.
  - Thumbnails (grid view)       → LAZY ASYNC + CACHE only; no pagination.
                                   Request on scroll; return immediately if cached,
                                   otherwise schedule background generation and notify via callback.

Production-grade for forensics; read-only evidence access, never modifies originals.
"""
import logging
import os
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable, Optional

from . import image_thumb
from . import video_thumb
from .cache import (
    get_cached_thumbnail_path,
    get_thumbs_dir,
    is_cached,
)

logger = logging.getLogger(__name__)

# Default max workers; keep low to avoid thrashing on large evidence
DEFAULT_MAX_WORKERS = 4
# Supported extensions union for quick "can we thumbnail?" check
SUPPORTED_EXTENSIONS = image_thumb.IMAGE_EXTENSIONS | video_thumb.VIDEO_EXTENSIONS


def _extension(path: str) -> str:
    if not path or "." not in os.path.basename(path):
        return ""
    return "." + path.rsplit(".", 1)[-1].lower()


def _is_supported(path: str) -> bool:
    return _extension(path) in SUPPORTED_EXTENSIONS


def _generate_thumbnail(file_path: str, case_cache_dir: str) -> Optional[str]:
    """
    Generate thumbnail for file_path and save to case cache. Called from worker thread.
    Returns thumbnail path on success, None on skip/failure. Read-only on file_path.
    """
    if not os.path.isfile(file_path):
        logger.debug("Not a file: %s", file_path)
        return None
    ext = _extension(file_path)
    if ext not in SUPPORTED_EXTENSIONS:
        return None
    out_path = get_cached_thumbnail_path(file_path, case_cache_dir)
    if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
        return out_path
    ok = False
    if ext in image_thumb.IMAGE_EXTENSIONS:
        ok = image_thumb.generate(file_path, out_path)
    elif ext in video_thumb.VIDEO_EXTENSIONS:
        ok = video_thumb.generate(file_path, out_path)
    if ok and os.path.isfile(out_path):
        return out_path
    return None


# Callback type: invoked with thumbnail path (or "") when generation completes. May be called from worker thread.
ThumbnailCallback = Callable[[str], None]


class ThumbnailManager:
    """
    High-performance, lazy-loading thumbnail service with case cache and thread pool.
    Safe for very large datasets; one generation per file (deduplicated in-flight).
    """

    def __init__(self, max_workers: int = DEFAULT_MAX_WORKERS):
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        # cache_key -> (Future, list of callbacks to run when done)
        self._in_progress: dict[str, tuple[Future[Optional[str]], list[ThumbnailCallback]]] = {}
        self._lock = threading.Lock()

    def request_thumbnail(
        self,
        file_path: str,
        case_cache_dir: str,
        callback: Optional[ThumbnailCallback] = None,
    ) -> str:
        """
        Request thumbnail for grid/tree view — non-blocking, scroll-safe.

        - If cached: returns path immediately; callback is NOT called.
        - If not cached: returns "" and schedules background generation; when done,
          callback(thumb_path) is invoked (from a worker thread — marshal to main thread in GUI).

        Use this when the user scrolls: call for each visible item; cached items show at once,
        others appear when generation completes via callback. No pagination needed for thumbnails.
        """
        if not file_path or not case_cache_dir:
            return ""
        if not _is_supported(file_path):
            return ""
        if is_cached(file_path, case_cache_dir):
            return get_cached_thumbnail_path(file_path, case_cache_dir)
        file_path = os.path.abspath(file_path)
        cache_key = get_cached_thumbnail_path(file_path, case_cache_dir)
        with self._lock:
            entry = self._in_progress.get(cache_key)
            if entry is not None:
                fut, callbacks = entry
                if callback is not None:
                    callbacks.append(callback)
                return ""
            fut = self._executor.submit(_generate_thumbnail, file_path, case_cache_dir)
            callbacks: list[ThumbnailCallback] = [callback] if callback else []
            self._in_progress[cache_key] = (fut, callbacks)

        def _done(f: Future[Optional[str]]) -> None:
            try:
                result = (f.result() or "").strip()
            except Exception as e:
                logger.debug("Thumbnail generation error for %s: %s", file_path, e)
                result = ""
            with self._lock:
                entry = self._in_progress.pop(cache_key, None)
                pending = list(entry[1]) if entry else []
            for cb in pending:
                try:
                    cb(result)
                except Exception as e:
                    logger.debug("Thumbnail callback error: %s", e)

        fut.add_done_callback(_done)
        return ""

    def get_thumbnail(self, file_path: str, case_cache_dir: str) -> str:
        """
        Return path to thumbnail (blocking). If cached, returns immediately.
        If not cached, runs generation in pool and returns when done.
        Prefer request_thumbnail() from UI for non-blocking scroll.
        """
        if not file_path or not case_cache_dir:
            return ""
        if not _is_supported(file_path):
            return ""
        if is_cached(file_path, case_cache_dir):
            return get_cached_thumbnail_path(file_path, case_cache_dir)
        file_path = os.path.abspath(file_path)
        cache_key = get_cached_thumbnail_path(file_path, case_cache_dir)
        with self._lock:
            entry = self._in_progress.get(cache_key)
            if entry is not None:
                fut, _ = entry
            else:
                fut = self._executor.submit(_generate_thumbnail, file_path, case_cache_dir)
                self._in_progress[cache_key] = (fut, [])
        try:
            result = fut.result()
            return result or ""
        except Exception as e:
            logger.debug("Thumbnail generation error for %s: %s", file_path, e)
            return ""
        finally:
            with self._lock:
                self._in_progress.pop(cache_key, None)

    def shutdown(self, wait: bool = True) -> None:
        """Shutdown the thread pool. wait=False for quick teardown."""
        self._executor.shutdown(wait=wait)


# Module-level default manager for simple API
_default_manager: Optional[ThumbnailManager] = None
_default_lock = threading.Lock()


def request_thumbnail(
    file_path: str,
    case_cache_dir: str,
    callback: Optional[ThumbnailCallback] = None,
) -> str:
    """
    Non-blocking: return path if cached, else "" and schedule generation; callback(path) when done.
    Use from grid view on scroll — never blocks UI. Callback may run on worker thread; marshal to main thread in GUI.
    """
    with _default_lock:
        if _default_manager is None:
            _default_manager = ThumbnailManager()
        return _default_manager.request_thumbnail(file_path, case_cache_dir, callback)


def get_thumbnail(file_path: str, case_cache_dir: str) -> str:
    """
    Blocking: return path when ready. Prefer request_thumbnail() from UI for scroll-safe lazy load.
    """
    with _default_lock:
        if _default_manager is None:
            _default_manager = ThumbnailManager()
        return _default_manager.get_thumbnail(file_path, case_cache_dir)


def get_manager() -> ThumbnailManager:
    """Return the shared default manager (e.g. for shutdown)."""
    with _default_lock:
        if _default_manager is None:
            _default_manager = ThumbnailManager()
        return _default_manager
