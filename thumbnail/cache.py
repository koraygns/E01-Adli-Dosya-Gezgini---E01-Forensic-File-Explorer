"""
Thumbnail cache: SHA1-based cache keys, directory management, read-only evidence handling.
Production-grade for digital forensics; never modifies original evidence.
"""
import hashlib
import logging
import os

logger = logging.getLogger(__name__)

# Subdirectory under case cache for thumbnails
THUMBS_SUBDIR = "thumbs"
# Thumbnail file extension (always JPEG for consistency)
THUMB_EXT = ".jpg"
# Max thumbnail dimension (pixels)
MAX_THUMB_SIZE = 256


def _normalize_path_for_hash(path: str) -> str:
    """Normalize file path for stable SHA1 hashing (e.g. consistent slashes)."""
    if not path:
        return ""
    return os.path.normpath(os.path.abspath(path))


def path_to_cache_key(file_path: str) -> str:
    """
    Return SHA1 hash of file path for use as cache filename (no extension).
    Deterministic and safe for very large datasets.
    """
    normalized = _normalize_path_for_hash(file_path)
    return hashlib.sha1(normalized.encode("utf-8", errors="replace")).hexdigest()


def get_thumbs_dir(case_cache_dir: str) -> str:
    """Return the thumbs subdirectory under case cache; ensure it exists."""
    base = os.path.abspath(case_cache_dir)
    thumbs = os.path.join(base, THUMBS_SUBDIR)
    try:
        os.makedirs(thumbs, exist_ok=True)
    except OSError as e:
        logger.warning("Could not create thumbs cache dir %s: %s", thumbs, e)
    return thumbs


def get_cached_thumbnail_path(file_path: str, case_cache_dir: str) -> str:
    """
    Return the path where the thumbnail for file_path would be stored.
    Does not check existence; use for both lookup and write.
    """
    thumbs_dir = get_thumbs_dir(case_cache_dir)
    key = path_to_cache_key(file_path)
    return os.path.join(thumbs_dir, key + THUMB_EXT)


def is_cached(file_path: str, case_cache_dir: str) -> bool:
    """Return True if a valid cached thumbnail exists for this file path."""
    path = get_cached_thumbnail_path(file_path, case_cache_dir)
    return os.path.isfile(path) and os.path.getsize(path) > 0
