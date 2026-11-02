"""Result card thumbnails: fetched in a worker pool, cached on disk, brightened when the server stores them dark, and handed back on the UI thread."""

import hashlib
import os
import tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from qgis.PyQt.QtCore import QObject, Qt, pyqtSignal
from qgis.PyQt.QtGui import QImage

from ..config import PLUGIN_VERSION
from ..net import METADATA_S


class _UiThreadInvoker(QObject):
    """Queues Python callbacks onto the Qt GUI thread."""

    invokeRequested = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.invokeRequested.connect(self._invoke, Qt.ConnectionType.QueuedConnection)

    def _invoke(self, callback):
        try:
            callback()
        except Exception as exc:
            from ..logger import warning

            warning(f"UI callback error: {exc}")


_ui_thread_invoker = _UiThreadInvoker()


def _invoke_on_ui_thread(callback):
    """Schedules a callable to run on the Qt main thread."""
    try:
        _ui_thread_invoker.invokeRequested.emit(callback)
    except RuntimeError:
        pass


# Thread pool for thumbnail downloads
_thumb_executor = ThreadPoolExecutor(max_workers=4)


def shutdown_thumb_executor():
    """Shut down the thumbnail thread pool. Call on plugin unload to avoid
    dangling daemon threads between QGIS plugin reloads."""
    global _thumb_executor
    _thumb_executor.shutdown(wait=False)
    _thumb_executor = ThreadPoolExecutor(max_workers=4)


def _get_thumb_cache_path(url):
    """Return a local cache file path for a thumbnail URL."""
    cache_dir = os.path.join(tempfile.gettempdir(), "bdc_loader_thumbs")
    os.makedirs(cache_dir, exist_ok=True)
    url_hash = hashlib.md5(url.encode("utf-8"), usedforsecurity=False).hexdigest()
    # "v2": entries are stored after _brighten_if_dark.
    return os.path.join(cache_dir, f"{url_hash}.v2.png")


# Mean luminance (0-255) of the imagery below which a thumbnail is stretched.
_DARK_THUMBNAIL = 50


def _brighten_if_dark(data):
    """PNG bytes of ``data`` with a 2-98 % stretch per channel when it is dark.

    The BDC's landsat-2 thumbnails are stored dark (mean luminance 17.7 of
    255 for LC09_L2SP_218074_20240831), so their cards looked black. Black
    fill around the scene is left black. Returns ``data`` unchanged when it
    is not dark or cannot be decoded. Safe in worker threads (QImage only).
    """
    try:
        import numpy as np
        from qgis.PyQt.QtCore import QBuffer, QByteArray, QIODevice

        image = QImage()
        if not image.loadFromData(data):
            return data
        image = image.convertToFormat(QImage.Format.Format_RGB32)
        ptr = image.constBits()
        ptr.setsize(image.sizeInBytes())
        pixels = np.frombuffer(ptr, np.uint8).reshape(image.height(), image.bytesPerLine() // 4, 4)
        pixels = pixels[:, : image.width(), :3].astype(np.float32)  # BGR
        content = pixels.sum(axis=2) > 0
        if not content.any():
            return data
        lum = pixels[content] @ np.array([0.114, 0.587, 0.299], np.float32)
        if float(lum.mean()) >= _DARK_THUMBNAIL:
            return data
        out = pixels.copy()
        for channel in range(3):
            values = pixels[..., channel][content]
            low, high = np.percentile(values, (2, 98))
            if high <= low:
                continue
            stretched = (pixels[..., channel] - low) * (255.0 / (high - low))
            out[..., channel] = np.where(content, np.clip(stretched, 1, 255), 0)
        rgb = np.ascontiguousarray(out[..., ::-1].astype(np.uint8))
        result = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format.Format_RGB888).copy()
        buffer = QByteArray()
        device = QBuffer(buffer)
        device.open(QIODevice.OpenModeFlag.WriteOnly)
        result.save(device, "PNG")
        device.close()
        return bytes(buffer)
    except Exception:
        return data


def _fetch_thumbnail_bytes(url):
    """Download thumbnail bytes from URL. Returns bytes or None."""
    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", f"BDC-Loader-Plugin/{PLUGIN_VERSION}")
        resp = urllib.request.urlopen(req, timeout=METADATA_S)
        data = _brighten_if_dark(resp.read())
        # Save to cache
        try:
            cache_path = _get_thumb_cache_path(url)
            with open(cache_path, "wb") as f:
                f.write(data)
        except Exception:
            pass
        return data
    except Exception:
        return None


class _ThumbJob:
    """A queued thumbnail or preview; ``wanted`` turns False when its card no longer needs it."""

    __slots__ = ("wanted",)

    def __init__(self):
        self.wanted = True
