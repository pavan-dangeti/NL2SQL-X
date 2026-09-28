import threading
import time
from collections import OrderedDict, deque
from collections.abc import Hashable
from typing import Any


class TTLCache:
    def __init__(self, maxsize: int, ttl_s: float) -> None:
        self.maxsize, self.ttl = maxsize, ttl_s
        self._data: OrderedDict[Hashable, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: Hashable) -> Any | None:
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            if item[0] < time.monotonic():
                del self._data[key]
                return None
            self._data.move_to_end(key)
            return item[1]

    def set(self, key: Hashable, value: Any) -> None:
        if self.maxsize <= 0 or self.ttl <= 0:
            return
        with self._lock:
            self._data[key] = (time.monotonic() + self.ttl, value)
            self._data.move_to_end(key)
            while len(self._data) > self.maxsize:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


class RateLimiter:
    """Sliding one-minute window per key."""

    def __init__(self, per_minute: int, max_keys: int = 50_000) -> None:
        self.per_minute = per_minute
        self.max_keys = max_keys
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def hit(self, key: str) -> float | None:
        """Records a hit; returns seconds to wait when over the limit."""
        now = time.monotonic()
        with self._lock:
            window = self._hits.get(key)
            if window is None:
                window = self._hits[key] = deque()
                if len(self._hits) > self.max_keys:
                    self._hits.popitem(last=False)
            self._hits.move_to_end(key)
            while window and window[0] <= now - 60:
                window.popleft()
            if len(window) >= self.per_minute:
                return round(60 - (now - window[0]), 1)
            window.append(now)
            return None
