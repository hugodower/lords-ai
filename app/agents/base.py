from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from typing import Optional

from app.config import settings
from app.guards.rate_limiter import check_rate_limit
from app.guards.intent_classifier import classify_message_intent
from app.guards.context_builder import build_context
from app.guards.response_validator import validate_response
from app.guards.autonomy_limit import check_autonomy_limit
from app.integrations import supabase_client as sb
from app.integrations.chatwoot import chatwoot_client
from app.integrations.claude_client import generate_response
from app.memory.redis_store import add_message, get_conversation_history, is_paused
from app.memory.history import log_interaction
from app.models.schemas import AgentOutput, ProcessMessageResponse
from app.skills.business_hours import is_within_business_hours, get_after_hours_response
from app.skills.handoff import perform_handoff
from app.utils.logger import get_logger

log = get_logger("agent:base")

# Approximate cost per token for claude-sonnet-4-20250514
COST_PER_TOKEN = 0.000003  # ~$3/M input, varies


class BaseAgent(ABC):
    agent_type: str = "base"

    @abstractmethod
    def get_agent_type(self) -> str: ...

    async def process(
        self,
        org_id: str,
        conversation_id: str,
        contact_phone: str,
        contact_name: str,
        message: str,
    ) -> ProcessMessageResponse:
        """Main processing pipeline with all 7 guard layers."""
        start_time = time.time()
        agent_type = self.get_agent_type()

        # Load agent config
        agent_config = await sb.get_agent_config(org_id, agent_type)
        if not agent_config:
            log.warning("No active %s agent for org %s", agent_type, org_id)
            return ProcessMessageResponse(action="ignored", error="Agent not active")

        # Check if paused (kill switch)
        if await is_paused():
            log.info("Agents paused — ignoring message")
            return ProcessMessageResponse(action="ignored", error="Agents paused")

        # ── Layer 0: Business hours ──────────────────────────────────
        if not await is_within_business_hours(org_id):
            after_msg, behavior = await get_after_hours_response(org_id)
            if behavior == "silent":
                return ProcessMessageResponse(action="ignored", skill_used="business_hours")
            # Send after-hours message
            await chatwoot_client.send_message(conversation_id, after_msg)
            await log_interaction(
                org_id=org_id,
                conversation_id=conversation_id,
                contact_phone=contact_phone,
                contact_name=contact_name,
                agent_type=agent_type,
                message_role="assistant",
                message_text=after_msg,
                skill_used="business_hours",
                action_taken="after_hours",
            )
            if behavior == "reply_and_stop":
                return ProcessMessageResponse(
                    action="after_hours",
                    message_sent=after_msg,
                    skill_used="business_hours",
                    agent_type=agent_type,
                )
            # reply_and_qualify — continue processing

        # ── Layer 1: Rate limiter ────────────────────────────────────
        if not check_rate_limit(contact_phone, message):
            await log_interaction(
                org_id=org_id,
                conversation_id=conversation_id,
                contact_phone=contact_phone,
                contact_name=contact_name,
                agent_type=agent_type,
                message_role="user",
                message_text=message,
                action_taken="rate_limited",
            )
            return ProcessMessageResponse(action="ignored", error="Rate limited")

        # ── Layer 2: Intent classification ───────────────────────────
        intent, handoff_note = await classify_message_intent(message)
        if handoff_note:
            await perform_handoff(
                conversation_id=conversation_id,
                org_id=org_id,
                agent_config=agent_config,
                contact_name=contact_name,
                contact_phone=contact_phone,
                reason=handoff_note,
            )
            await log_interaction(
                org_id=org_id,
                conversation_id=conversation_id,
                contact_phone=contact_phone,
                contact_name=contact_name,
                agent_type=agent_type,
                message_role="user",
                message_text=message,
                action_taken="handoff",
                skill_used="handoff",
            )
            return ProcessMessageResponse(
                action="handoff",
                skill_used="handoff",
                agent_type=agent_type,
            )

        # Save incoming message to Redis
        await add_message(conversation_id, "user", message)

        # Log incoming message
        await log_interaction(
            org_id=org_id,
            conversation_id=conversation_id,
            contact_phone=contact_phone,
            contact_name=contact_name,
            agent_type=agent_type,
            message_role="user",
            message_text=message,
        )

        # ── Layer 3: Build context ──────────────────────────────────
        system_prompt = await build_context(
            org_id=org_id,
            agent_type=agent_type,
            agent_config=agent_config,
            conversation_id=conversation_id,
            contact_name=contact_name,
            contact_phone=contact_phone,
            user_message=message,
        )

        # Build message history for Claude
        history = await get_conversation_history(conversation_id)
        messages = [
            {"role": m["role"], "content": m["content"]}
            for m in history[-20:]  # Last 20 messages
        ]

        # ── Layer 4: Claude API ──────────────────────────────────────
        max_time = agent_config.get(
            "max_response_time_seconds", settings.max_response_time_seconds
        )
        try:
            raw_response, tokens_used = await generate_response(
                system_prompt=system_prompt,
                messages=messages,
                max_tokens=500,
                temperature=0.3,
            )
        except Exception as e:
            elapsed = time.time() - start_time
            log.error("Claude API error after %.1fs: %s", elapsed, e)
            return ProcessMessageResponse(action="error", error=str(e))

        # Parse agent output
        try:
            output = AgentOutput.model_validate_json(raw_response)
        except Exception:
            # Try to extract JSON from response
            try:
                json_start = raw_response.index("{")
                json_end = raw_response.rindex("}") + 1
                output = AgentOutput.model_validate_json(raw_response[json_start:json_end])
            except Exception:
                # Use raw text as response
                output = AgentOutput(text=raw_response, action="continue", skill_used="general")

        # ── Layer 5: Response validation ─────────────────────────────
        products = await sb.get_products(org_id)
        forbidden = await sb.get_forbidden_topics(org_id)
        validation = validate_response(output.text, products, forbidden)

        elapsed_ms = int((time.time() - start_time) * 1000)
        cost = tokens_used * COST_PER_TOKEN if tokens_used else None

        if not validation.passed:
            log.warning(
                "[VALIDATOR] Blocked response: %s — %s",
                validation.check_name, validation.reason,
            )
            # Handoff due to validation failure
            await perform_handoff(
                conversation_id=conversation_id,
                org_id=org_id,
                agent_config=agent_config,
                contact_name=contact_name,
                contact_phone=contact_phone,
                reason=f"Resposta da IA bloqueada: {validation.reason}",
            )
            await log_interaction(
                org_id=org_id,
                conversation_id=conversation_id,
                contact_phone=contact_phone,
                contact_name=contact_name,
                agent_type=agent_type,
                message_role="assistant",
                message_text=output.text,
                skill_used=output.skill_used,
                action_taken="blocked",
                validation_result=validation.check_name,
                tokens_used=tokens_used,
                cost_usd=cost,
                response_time_ms=elapsed_ms,
            )
            return ProcessMessageResponse(
                action="blocked",
                skill_used=output.skill_used,
                agent_type=agent_type,
            )

        # ── Layer 6: Autonomy limit ─────────────────────────────────
        max_msgs = agent_config.get("max_messages", 10)
        autonomy = await check_autonomy_limit(conversation_id, max_msgs)
        if autonomy.should_handoff:
            await perform_handoff(
                conversation_id=conversation_id,
                org_id=org_id,
                agent_config=agent_config,
                contact_name=contact_name,
                contact_phone=contact_phone,
                reason=autonomy.reason or "Limite de autonomia atingido.",
                lead_temperature=output.lead_temperature,
                extra_info=output.summary,
            )
            # Still send the last message before handoff
            await chatwoot_client.send_message(conversation_id, output.text)
            await add_message(conversation_id, "assistant", output.text)
            await log_interaction(
                org_id=org_id,
                conversation_id=conversation_id,
                contact_phone=contact_phone,
                contact_name=contact_name,
                agent_type=agent_type,
                message_role="assistant",
                message_text=output.text,
                skill_used=output.skill_used,
                action_taken="handoff",
                validation_result="passed",
                tokens_used=tokens_used,
                cost_usd=cost,
                response_time_ms=elapsed_ms,
            )
            return ProcessMessageResponse(
                action="handoff",
                message_sent=output.text,
                skill_used=output.skill_used,
                agent_type=agent_type,
            )

        # ── Success: send response ───────────────────────────────────
        action = output.action

        # Handle scheduling requested by the agent
        if action == "schedule" and output.schedule:
            from app.skills.schedule import execute_scheduling

            sched_result = await execute_scheduling(
                org_id=org_id,
                contact_name=contact_name,
                contact_phone=contact_phone,
                requested_date=output.schedule.requested_date,
                requested_time=output.schedule.requested_time,
            )
            if sched_result.get("success"):
                # Replace agent message with confirmation
                output.text = sched_result["confirmation_message"]
                action = "schedule"
            else:
                # Scheduling failed — send original text (fallback)
                log.warning(
                    "[SCHEDULE] Failed for conv %s: %s",
                    conversation_id, sched_result.get("error"),
                )

        # Handle handoff requested by the agent
        if action == "handoff":
            await chatwoot_client.send_message(conversation_id, output.text)
            await add_message(conversation_id, "assistant", output.text)
            await perform_handoff(
                conversation_id=conversation_id,
                org_id=org_id,
                agent_config=agent_config,
                contact_name=contact_name,
                contact_phone=contact_phone,
                reason=output.summary or "Agente solicitou handoff.",
                lead_temperature=output.lead_temperature,
            )
        else:
            try:
                await chatwoot_client.send_message(conversation_id, output.text)
            except Exception as send_err:
                log.warning("Chatwoot send failed (conv=%s): %s", conversation_id, send_err)
            await add_message(conversation_id, "assistant", output.text)

        # Update CRM if needed
        if action == "update_crm" or action == "schedule" or output.crm_updates:
            try:
                await sb.update_deal_ai_fields(org_id, contact_phone, agent_type)
            except Exception as crm_err:
                log.warning("CRM update failed: %s", crm_err)

        # ── Layer 7: Log ─────────────────────────────────────────────
        await log_interaction(
            org_id=org_id,
            conversation_id=conversation_id,
            contact_phone=contact_phone,
            contact_name=contact_name,
            agent_type=agent_type,
            message_role="assistant",
            message_text=output.text,
            skill_used=output.skill_used,
            action_taken=action,
            validation_result="passed",
            tokens_used=tokens_used,
            cost_usd=cost,
            response_time_ms=elapsed_ms,
        )

        log.info(
            "Processed message: conv=%s action=%s skill=%s time=%dms tokens=%d",
            conversation_id, action, output.skill_used, elapsed_ms, tokens_used,
        )

        return ProcessMessageResponse(
            action=action,
            message_sent=output.text,
            skill_used=output.skill_used,
            agent_type=agent_type,
        )
