from __future__ import annotations

from app.memory.redis_store import get_conversation_metadata, set_conversation_metadata
from app.integrations import supabase_client as sb
from app.utils.logger import get_logger

log = get_logger("skill:qualify")


async def get_current_step(conversation_id: str) -> int:
    """Get the current qualification step for this conversation."""
    meta = await get_conversation_metadata(conversation_id)
    return int(meta.get("qual_step", "0"))


async def advance_step(conversation_id: str) -> int:
    """Advance to the next qualification step. Returns new step number."""
    current = await get_current_step(conversation_id)
    new_step = current + 1
    await set_conversation_metadata(conversation_id, "qual_step", str(new_step))
    log.info("Conv %s advanced to qualification step %d", conversation_id, new_step)
    return new_step


async def is_qualification_complete(
    org_id: str, conversation_id: str, agent_type: str = "sdr"
) -> bool:
    """Check if all required qualification steps have been completed."""
    steps = await sb.get_qualification_steps(org_id, agent_type)
    if not steps:
        return True  # No steps configured — consider it complete
    current = await get_current_step(conversation_id)
    required_count = sum(1 for s in steps if s.get("is_required", True))
    return current >= required_count


async def get_qualification_progress(
    org_id: str, conversation_id: str, agent_type: str = "sdr"
) -> dict:
    """Get qualification progress summary."""
    steps = await sb.get_qualification_steps(org_id, agent_type)
    current = await get_current_step(conversation_id)
    total = len(steps)
    return {
        "current_step": current,
        "total_steps": total,
        "completed": current >= total,
        "progress_pct": (current / total * 100) if total > 0 else 100,
    }
