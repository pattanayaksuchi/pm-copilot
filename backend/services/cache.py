# backend/services/cache.py
import time

class TTLCache:
    def __init__(self, ttl_seconds: int = 120):
        self.ttl = ttl_seconds
        self._store = {}  # key -> (expires_at, value)

    def get(self, key):
        v = self._store.get(key)
        if not v:
            return None
        expires, val = v
        if time.time() > expires:
            self._store.pop(key, None)
            return None
        return val

    def set(self, key, value):
        self._store[key] = (time.time() + self.ttl, value)

themes_cache = TTLCache(ttl_seconds=120)  # cache themes for 2 minutes
