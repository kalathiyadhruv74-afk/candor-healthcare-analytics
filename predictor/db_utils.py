"""
Safe DB helpers for Vercel serverless + remote MySQL.

Goals:
- Always release connections after use (prevents Too many connections)
- Lightweight TTL cache for metadata / identical report responses
- Soft per-process concurrency limit for heavy report APIs
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from django.db import connection, close_old_connections
from django.http import JsonResponse

# Cap concurrent heavy DB work inside one warm serverless instance
_HEAVY_REPORT_SEM = threading.Semaphore(1)
_CACHE_LOCK = threading.Lock()
_CACHE: Dict[str, Tuple[float, Any]] = {}


def close_db() -> None:
    """Force-close Django DB connections for this worker."""
    try:
        close_old_connections()
    except Exception:
        pass
    try:
        connection.close()
    except Exception:
        pass


@contextmanager
def db_cursor() -> Iterator[Any]:
    """Yield a cursor and always close the connection afterwards."""
    close_old_connections()
    cursor = connection.cursor()
    try:
        yield cursor
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        close_db()


def cache_get(key: str) -> Optional[Any]:
    now = time.time()
    with _CACHE_LOCK:
        item = _CACHE.get(key)
        if not item:
            return None
        expires_at, value = item
        if expires_at < now:
            _CACHE.pop(key, None)
            return None
        return value


def cache_set(key: str, value: Any, ttl_seconds: int = 45) -> None:
    with _CACHE_LOCK:
        # Bound memory on warm instances
        if len(_CACHE) > 200:
            now = time.time()
            expired = [k for k, (exp, _) in _CACHE.items() if exp < now]
            for k in expired:
                _CACHE.pop(k, None)
            if len(_CACHE) > 200:
                _CACHE.clear()
        _CACHE[key] = (time.time() + ttl_seconds, value)


def request_cache_key(prefix: str, request) -> str:
    items = sorted((k, v) for k, v in request.GET.items())
    raw = prefix + "|" + json.dumps(items, separators=(",", ":"), ensure_ascii=True)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def with_db_safety(
    *,
    cache_prefix: Optional[str] = None,
    cache_ttl: int = 45,
    heavy: bool = True,
    busy_message: str = "Report is busy. Please retry in a few seconds.",
):
    """
    Decorator for report APIs:
    - optional short response cache (reduces duplicate DB load)
    - optional single-flight semaphore (limits concurrent MySQL use per instance)
    - always closes DB connection after the handler returns
    """

    def decorator(view_func: Callable):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            cache_key = None
            if cache_prefix and request.method == "GET":
                cache_key = request_cache_key(cache_prefix, request)
                cached = cache_get(cache_key)
                if cached is not None:
                    return JsonResponse(cached)

            acquired = True
            if heavy:
                acquired = _HEAVY_REPORT_SEM.acquire(timeout=12)
                if not acquired:
                    return JsonResponse(
                        {"status": "error", "message": busy_message},
                        status=503,
                    )

            try:
                response = view_func(request, *args, **kwargs)
                if (
                    cache_key
                    and isinstance(response, JsonResponse)
                    and getattr(response, "status_code", 200) == 200
                ):
                    try:
                        payload = json.loads(response.content.decode("utf-8"))
                        if isinstance(payload, dict) and payload.get("status") == "success":
                            cache_set(cache_key, payload, ttl_seconds=cache_ttl)
                    except Exception:
                        pass
                return response
            finally:
                if heavy and acquired:
                    _HEAVY_REPORT_SEM.release()
                close_db()

        return wrapper

    return decorator


def fetch_all(sql: str, params: Optional[List[Any]] = None, *, close: bool = False) -> List[Tuple]:
    close_old_connections()
    cursor = connection.cursor()
    try:
        cursor.execute(sql, params or [])
        return list(cursor.fetchall())
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        if close:
            close_db()


def fetch_one(sql: str, params: Optional[List[Any]] = None, *, close: bool = False) -> Optional[Tuple]:
    close_old_connections()
    cursor = connection.cursor()
    try:
        cursor.execute(sql, params or [])
        return cursor.fetchone()
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        if close:
            close_db()


def get_branch_options(ttl_seconds: int = 300) -> List[Dict[str, Any]]:
    cached = cache_get("meta:branches")
    if cached is not None:
        return cached
    rows = fetch_all("SELECT id, name FROM branch WHERE status = 1 ORDER BY name")
    data = [{"id": r[0], "name": r[1]} for r in rows]
    cache_set("meta:branches", data, ttl_seconds=ttl_seconds)
    return data


def get_category_options(ttl_seconds: int = 300) -> List[Dict[str, Any]]:
    cached = cache_get("meta:categories")
    if cached is not None:
        return cached
    rows = fetch_all("SELECT id, name FROM category WHERE status = 1 ORDER BY name")
    data = [{"id": r[0], "name": r[1]} for r in rows]
    cache_set("meta:categories", data, ttl_seconds=ttl_seconds)
    return data


def get_donor_patient_ids(ttl_seconds: int = 120) -> set:
    cached = cache_get("meta:donor_pids")
    if cached is not None:
        return cached
    rows = fetch_all("SELECT id FROM patients WHERE is_donor = 1")
    data = {r[0] for r in rows}
    cache_set("meta:donor_pids", data, ttl_seconds=ttl_seconds)
    return data
