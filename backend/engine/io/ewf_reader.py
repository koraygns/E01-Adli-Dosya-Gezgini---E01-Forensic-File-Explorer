import os
import pyewf
import pytsk3


class EWFImgInfo(pytsk3.Img_Info):
    def __init__(self, ewf_handle):
        self._ewf_handle = ewf_handle
        super().__init__(url="", type=pytsk3.TSK_IMG_TYPE_EXTERNAL)

    def close(self):
        self._ewf_handle.close()

    def read(self, offset, size):
        self._ewf_handle.seek(offset)
        return self._ewf_handle.read(size)

    def get_size(self):
        return self._ewf_handle.get_media_size()


def open_ewf_image(e01_path: str):
    """E01 aç (E02, E03... otomatik bulunur)."""
    e01_path = os.path.normpath(os.path.abspath(e01_path))
    if not os.path.isfile(e01_path):
        raise FileNotFoundError(f"E01 bulunamadı: {e01_path}")

    filenames = pyewf.glob(e01_path)
    if not filenames:
        raise FileNotFoundError(f"E01 segment dosyası bulunamadı: {e01_path}")

    try:
        ewf_handle = pyewf.handle()
        ewf_handle.open(filenames)
    except (IOError, OSError, RuntimeError) as e:
        err = str(e).lower()
        if "segment" in err or "missing" in err or "offset" in err or "chunk" in err:
            raise RuntimeError(
                "E01 parça dosyaları eksik. Tüm segmentlerin (E01, E02, E03, ...) seçtiğiniz E01 ile aynı klasörde olduğundan emin olun."
            ) from e
        raise

    img_info = EWFImgInfo(ewf_handle)
    return img_info
