from __future__ import annotations

import json
import time
from typing import Optional

import redis.asyncio as aioredis

from app.config import settings
from app.utils.logger import get_logger

log = get_logger("redis")

_pool: Optional[aioredis.Redis] = None
_redis_available: Optional[bool] = None

CONVERSATION_TTL = 3600 * 24  # 24 hours

# ── In-memory fallback when Redis is unavailable ─────────────────────
_mem_history: dict[str, list[str]] = {}
_mem_meta: dict[str, dict[str, str]] = {}
_mem_paused: bool = False


async def get_redis() -> Optional[aioredis.Redis]:
    global _pool, _redis_available
    if _redis_available is False:
        return None
    if _pool is None:
        try:
            _pool = aioredis.from_url(settings.redis_url, decode_responses=True)
            await _pool.ping()
            _redis_available = True
            log.info("Redis connection pool created")
        except Exception:
            _redis_available = False
            _pool = None
            log.warning("Redis unavailable — using in-memory fallback")
            return None
    return _pool


async def ping_redis() -> bool:
    try:
        r = await get_redis()
        if r is None:
            return False
        return await r.ping()
    except Exception:
        return False


# ── Conversation history ─────────────────────────────────────────────


def _history_key(conversation_id: str) -> str:
    return f"conv:{conversation_id}:history"


def _meta_key(conversation_id: str) -> str:
    return f"conv:{conversation_id}:meta"


async def add_message(
    conversation_id: str, role: str, content: str
) -> None:
    msg = json.dumps({"role": role, "content": content, "ts": time.time()})
    r = await get_redis()
    if r is None:
        hk = _history_key(conversation_id)
        _mem_history.setdefault(hk, []).append(msg)
        mk = _meta_key(conversation_id)
        if mk not in _mem_meta:
            _mem_meta[mk] = {"started_at": str(time.time())}
        return

    await r.rpush(_history_key(conversation_id), msg)
    await r.expire(_history_key(conversation_id), CONVERSATION_TTL)

    # Set started_at on first message
    meta_key = _meta_key(conversation_id)
    if not await r.exists(meta_key):
        await r.hset(meta_key, "started_at", str(time.time()))
        await r.expire(meta_key, CONVERSATION_TTL)


async def get_conversation_history(conversation_id: str) -> list[dict]:
    r = await get_redis()
    if r is None:
        raw = _mem_history.get(_history_key(conversation_id), [])
        return [json.loads(m) for m in raw]

    raw = await r.lrange(_history_key(conversation_id), 0, -1)
    return [json.loads(m) for m in raw]


async def get_conversation_metadata(conversation_id: str) -> dict:
    r = await get_redis()
    if r is None:
        return _mem_meta.get(_meta_key(conversation_id), {})

    data = await r.hgetall(_meta_key(conversation_id))
    return data or {}


async def set_conversation_metadata(
    conversation_id: str, key: str, value: str
) -> None:
    r = await get_redis()
    if r is None:
        mk = _meta_key(conversation_id)
        _mem_meta.setdefault(mk, {})[key] = value
        return

    await r.hset(_meta_key(conversation_id), key, value)
    await r.expire(_meta_key(conversation_id), CONVERSATION_TTL)


async def clear_conversation(conversation_id: str) -> None:
    r = await get_redis()
    if r is None:
        _mem_history.pop(_history_key(conversation_id), None)
        _mem_meta.pop(_meta_key(conversation_id), None)
        return

    await r.delete(_history_key(conversation_id), _meta_key(conversation_id))


# ── Pause state ──────────────────────────────────────────────────────

PAUSE_KEY = "lords-ai:paused"


async def is_paused() -> bool:
    r = await get_redis()
    if r is None:
        return _mem_paused

    return await r.exists(PAUSE_KEY) == 1


async def set_paused(paused: bool) -> None:
    global _mem_paused
    r = await get_redis()
    if r is None:
        _mem_paused = paused
        return

    if paused:
        await r.set(PAUSE_KEY, "1")
    else:
        await r.delete(PAUSE_KEY)
