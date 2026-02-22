"""
Image thumbnail generation: Pillow-based resize with EXIF orientation fix.
Read-only access to evidence; never modifies source files.
"""
import logging
import os

from .cache import MAX_THUMB_SIZE

logger = logging.getLogger(__name__)

# Tüm yaygın resim formatları (Pillow ile açılabilen; lowercase)
IMAGE_EXTENSIONS = frozenset({
    ".jpg", ".jpeg", ".jpe", ".jfif",   # JPEG
    ".png", ".apng",                     # PNG
    ".bmp", ".dib",                      # BMP
    ".gif",                             # GIF
    ".webp",                            # WebP
    ".tiff", ".tif",                    # TIFF
    ".ico", ".cur",                      # ICO / Cursor
    ".ppm", ".pgm", ".pbm", ".pnm",     # PNM
    ".pcx",                             # PCX
    ".tga", ".targa", ".icb", ".vda", ".vst",  # TGA
    ".xbm", ".xpm",                     # XBM / XPM
    ".jp2", ".j2k", ".jpf", ".jpx",     # JPEG 2000
    ".heic", ".heif", ".avci", ".avcs",  # HEIC/HEIF (Pillow 10+ veya pillow-heif)
})


def _get_extension(path: str) -> str:
    if not path or "." not in os.path.basename(path):
        return ""
    return "." + path.rsplit(".", 1)[-1].lower()


def is_supported(path: str) -> bool:
    """Return True if the path has a supported image extension."""
    return _get_extension(path) in IMAGE_EXTENSIONS


def _apply_exif_orientation(img):
    """Apply EXIF orientation so thumbnail is upright. Pillow 6+ has getexif()."""
    try:
        from PIL import Image
        exif = getattr(img, "getexif", None)
        if exif is None:
            return img
        exif_data = exif()
        if not exif_data:
            return img
        orientation = exif_data.get(0x0112)  # EXIF Orientation tag
        if not orientation or orientation == 1:
            return img
        # Rotate/flip according to EXIF
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
    except Exception as e:
        logger.debug("EXIF orientation skip: %s", e)
        return img


def generate(
    source_path: str,
    out_path: str,
    max_size: int = MAX_THUMB_SIZE,
) -> bool:
    """
    Generate a thumbnail from an image file. Reads source_path only; never writes to it.
    Saves JPEG to out_path. Returns True on success, False on skip/failure.
    """
    if not os.path.isfile(source_path):
        logger.debug("Not a file: %s", source_path)
        return False
    if not is_supported(source_path):
        return False
    try:
        from PIL import Image
    except ImportError:
        logger.warning("Pillow not installed; image thumbnails disabled")
        return False
    try:
        with Image.open(source_path) as img:
            img.load()
            img = _apply_exif_orientation(img)
            # Convert to RGB if necessary for JPEG
            if img.mode in ("RGBA", "P", "LA"):
                background = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode == "P":
                    img = img.convert("RGBA")
                if img.mode in ("RGBA", "LA"):
                    background.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
                    img = background
                else:
                    img = img.convert("RGB")
            elif img.mode != "RGB":
                img = img.convert("RGB")
            resample = getattr(Image, "Resampling", getattr(Image, "LANCZOS", None)) or Image.LANCZOS
            if isinstance(resample, type):
                resample = getattr(resample, "LANCZOS", Image.LANCZOS)
            img.thumbnail((max_size, max_size), resample)
            img.save(out_path, "JPEG", quality=85, optimize=True)
        return os.path.isfile(out_path) and os.path.getsize(out_path) > 0
    except Exception as e:
        logger.debug("Thumbnail failed for %s: %s", source_path, e)
        return False
