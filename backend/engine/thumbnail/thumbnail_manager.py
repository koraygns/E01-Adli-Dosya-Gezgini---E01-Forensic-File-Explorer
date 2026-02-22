"""
Thumbnail motoru: async üretim, disk cache.
"""
import io
import logging
import os
import subprocess
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from backend.engine.io.ffmpeg_finder import find_ffmpeg

logger = logging.getLogger(__name__)

# ffmpeg/Pillow uyarısı bir kez
_ffmpeg_warned = False
_pillow_warned = False

# Resim/video uzantıları
THUMB_IMAGE_EXT = {
    ".jpg", ".jpeg", ".jpe", ".jfif",
    ".png", ".apng",
    ".bmp", ".dib",
    ".gif",
    ".webp",
    ".tiff", ".tif",
    ".ico", ".cur",
    ".ppm", ".pgm", ".pbm", ".pnm",
    ".pcx", ".tga", ".targa", ".icb", ".vda", ".vst",
    ".xbm", ".xpm",
    ".jp2", ".j2k", ".jpf", ".jpx",
    ".heic", ".heif", ".avci", ".avcs",
}
THUMB_VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
THUMB_EXT_ALL = THUMB_IMAGE_EXT | THUMB_VIDEO_EXT

MAX_READ_IMAGE = 10 * 1024 * 1024   # 10 MB
MAX_READ_VIDEO = 50 * 1024 * 1024   # 50 MB for first frame
THUMB_SIZE = (256, 256)
VIDEO_FRAME_TIME = 1.0  # saniye
# Max eşzamanlı thumbnail işi
MAX_CONCURRENT_THUMB_JOBS = 200


def _extension(name: str) -> str:
    if not name or "." not in name:
        return ""
    return "." + name.rsplit(".", 1)[-1].lower()


def _should_thumbnail(name: str, is_dir: bool) -> bool:
    if is_dir:
        return False
    return _extension(name) in THUMB_EXT_ALL


def _apply_exif_orientation(img):
    """EXIF yönlendirme uygula."""
    try:
        from PIL import Image
        exif = getattr(img, "getexif", None)
        if exif is None:
            return img
        exif_data = exif()
        if not exif_data:
            return img
        orientation = exif_data.get(0x0112)
        if not orientation or orientation == 1:
            return img
        if orientation == 2:
            img = img.transpose(Image.FLIP_LEFT_RIGHT)
        elif orientation == 3:
            img = img.transpose(Image.ROTATE_180)
        elif orientation == 4:
            img = img.transpose(Image.FLIP_TOP_BOTTOM)
        elif orientation == 5:
            img = img.transpose(Image.FLIP_LEFT_RIGHT).transpose(Image.ROTATE_90)
        elif orientation == 6:
            img = img.transpose(Image.ROTATE_270)
        elif orientation == 7:
            img = img.transpose(Image.FLIP_LEFT_RIGHT).transpose(Image.ROTATE_270)
        elif orientation == 8:
            img = img.transpose(Image.ROTATE_90)
        return img
    except Exception:
        return img


def _generate_image_thumb(data: bytes, out_path: str, size: tuple = THUMB_SIZE) -> bool:
    """Pillow ile resim thumbnail."""
    global _pillow_warned
    try:
        from PIL import Image
    except ImportError:
        if not _pillow_warned:
            _pillow_warned = True
            logger.warning("Pillow yüklü değil; resim thumbnail'ları devre dışı. pip install Pillow")
        return False
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        img = _apply_exif_orientation(img)
        if img.mode in ("RGBA", "P", "LA"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            if img.mode in ("RGBA", "LA"):
                background.paste(img, mask=img.split()[-1])
                img = background
            else:
                img = img.convert("RGB")
        elif img.mode != "RGB":
            img = img.convert("RGB")
        resample = getattr(Image, "Resampling", getattr(Image, "LANCZOS", None)) or Image.LANCZOS
        if isinstance(resample, type):
            resample = getattr(resample, "LANCZOS", Image.LANCZOS)
        img.thumbnail(size, resample)
        img.save(out_path, "JPEG", quality=85, optimize=True)
        return True
    except Exception as e:
        # Bozuk/eksik/yanlış uzantılı dosyalar sık; log dosyasını şişirmemek için DEBUG
        logger.debug("Resim thumbnail oluşturulamadı: %s", e)
        return False


def _video_temp_suffix(ext: str) -> str:
    if ext in (".mp4", ".mov", ".avi", ".mkv", ".webm"):
        return ext
    return ".mp4"


def _run_ffmpeg_frame(cmd: list, tmp: str, out_path: str, max_s: int, timeout: int, creationflags: int) -> bool:
    """ffmpeg çalıştır."""
    r = subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=creationflags)
    return r.returncode == 0 and os.path.isfile(out_path) and os.path.getsize(out_path) > 0


