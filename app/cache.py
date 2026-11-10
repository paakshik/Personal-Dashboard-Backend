import json
import os
import logging
from typing import Any

logger = logging.getLogger(__name__)
REDIS_URL = os.getenv("REDIS_URL")
_client = None
if REDIS_URL:
    try:
        import redis
        _client = redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=1, socket_timeout=1, health_check_interval=30)
    except Exception as exc:
        logger.warning("Redis client initialization failed; using PostgreSQL directly: %s", exc)


def get_json(key: str):
    if not _client:
        return None
    try:
        value = _client.get(key)
        return json.loads(value) if value else None
    except Exception as exc:
        logger.warning("Redis read failed for %s: %s", key, exc)
        return None


def set_json(key: str, value: Any, ttl: int = 60) -> None:
    if not _client:
        return
    try:
        _client.setex(key, ttl, json.dumps(value, default=str))
    except Exception as exc:
        logger.warning("Redis write failed for %s: %s", key, exc)


def delete_pattern(pattern: str) -> None:
    if not _client:
        return
    try:
        keys = _client.scan_iter(match=pattern, count=200)
        batch = []
        for key in keys:
            batch.append(key)
            if len(batch) >= 200:
                _client.delete(*batch)
                batch.clear()
        if batch:
            _client.delete(*batch)
    except Exception as exc:
        logger.warning("Redis invalidation failed for %s: %s", pattern, exc)
