from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from typing import Any, Awaitable, Callable

from app.memory.redis_store import get_redis
from app.utils.logger import get_logger

log = get_logger("debounce")

DEBOUNCE_SECONDS = 4
DEDUP_TTL = 30

# ── In-memory fallback structures ────────────────────────────────────
_pending_msgs: dict[str, list[str]] = {}
_versions: dict[str, str] = {}
_tasks: dict[str, asyncio.Task] = {}
_sent_hashes: dict[str, float] = {}


# ── Debounce ─────────────────────────────────────────────────────────


async def debounce_message(
    conversation_id: str,
    message: str,
    process_fn: Callable[[str], Awaitable[Any]],
) -> None:
    """Buffer incoming messages per conversation.

    After ``DEBOUNCE_SECONDS`` of silence, concatenate all buffered texts
    and invoke *process_fn* once with the combined message.
    """
    version = uuid.uuid4().hex
    pending_key = f"debounce:{conversation_id}:pending"
    version_key = f"debounce:{conversation_id}:version"

    r = await get_redis()
    if r:
        await r.rpush(pending_key, message)
        await r.expire(pending_key, DEBOUNCE_SECONDS + 30)
        await r.set(version_key, version, ex=DEBOUNCE_SECONDS + 30)
    else:
        _pending_msgs.setdefault(conversation_id, []).append(message)
        _versions[conversation_id] = version

    # Cancel any previous waiting task for this conversation
    prev = _tasks.pop(conversation_id, None)
    if prev and not prev.done():
        prev.cancel()

    async def _deferred() -> None:
        await asyncio.sleep(DEBOUNCE_SECONDS)

        # Check if we are still the latest version
        if r:
            current = await r.get(version_key)
        else:
            current = _versions.get(conversation_id)

        if current != version:
            return  # a newer message superseded us

        # Collect all buffered messages
        if r:
            msgs = await r.lrange(pending_key, 0, -1)
            await r.delete(pending_key, version_key)
        else:
            msgs = _pending_msgs.pop(conversation_id, [])
            _versions.pop(conversation_id, None)

        if not msgs:
            return

        combined = "\n".join(msgs)
        log.info(
            "[DEBOUNCE] Processing %d buffered msg(s) for conv %s (len=%d)",
            len(msgs), conversation_id, len(combined),
        )

        try:
            await process_fn(combined)
        except Exception as exc:
            log.error(
                "[DEBOUNCE] process_fn error for conv %s: %s",
                conversation_id, exc,
            )

    _tasks[conversation_id] = asyncio.create_task(_deferred())


# ── Deduplication ────────────────────────────────────────────────────


async def is_duplicate_response(conversation_id: str, text: str) -> bool:
    """Return True if *text* was already sent to *conversation_id*
    within the last ``DEDUP_TTL`` seconds."""
    h = hashlib.md5(f"{conversation_id}:{text}".encode()).hexdigest()
    dedup_key = f"dedup:{h}"

    r = await get_redis()
    if r:
        if await r.exists(dedup_key):
            log.warning("[DEDUP] Blocked duplicate for conv %s", conversation_id)
            return True
        await r.set(dedup_key, "1", ex=DEDUP_TTL)
        return False

    # In-memory fallback
    now = time.time()
    expired = [k for k, ts in _sent_hashes.items() if now - ts > DEDUP_TTL]
    for k in expired:
        del _sent_hashes[k]

    if h in _sent_hashes:
        log.warning("[DEDUP] Blocked duplicate for conv %s", conversation_id)
        return True
    _sent_hashes[h] = now
    return False