def _generate_video_first_frame(data: bytes, out_path: str, size: tuple = THUMB_SIZE, ext: str = ".mp4") -> bool:
    """Videodan ilk kare (ffmpeg)."""
    ffmpeg_exe = find_ffmpeg()
    if not ffmpeg_exe:
        global _ffmpeg_warned
        if not _ffmpeg_warned:
            _ffmpeg_warned = True
            logger.warning(
                "ffmpeg bulunamadı; video thumbnail devre dışı. "
                "PATH'e ekleyin veya third_party/ffmpeg/bin/ içine koyun."
            )
        return False
    ext = _video_temp_suffix(ext)
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    timeout = 20 if ext == ".mov" else 15
    max_s = size[0]
    vf = f"scale='min({max_s},iw)':'min({max_s},ih)':force_original_aspect_ratio=decrease"
    try:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
            f.write(data)
            tmp = f.name
        try:
            # 1) Hızlı seek: -ss önce (çoğu MP4/MKV için). Zamanları dene: 0, 0.5, 1 (MOV'da 0 genelde güvenilir)
            for t in ([0.0, 0.5, VIDEO_FRAME_TIME] if ext == ".mov" else [VIDEO_FRAME_TIME, 0.0]):
                cmd = [
                    ffmpeg_exe, "-y", "-ss", str(t), "-i", tmp,
                    "-vframes", "1", "-vf", vf, "-f", "image2", out_path,
                ]
                if _run_ffmpeg_frame(cmd, tmp, out_path, max_s, timeout, creationflags):
                    return True
            # 2) Kesin seek: -i sonra -ss (değişken FPS / MOV için daha uyumlu, yavaş)
            cmd = [
                ffmpeg_exe, "-y", "-i", tmp, "-ss", "0.5",
                "-vframes", "1", "-vf", vf, "-f", "image2", out_path,
            ]
            if _run_ffmpeg_frame(cmd, tmp, out_path, max_s, timeout, creationflags):
                return True
            # 3) İlk kare, scale ile (keyframe sorunlu dosyalar)
            cmd = [
                ffmpeg_exe, "-y", "-i", tmp, "-vframes", "1",
                "-vf", vf, "-f", "image2", out_path,
            ]
            if _run_ffmpeg_frame(cmd, tmp, out_path, max_s, timeout, creationflags):
                return True
            return False
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    except subprocess.TimeoutExpired:
        logger.debug("Video thumbnail zaman aşımı: %s", ext)
        return False
    except Exception as e:
        logger.debug("Video önizlemesi oluşturulamadı: %s", e)
        return False


class ThumbnailManager:
    """
    Async thumbnail generation with disk cache.
    Call request_thumbnail(inode, callback); callback(path) is invoked when ready (main-thread safe by caller).
    """

    def __init__(self, engine_session, thumbnail_dir: str):
        self.session = engine_session
        self.thumb_dir = os.path.abspath(thumbnail_dir)
        self.executor = ThreadPoolExecutor(max_workers=4)
        self._in_progress: set = set()
        self._lock = threading.Lock()
        self._job_semaphore = threading.Semaphore(MAX_CONCURRENT_THUMB_JOBS)

        os.makedirs(self.thumb_dir, exist_ok=True)

    def get_thumbnail_path(self, inode: int) -> str:
        return os.path.join(self.thumb_dir, f"thumb_{inode}.jpg")

    def has_thumbnail(self, inode: int) -> bool:
        return os.path.isfile(self.get_thumbnail_path(inode))

    def should_thumbnail(self, inode: int, name: str, is_dir: bool) -> bool:
        return _should_thumbnail(name or "", is_dir)

    def request_thumbnail(
        self,
        inode: int,
        callback: Callable[[str | None], None],
        name: str | None = None,
        is_dir: bool = False,
        size: int | None = None,
    ):
        """
        If cached: call callback(path) immediately.
        Else if not in progress: submit background task; when done call callback(path) or callback(None).
        Sadece NORMAL_MEDIA kuyruğa girmeli: size=0 veya desteklenmeyen format callback(None) ile atlanır.
        """
        if size is not None and int(size) == 0:
            callback(None)
            return
        path = self.get_thumbnail_path(inode)
        if self.has_thumbnail(inode):
            callback(path)
            return
        if not self.should_thumbnail(inode, name or "", is_dir):
            callback(None)
            return

        with self._lock:
            if inode in self._in_progress:
                return
            self._in_progress.add(inode)

        if not self._job_semaphore.acquire(blocking=False):
            with self._lock:
                self._in_progress.discard(inode)
            callback(None)
            return

        def done():
            try:
                thumb_path = self._generate_thumbnail(inode, name)
                callback(thumb_path)
            except Exception:
                callback(None)
            finally:
                self._job_semaphore.release()
                with self._lock:
                    self._in_progress.discard(inode)

        self.executor.submit(done)

    def _generate_thumbnail(self, inode: int, name: str | None) -> str | None:
        """Thumbnail üret, cache'e kaydet."""
        path = self.get_thumbnail_path(inode)
        if os.path.isfile(path):
            return path

        node = None
        if getattr(self.session, "snapshot", None):
            node = self.session.snapshot.get_node(inode)
        if not node:
            logger.info("Thumbnail atlandı (inode %s): snapshot'ta node yok", inode)
            return None
        if node.get("is_dir"):
            return None
        if (node.get("size") or 0) == 0:
            return None

        ext = _extension(node.get("name") or "")
        if ext not in THUMB_EXT_ALL:
            return None

        max_read = MAX_READ_VIDEO if ext in THUMB_VIDEO_EXT else MAX_READ_IMAGE
        data = self.session.read_file_content(inode, offset=0, max_size=max_read)
        if not data or len(data) == 0:
            logger.info("Thumbnail atlandı (inode %s, %s): dosya okunamadı veya boş", inode, name or "")
            return None

        ok = False
        if ext in THUMB_IMAGE_EXT:
            ok = _generate_image_thumb(data, path)
        elif ext in THUMB_VIDEO_EXT:
            ok = _generate_video_first_frame(data, path, ext=ext)

        if ok and os.path.isfile(path):
            return path
        return None

    def shutdown(self):
        self.executor.shutdown(wait=False)
