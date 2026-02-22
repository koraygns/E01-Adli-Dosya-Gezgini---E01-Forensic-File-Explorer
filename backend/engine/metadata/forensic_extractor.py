"""
EXIF, GPS, cihaz bilgisi (resim/video). Video için ExifTool gerekir.
"""
import io
import os
import fractions
import json
import shutil
import subprocess
import tempfile
import urllib.request
import urllib.error
from typing import Any

try:
    import reverse_geocode
    HAS_REVERSE_GEOCODE = True
except ImportError:
    HAS_REVERSE_GEOCODE = False

# Pillow opsiyonel
try:
    from PIL import Image
    from PIL.ExifTags import TAGS, GPSTAGS
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# EXIF okuma limiti
EXIF_READ_LIMIT = 256 * 1024
# Video metadata (moov atom) genelde dosya başında; bazen sonda
VIDEO_READ_LIMIT = 4 * 1024 * 1024  # 4 MB

EXIF_EXTENSIONS = {".jpg", ".jpeg", ".jpe", ".png", ".tiff", ".tif", ".webp", ".heic", ".heif", ".dng"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".3gp", ".avi", ".mkv", ".webm", ".mpg", ".mpeg"}


def _get_extension(name: str) -> str:
    if not name or "." not in name:
        return ""
    return "." + name.rsplit(".", 1)[-1].lower()


