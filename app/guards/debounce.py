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
    using_redis = r is not None

    log.info(
        "[DEBOUNCE] Received msg for conv=%s version=%s redis=%s msg_preview='%s'",
        conversation_id, version[:8], using_redis, message[:80],
    )

    if using_redis:
        await r.rpush(pending_key, message)
        await r.expire(pending_key, DEBOUNCE_SECONDS + 30)
        await r.set(version_key, version, ex=DEBOUNCE_SECONDS + 30)
        buffered_count = await r.llen(pending_key)
        log.info(
            "[DEBOUNCE] Buffered in Redis: conv=%s total_pending=%d version=%s",
            conversation_id, buffered_count, version[:8],
        )
    else:
        _pending_msgs.setdefault(conversation_id, []).append(message)
        _versions[conversation_id] = version
        log.info(
            "[DEBOUNCE] Buffered in-memory: conv=%s total_pending=%d version=%s",
            conversation_id, len(_pending_msgs.get(conversation_id, [])), version[:8],
        )

    # Cancel any previous waiting task for this conversation
    prev = _tasks.pop(conversation_id, None)
    if prev and not prev.done():
        prev.cancel()
        log.info("[DEBOUNCE] Cancelled previous timer for conv=%s", conversation_id)

    async def _deferred() -> None:
        log.info(
            "[DEBOUNCE] Timer started: conv=%s waiting %ds version=%s",
            conversation_id, DEBOUNCE_SECONDS, version[:8],
        )
        await asyncio.sleep(DEBOUNCE_SECONDS)

        # Re-acquire Redis connection (don't rely on stale reference)
        _r = await get_redis()
        _using_redis = _r is not None

        # Check if we are still the latest version
        if _using_redis:
            current = await _r.get(version_key)
        else:
            current = _versions.get(conversation_id)

        if current != version:
            log.info(
                "[DEBOUNCE] Superseded: conv=%s our_version=%s current=%s — skipping",
                conversation_id, version[:8], (current or "None")[:8],
            )
            return  # a newer message superseded us

        # Collect all buffered messages
        if _using_redis:
            msgs = await _r.lrange(pending_key, 0, -1)
            await _r.delete(pending_key, version_key)
        else:
            msgs = _pending_msgs.pop(conversation_id, [])
            _versions.pop(conversation_id, None)

        if not msgs:
            log.warning("[DEBOUNCE] No messages found after timer for conv=%s", conversation_id)
            return

        combined = "\n".join(msgs)
        log.info(
            "[DEBOUNCE] FIRING: conv=%s msgs=%d combined_len=%d version=%s content='%s'",
            conversation_id, len(msgs), len(combined), version[:8], combined[:150],
        )

        try:
            await process_fn(combined)
            log.info("[DEBOUNCE] process_fn completed for conv=%s", conversation_id)
        except Exception as exc:
            log.error(
                "[DEBOUNCE] process_fn ERROR for conv %s: %s",
                conversation_id, exc, exc_info=True,
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
