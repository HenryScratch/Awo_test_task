from functools import lru_cache
from typing import Any
from time import monotonic
from hashlib import blake2b
from collections import OrderedDict, Counter
from collections.abc import Hashable
from threading import Lock
import redis
from typing import Any, Hashable

from router.config import REDIS_CONFIG
from .utils import encode_request_signature, decode_request_signature


class NotFoundInCache(Exception): ...

class BaseCache:

    def __init__(
        self,
        maxsize: int | None = None,
        ttl: float | None = None,
    ) -> None:
        self.maxsize = maxsize
        self.ttl = ttl
        self._lookups = Counter()
        self._hits = Counter()
        self._misses = Counter()
        self._lock = Lock()
        self._prepare()
        self._init_data_store()

    def _prepare(self) -> None: ...

    def _init_data_store(self) -> None: ...

    def _get(
        self,
        key: Hashable,
        default: Any = None,
        raise_not_found: bool = False,
        count: bool = True,
    ) -> Any:
        raise NotImplementedError

    def _set(
        self,
        key: Hashable,
        value: Any,
        ttl: float | None = None,
    ) -> None:
        raise NotImplementedError

    def _remove(self, key: Hashable) -> None:
        raise NotImplementedError

    def _purge(self) -> None:
        raise NotImplementedError

    def _cleanup(self) -> None:
        raise NotImplementedError

    def _clear_counters(self) -> None:
        self._lookups.clear()
        self._hits.clear()
        self._misses.clear()

    def _get_size(self) -> int:
        raise NotImplementedError

    def get(
        self,
        key: Hashable,
        default: Any = None,
        raise_not_found: bool = False,
        count: bool = True,
    ) -> Any:
        with self._lock:
            return self._get(key, default, raise_not_found, count)

    def set(
        self,
        key: Hashable,
        value: Any,
        ttl: float | None = None,
    ) -> None:
        with self._lock:
            return self._set(key, value, ttl)

    def remove(self, key: Hashable) -> None:
        with self._lock:
            return self._remove(key)

    def purge(self) -> None:
        with self._lock:
            self._clear_counters()
            return self._purge()

    def has_key(self, key: Hashable) -> bool:
        try:
            self.get(key, raise_not_found=True, count=False)
            return True
        except NotFoundInCache:
            return False

    def make_key(self, data: str | bytes) -> str:
        if isinstance(data, str):
            data = data.encode()
        hashed_key = blake2b(data, digest_size=8).hexdigest()
        return 'k:' + hashed_key

    def most_common_lookups(
        self,
        n: int | None = None,
    ) -> list[tuple[Hashable, int]]:
        with self._lock:
            return self._lookups.most_common(n)

    def most_common_hits(
        self,
        n: int | None = None,
    ) -> list[tuple[Hashable, int]]:
        with self._lock:
            return self._hits.most_common(n)

    def most_common_misses(
        self,
        n: int | None = None,
    ) -> list[tuple[Hashable, int]]:
        with self._lock:
            return self._misses.most_common(n)

    @property
    def size(self) -> int:
        with self._lock:
            return self._get_size()

    @property
    def capacity(self) -> int | None:
        if self.maxsize is not None:
            return max(0, self.maxsize - self.size)
        else:
            return None

    @property
    def lookups(self) -> int:
        with self._lock:
            return self._lookups.total()

    @property
    def hits(self) -> int:
        with self._lock:
            return self._hits.total()

    @property
    def misses(self) -> int:
        with self._lock:
            return self._misses.total()

    @property
    def hitrate(self) -> float:
        hits, misses = self.hits, self.misses
        if hits or misses:
            return hits / (misses + hits)
        else:
            return 0.0


class InMemoryCache(BaseCache):

    def _init_data_store(self) -> None:
        self._store = OrderedDict()

    def _get(
        self,
        key: Hashable,
        default: Any = None,
        raise_not_found: bool = False,
        count: bool = True,
    ) -> Any:
        if count:
            self._lookups[key] += 1
        if key in self._store:
            expiry_timestamp, value = self._store[key]
            if expiry_timestamp is not None and expiry_timestamp < monotonic():
                self._store.pop(key, None)
            else:
                self._store.move_to_end(key) # move on has_key?
                if count:
                    self._hits[key] += 1
                return value
        if count:
            self._misses[key] += 1
        if raise_not_found:
            raise NotFoundInCache(key)
        else:
            return default

    def _set(
        self,
        key: Hashable,
        value: Any,
        ttl: float | None = None,
    ) -> None:
        self._cleanup()
        ttl = self.ttl if ttl is None else ttl
        expiry_timestamp = None if ttl is None else monotonic() + ttl
        self._store[key] = (expiry_timestamp, value)
        if self.maxsize is not None:
            while self._get_size() > self.maxsize:
                self._store.popitem(0)

    def _remove(self, key: Hashable) -> None:
        self._store.pop(key, None)

    def _purge(self) -> None:
        self._store.clear()

    def _cleanup(self) -> None:
        now = monotonic()
        for key in list(self._store):
            expiry_timestamp = self._store[key][0]
            if expiry_timestamp is not None and expiry_timestamp < now:
                self._store.pop(key, None)

    def _get_size(self) -> int:
        # doesn't guarantee to be actual size
        return len(self._store)


class RedisCache(BaseCache):

    @lru_cache(maxsize=1)
    def get_cached_keys(self):
        return list(self._client.scan_iter(match='bind|*'))

    def _init_data_store(self) -> None:
        self._client = redis.StrictRedis(host=REDIS_CONFIG['host'], port=REDIS_CONFIG['port'], db=0)

    def _get(
        self,
        key: Hashable,
        default: Any = None,
        raise_not_found: bool = False,
        count: bool = True,
    ) -> Any:
        if count:
            self._lookups[key] += 1
        value = self._client.get(key)
        if value is not None:
            try:
                # Попробуем сначала декодировать как строку
                value = value.decode('utf-8')
            except UnicodeDecodeError:
                pass # У нас pickle
            if count:
                self._hits[key] += 1
            return value
        if count:
            self._misses[key] += 1
        if raise_not_found:
            raise NotFoundInCache(key)
        else:
            return default

    def _set(
        self,
        key: Hashable,
        value: Any,
        ttl: float | None = None,
    ) -> None:
        ttl = self.ttl if ttl is None else ttl
        if ttl is not None:
            self._client.setex(key, int(ttl), value)
        else:
            self._client.set(key, value)

    def _remove(self, key: Hashable) -> None:
        self._client.delete(key)

    def _purge(self) -> None:
        self._client.flushdb()

    def _get_size(self) -> int:
        return self._client.dbsize()

    def count_keys(self, value: Any) -> int:
        keys = self.get_cached_keys()
        if not keys:
            return 0

        values = self._client.mget(keys)

        return sum(1 for v in values if v == value)


class HTTPCache(RedisCache):

    def _prepare(self) -> None:
        self._req_signatures = {}

    def _purge(self) -> None:
        self._req_signatures.clear()
        super()._purge()

    def make_request_key(
        self,
        method: str,
        path: str,
        headers: dict,
        params: str,
        body: bytes,
    ) -> str:
        signature = encode_request_signature(
            method, path, headers, params, body)
        key = self.make_key(signature)
        self._req_signatures[key] = signature
        return key

    def most_common_requests(
        self,
        n: int | None = None,
    ) -> list[dict]:
        return [
            {
                'key': key,
                'lookups': val,
                **decode_request_signature(self._req_signatures[key])
            }
            for key, val in self.most_common_lookups(n)
            if key in self._req_signatures
        ]
