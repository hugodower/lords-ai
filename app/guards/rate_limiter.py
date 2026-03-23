from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field

from app.utils.logger import get_logger

log = get_logger("rate_limiter")

# In-memory store (reset on restart — acceptable for rate limiting)
_message_times: dict[str, list[float]] = defaultdict(list)
_recent_messages: dict[str, list[str]] = defaultdict(list)

MAX_MESSAGES_PER_MINUTE = 30
MAX_IDENTICAL_CONSECUTIVE = 5
WINDOW_SECONDS = 60


def check_rate_limit(phone: str, message: str) -> bool:
    """Return True if the message should be processed, False if rate-limited."""
    now = time.time()

    # Clean old entries
    _message_times[phone] = [
        t for t in _message_times[phone] if now - t < WINDOW_SECONDS
    ]

    # Check messages per minute
    if len(_message_times[phone]) >= MAX_MESSAGES_PER_MINUTE:
        log.warning("[RATE_LIMIT] Phone %s exceeded %d msgs/min", phone, MAX_MESSAGES_PER_MINUTE)
        return False

    # Check identical consecutive messages
    recent = _recent_messages[phone]
    if len(recent) >= MAX_IDENTICAL_CONSECUTIVE:
        if all(m == message for m in recent[-MAX_IDENTICAL_CONSECUTIVE:]):
            log.warning("[RATE_LIMIT] Phone %s sent %d identical msgs", phone, MAX_IDENTICAL_CONSECUTIVE)
            return False

    # Record this message
    _message_times[phone].append(now)
    _recent_messages[phone].append(message)
    # Keep only last N messages in memory
    if len(_recent_messages[phone]) > MAX_IDENTICAL_CONSECUTIVE + 5:
        _recent_messages[phone] = _recent_messages[phone][-MAX_IDENTICAL_CONSECUTIVE - 5:]

    return True


def reset_rate_limits() -> None:
    """Reset all rate limit state (useful for tests)."""
    _message_times.clear()
    _recent_messages.clear()
