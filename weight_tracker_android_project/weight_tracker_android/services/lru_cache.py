"""Small standard-library LRU cache with a strict maximum item count."""
from collections import OrderedDict


class BoundedLRU:
    """An insertion-ordered cache that evicts the least recently used item."""

    def __init__(self, capacity=5):
        capacity = int(capacity)
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self.capacity = capacity
        self._items = OrderedDict()

    def get(self, key, default=None):
        if key not in self._items:
            return default
        self._items.move_to_end(key)
        return self._items[key]

    def set(self, key, value):
        self._items[key] = value
        self._items.move_to_end(key)
        while len(self._items) > self.capacity:
            self._items.popitem(last=False)
        return value

    def pop(self, key, default=None):
        return self._items.pop(key, default)

    def clear(self):
        self._items.clear()

    def __contains__(self, key):
        return key in self._items

    def __len__(self):
        return len(self._items)

    def items(self):
        return self._items.items()
