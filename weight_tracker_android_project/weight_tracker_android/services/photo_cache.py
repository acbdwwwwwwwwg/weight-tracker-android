"""Bounded asynchronous image cache used by the body-photo browser.

Only Kivy's Loader performs decoding. UI widgets receive texture changes from
Clock callbacks; callers may keep their current texture while a new one loads.
"""
from kivy.clock import Clock
from kivy.loader import Loader

from services.lru_cache import BoundedLRU


def proxy_texture(proxy):
    """Return the decoded texture, excluding Loader's temporary placeholder."""
    if proxy is None or not getattr(proxy, "loaded", False):
        return None
    image = getattr(proxy, "image", None)
    texture = getattr(image, "texture", None) if image is not None else None
    return texture or getattr(proxy, "texture", None)


class PhotoImageCache:
    """LRU cache of at most ``capacity`` Kivy Loader proxy images."""

    def __init__(self, capacity=5):
        self._entries = BoundedLRU(capacity)

    @property
    def capacity(self):
        return self._entries.capacity

    def __len__(self):
        return len(self._entries)

    def _entry(self, path):
        key = str(path)
        entry = self._entries.get(key)
        if entry is not None:
            return key, entry

        proxy = Loader.image(key, nocache=True)
        entry = {"proxy": proxy, "listeners": [], "bound": False, "failed": False}
        self._entries.set(key, entry)

        def loaded(image, *_args, _entry=entry):
            _entry["failed"] = False
            listeners, _entry["listeners"] = _entry["listeners"], []
            for success, _error in listeners:
                if success:
                    try:
                        success(image)
                    except Exception:
                        # One stale widget callback must not prevent other users
                        # of the same loaded resource from being notified.
                        pass

        def failed(image, error=None, _entry=entry):
            _entry["failed"] = True
            listeners, _entry["listeners"] = _entry["listeners"], []
            for _success, on_error in listeners:
                if on_error:
                    try:
                        on_error(image, error)
                    except Exception:
                        pass

        proxy.bind(on_load=loaded)
        proxy.bind(on_error=failed)
        entry["bound"] = True
        return key, entry

    def request(self, path, on_load=None, on_error=None):
        """Return the cached proxy and asynchronously invoke the appropriate callback."""
        key, entry = self._entry(path)
        proxy = entry["proxy"]
        if getattr(proxy, "loaded", False) and proxy_texture(proxy) is not None:
            if on_load:
                Clock.schedule_once(lambda _dt, cb=on_load, img=proxy: cb(img), 0)
        elif entry.get("failed"):
            if on_error:
                Clock.schedule_once(
                    lambda _dt, cb=on_error, img=proxy: cb(img, RuntimeError("图片加载失败")), 0
                )
        elif on_load or on_error:
            entry["listeners"].append((on_load, on_error))
        return proxy

    def prefetch(self, path):
        """Start loading a nearby image without attaching a UI callback."""
        if path:
            return self._entry(path)[1]["proxy"]
        return None

    def invalidate(self, path):
        if path:
            self._entries.pop(str(path), None)

    def clear(self):
        self._entries.clear()