def _gps_to_decimal(dms: tuple, ref: str) -> float | None:
    """GPS dms -> ondalık derece."""
    if not dms or len(dms) < 3:
        return None
    try:
        d = float(fractions.Fraction(str(dms[0])) if isinstance(dms[0], fractions.Fraction) else float(dms[0]))
        m = float(fractions.Fraction(str(dms[1])) if isinstance(dms[1], fractions.Fraction) else float(dms[1]))
        s = float(fractions.Fraction(str(dms[2])) if isinstance(dms[2], fractions.Fraction) else float(dms[2]))
        dec = d + m / 60.0 + s / 3600.0
        if ref and ref.upper() in ("S", "W"):
            dec = -dec
        return round(dec, 6)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _reverse_geocode_region(lat: float, lon: float) -> str:
    """Koordinatlardan bölge adı (offline veya Nominatim)."""
    # 1. Offline: reverse_geocode (pip install reverse-geocode)
    if HAS_REVERSE_GEOCODE:
        try:
            result = reverse_geocode.search([(lat, lon)])
            if result:
                r = result[0]
                parts = []
                if r.get("city"):
                    parts.append(r["city"])
                if r.get("state"):
                    parts.append(r["state"])
                if r.get("country"):
                    parts.append(r["country"])
                if parts:
                    return ", ".join(parts)
        except Exception:
            pass
    # Online: Nominatim
    try:
        url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json"
        req = urllib.request.Request(url, headers={"User-Agent": "ForensicMetadata/1.0"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())
        addr = data.get("address") or {}
        parts = []
        for k in ("city", "town", "village", "municipality", "state", "country"):
            v = addr.get(k)
            if v and v not in parts:
                parts.append(v)
        return ", ".join(parts) if parts else ""
    except (urllib.error.URLError, OSError, json.JSONDecodeError, KeyError):
        return ""


def _format_gps(gps_ifd: dict) -> tuple[str, str]:
    """Format GPS: (koordinatlar, bölge_adi)."""
    lat = gps_ifd.get("GPSLatitude")
    lat_ref = gps_ifd.get("GPSLatitudeRef", "N")
    lon = gps_ifd.get("GPSLongitude")
    lon_ref = gps_ifd.get("GPSLongitudeRef", "E")
    lat_dec = _gps_to_decimal(lat, lat_ref) if lat else None
    lon_dec = _gps_to_decimal(lon, lon_ref) if lon else None
    if lat_dec is None or lon_dec is None:
        return "", ""
    coords = f"{lat_dec}, {lon_dec}"
    region = _reverse_geocode_region(lat_dec, lon_dec)
    return coords, region


def _extract_video_metadata(data: bytes, name: str) -> dict[str, Any]:
    """Videodan metadata (ExifTool)."""
    result = {
        "gps": "",
        "gps_region": "",
        "make": "",
        "model": "",
        "datetime_original": "",
        "software": "",
        "image_width": "",
        "image_height": "",
    }
    exiftool = shutil.which("exiftool")
    if not exiftool or not data:
        return result
    ext = _get_extension(name)
    if ext not in VIDEO_EXTENSIONS:
        return result
    try:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
            f.write(data)
            tmp = f.name
        try:
            out = subprocess.run(
                [exiftool, "-j", "-G1", "-a", tmp],
                capture_output=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
            if out.returncode != 0 or not out.stdout:
                return result
            arr = json.loads(out.stdout.decode("utf-8", errors="replace"))
            if not arr:
                return result
            d = arr[0]
            # GPS: çeşitli tag isimleri
            lat = d.get("QuickTime:GPSLatitude") or d.get("Composite:GPSLatitude") or d.get("GPS:GPSLatitude")
            lon = d.get("QuickTime:GPSLongitude") or d.get("Composite:GPSLongitude") or d.get("GPS:GPSLongitude")
            pos = d.get("Composite:GPSPosition")
            if lat is not None and lon is not None:
                try:
                    lat_f, lon_f = float(lat), float(lon)
                    result["gps"] = f"{lat_f}, {lon_f}"
                    result["gps_region"] = _reverse_geocode_region(lat_f, lon_f)
                except (TypeError, ValueError):
                    pass
            elif pos and isinstance(pos, str):
                result["gps"] = pos
                try:
                    parts = pos.replace(" ", "").split(",")
                    if len(parts) >= 2:
                        lat_f, lon_f = float(parts[0]), float(parts[1])
                        result["gps_region"] = _reverse_geocode_region(lat_f, lon_f)
                except (TypeError, ValueError):
                    pass
            result["make"] = _s(d.get("QuickTime:Make") or d.get("Make"))
            result["model"] = _s(d.get("QuickTime:Model") or d.get("Model"))
            result["datetime_original"] = _s(
                d.get("QuickTime:CreateDate") or d.get("CreateDate") or d.get("QuickTime:MediaCreateDate")
            )
            result["software"] = _s(d.get("QuickTime:Software") or d.get("Software"))
            w = d.get("QuickTime:ImageWidth") or d.get("Track1:ImageWidth") or d.get("Video:ImageWidth")
            h = d.get("QuickTime:ImageHeight") or d.get("Track1:ImageHeight") or d.get("Video:ImageHeight")
            if w is not None and h is not None:
                result["image_width"] = str(w)
                result["image_height"] = str(h)
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    except Exception:
        pass
    return result


def extract_forensic_metadata(data: bytes, name: str) -> dict[str, Any]:
    """
    Extract forensic metadata (EXIF, GPS, device) from file bytes.
    Returns dict with keys: gps, make, model, datetime_original, software, etc.
    Empty string for missing values; no external network calls.
    """
    result = {
        "gps": "",
        "gps_region": "",
        "make": "",
        "model": "",
        "datetime_original": "",
        "datetime_digitized": "",
        "software": "",
        "orientation": "",
        "x_resolution": "",
        "y_resolution": "",
        "color_space": "",
        "exposure_time": "",
        "f_number": "",
        "iso": "",
        "flash": "",
        "focal_length": "",
        "lens_make": "",
        "lens_model": "",
        "image_width": "",
        "image_height": "",
        "serial_number": "",
    }
    if not data:
        return result
    ext = _get_extension(name)
    if ext in VIDEO_EXTENSIONS:
        return _extract_video_metadata(data, name)
    if not HAS_PIL or ext not in EXIF_EXTENSIONS:
        return result
    try:
        img = Image.open(io.BytesIO(data[:EXIF_READ_LIMIT]))
        exif = img.getexif()
        if not exif:
            return result
        # Build tag name -> value map
        tag_map = {}
        for tag_id, val in exif.items():
            name_tag = TAGS.get(tag_id, tag_id)
            if isinstance(val, bytes):
                try:
                    val = val.decode("utf-8", errors="replace").strip("\x00")
                except Exception:
                    val = str(val)[:100]
            tag_map[name_tag] = val
        # GPS (IFD 34853)
        gps_ifd = {}
        if hasattr(exif, "get_ifd"):
            try:
                raw = exif.get_ifd(34853)
                if isinstance(raw, dict):
                    gps_ifd = {GPSTAGS.get(k, k): v for k, v in raw.items()}
            except Exception:
                pass
        if gps_ifd:
            coords, region = _format_gps(gps_ifd)
            if coords:
                result["gps"] = coords
                result["gps_region"] = region
        # Cihaz ve tarih
        result["make"] = _s(tag_map.get("Make"))
        result["model"] = _s(tag_map.get("Model"))
        result["datetime_original"] = _s(tag_map.get("DateTimeOriginal"))
        result["datetime_digitized"] = _s(tag_map.get("DateTimeDigitized"))
        result["software"] = _s(tag_map.get("Software"))
        result["orientation"] = _s(tag_map.get("Orientation"))
        result["exposure_time"] = _s(tag_map.get("ExposureTime"))
        result["f_number"] = _s(tag_map.get("FNumber"))
        result["iso"] = _s(tag_map.get("ISOSpeedRatings") or tag_map.get("PhotographicSensitivity"))
        result["flash"] = _s(tag_map.get("Flash"))
        result["focal_length"] = _s(tag_map.get("FocalLength"))
        result["lens_make"] = _s(tag_map.get("LensMake"))
        result["lens_model"] = _s(tag_map.get("LensModel"))
        result["image_width"] = _s(tag_map.get("ExifImageWidth") or img.width)
        result["image_height"] = _s(tag_map.get("ExifImageHeight") or img.height)
        result["serial_number"] = _s(tag_map.get("BodySerialNumber") or tag_map.get("LensSerialNumber"))
        if tag_map.get("XResolution"):
            result["x_resolution"] = str(tag_map["XResolution"])
        if tag_map.get("YResolution"):
            result["y_resolution"] = str(tag_map["YResolution"])
        if tag_map.get("ColorSpace") is not None:
            result["color_space"] = str(tag_map["ColorSpace"])
    except Exception:
        pass
    return result


def _s(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip() or ""
