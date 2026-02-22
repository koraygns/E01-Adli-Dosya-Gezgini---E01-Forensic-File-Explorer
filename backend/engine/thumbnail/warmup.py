"""
Thumbnail warmup: görünür medya öncelikli, iptal ve ilerleme destekli.
"""
import logging
import threading
from typing import Callable

from backend.engine.file_category import FileCategory
from backend.engine.utils.cancel_token import CancellationToken

logger = logging.getLogger(__name__)

# Overlay kapanacak hazır thumbnail sayısı
WARMUP_COUNT_DEFAULT = 150

# Performans: sadece listenin bu kadar öğesini tara (1M klasörde 2.5k ile sınırlı)
CANDIDATES_SCAN_LIMIT = 2500


def warmup_thumbnails_inode(
    nodes: list[dict],
    thumb_manager,
    warmup_count: int = WARMUP_COUNT_DEFAULT,
    cancel_token: CancellationToken | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> None:
    """İlk NORMAL_MEDIA node'lar için thumbnail warmup."""
    if not thumb_manager or not nodes:
        if progress_callback:
            progress_callback(0, 0)
        return

    token = cancel_token or CancellationToken()
    # Thumbnail alınabilecek node listesi
    candidates: list[dict] = []
    scan_limit = min(len(nodes), CANDIDATES_SCAN_LIMIT)
    for n in nodes[:scan_limit]:
        if n.get("category") != FileCategory.NORMAL_MEDIA:
            continue
        if n.get("is_dir"):
            continue
        inode = n.get("inode")
        name = n.get("name") or ""
        if not thumb_manager.should_thumbnail(inode, name, False):
            continue
        candidates.append(n)

    total = len(candidates)
    if total == 0:
        logger.info("Thumbnail ısındırma: bu klasörde thumbnail alınacak medya dosyası yok.")
        if progress_callback:
            progress_callback(0, 0)
        return

    if progress_callback:
        progress_callback(0, total)

    if scan_limit < len(nodes):
        logger.info("Thumbnail ısındırma başladı: ilk %s öğeden %s medya (toplam %s öğe, performans için sınırlı).", scan_limit, total, len(nodes))
    else:
        logger.info("Thumbnail ısındırma başladı: %s medya dosyası hedefleniyor.", total)
    # Cache'de olanları say
    ready = 0
    uncached: list[dict] = []
    for n in candidates:
        if token.is_cancelled():
            if progress_callback:
                progress_callback(ready, total)
            return
        if thumb_manager.has_thumbnail(int(n["inode"])):
            ready += 1
        else:
            uncached.append(n)

    if progress_callback:
        progress_callback(ready, total)
    if ready >= warmup_count:
        return
    if token.is_cancelled():
        return

    # Limit how many we enqueue so we don't flood the executor
    to_submit = min(len(uncached), max(0, warmup_count - ready))
    if to_submit <= 0:
        return

    lock = threading.Lock()
    ready_ref = [ready]  # callback güncelleyebilsin

    def on_ready(_path):
        with lock:
            ready_ref[0] += 1
            r, t = ready_ref[0], total
        if progress_callback:
            progress_callback(r, t)

    for i, n in enumerate(uncached):
        if i >= to_submit:
            break
        if token.is_cancelled():
            break
        inode = int(n.get("inode"))
        name = n.get("name") or ""
        size = n.get("size")
        thumb_manager.request_thumbnail(
            inode,
            on_ready,
            name=name,
            is_dir=False,
            size=size,
        )
