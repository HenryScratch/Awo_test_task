__all__ = [
    'get_uuid',
    'get_env_var',
    'encode_request_signature',
    'decode_request_signature',
    'memoize',
]

import os
from uuid import uuid4
from time import monotonic
from threading import RLock
from collections import defaultdict
from functools import wraps, _make_key


def get_uuid() -> str:
    return uuid4().hex[:8]


def get_env_var(name: str, raise_not_found: bool = True) -> str | None:
    if name in os.environ:
        return os.environ[name]
    elif raise_not_found:
        raise LookupError(f'Environment variable {name!r} is not set')
    else:
        return None


def encode_request_signature(
    method: str,
    path: str,
    headers: dict,
    params: str,
    body: bytes,
) -> bytes:
    return b'\0'.join([
        method.encode(),
        path.encode(),
        b'\1'.join(
            f'{k}:{v}'.encode()
            for k, v in sorted(headers.items())
        ),
        params.encode(),
        body,
    ])


def decode_request_signature(data: bytes) -> dict:
    method, path, headers, params, body = data.split(b'\0')
    return {
        'method': method.decode(),
        'path': path.decode(),
        'headers': dict(
            _.decode().split(':', 1)
            for _ in headers.split(b'\1')
        ) if headers else {},
        'params': params.decode(),
        'body': body,
    }


def memoize(maxsize=None, ttl=None):
    if ttl is not None:
        if not isinstance(ttl, (int, float)):
            raise TypeError('ttl must be int or float')
        elif ttl <= 0:
            raise ValueError('ttl must be > 0')

    if isinstance(maxsize, int):
        if maxsize <= 0:
            raise ValueError('maxsize must be > 0')
    elif callable(maxsize):
        func, maxsize = maxsize, None
        return _memoize_wrapper(func, maxsize, ttl)
    elif maxsize is not None:
        raise TypeError('Expected first argument to be int, callable or None')

    def decorator(func):
        return _memoize_wrapper(func, maxsize, ttl)
    return decorator


def _memoize_wrapper(func, maxsize, ttl):
    get_time = monotonic
    make_key = _make_key
    key_locks = defaultdict(RLock)
    lock = RLock()
    store = {}
    notfound = object()
    hits = misses = 0

    @wraps(func)
    def wrapper(*args, **kwds):
        nonlocal hits, misses
        key = make_key(args, kwds, False)
        result = store.get(key, notfound)
        if result is not notfound:
            if ttl:
                result, expiry_timestamp = result
                if expiry_timestamp < get_time():
                    with lock:
                        store.pop(key, None)
                else:
                    hits += 1
                    return result
            else:
                hits += 1
                return result
        with key_locks[key]:
            result = store.get(key, notfound)
            if result is not notfound: # expired?
                hits += 1
                return result[0] if ttl else result
            misses += 1
            result = func(*args, **kwds)
            with lock:
                while maxsize and len(store) >= maxsize:
                    oldest_key = next(iter(store))
                    del store[oldest_key]
                    del key_locks[oldest_key]
                store[key] = (result, get_time() + ttl) if ttl else result
            return result

    def info():
        with lock:
            return {
                'hits': hits,
                'misses': misses,
                'maxsize': maxsize,
            }

    def clear():
        nonlocal hits, misses
        with lock:
            store.clear()
            key_locks.clear() # ?
            hits = misses = 0

    wrapper.info = info
    wrapper.clear = clear
    wrapper._store = store

    return wrapper
