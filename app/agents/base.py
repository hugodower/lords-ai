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
from app.memory.redis_store import add_message, get_conversation_history, is_paused, save_agreed_schedule
from app.memory.history import log_interaction
from app.models.schemas import AgentOutput, ProcessMessageResponse
from app.skills.business_hours import is_within_business_hours, get_after_hours_response
from app.guards.debounce import is_duplicate_response
from app.services.followup_scheduler import cancel_pending_followups, schedule_followups_after_reply
from app.services.memory_manager import load_contact_memory, maybe_update_memory
from app.services.sentiment_analyzer import analyze_sentiment
from app.services.pipeline_manager import update_stage, add_label_to_chatwoot, ensure_contact_and_deal, swap_chatwoot_label, set_priority
from app.services.conversation_resolver import resolve_conversation, schedule_resolve
from app.skills.handoff import perform_handoff
from app.utils.logger import get_logger
from app.utils.phone import normalize_phone

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
        chatwoot_contact_id: str = "",
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

        # ── Sandbox guard ──────────────────────────────────────────
        if settings.sandbox_mode:
            allowed = {
                normalize_phone(p.strip())
                for p in settings.sandbox_phones.split(",")
                if p.strip()
            }
            # Also include phones from DB agent_config
            db_phones = agent_config.get("sandbox_phones") or []
            for p in db_phones:
                if p.strip():
                    allowed.add(normalize_phone(p.strip()))

            caller = normalize_phone(contact_phone) if contact_phone else ""
            if caller not in allowed:
                log.info(
                    "[SANDBOX] Phone %s not in allowed list, ignoring silently",
                    contact_phone,
                )
                return ProcessMessageResponse(action="ignored", error="Sandbox: phone not allowed")

        # ── Layer 0: Business hours ──────────────────────────────────
        if not await is_within_business_hours(org_id):
            after_msg, behavior = await get_after_hours_response(org_id)
            if behavior == "silent":
                return ProcessMessageResponse(action="ignored", skill_used="business_hours")
            # Send after-hours message
            await chatwoot_client.send_message(conversation_id, after_msg, org_id=org_id)
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

        # Cancel pending follow-ups (lead responded)
        try:
            conv_id_int = int(conversation_id)
            await cancel_pending_followups(conv_id_int, reason="lead respondeu")
        except (ValueError, TypeError):
            log.warning("[FOLLOWUP] Could not parse conversation_id=%s as int", conversation_id)

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

        # ── Sentiment analysis ────────────────────────────────────
        sentiment_data = {"sentiment": "neutral", "confidence": 1.0, "tone_adjustment": ""}
        try:
            sentiment_data = await analyze_sentiment(message)
            if sentiment_data["sentiment"] != "neutral":
                log.info(
                    "[SENTIMENT] Detectado: %s (confidence: %.2f) conv=%s",
                    sentiment_data["sentiment"], sentiment_data["confidence"],
                    conversation_id,
                )
        except Exception as sent_err:
            log.warning("[SENTIMENT] Error analyzing sentiment: %s", sent_err)

        # ── Load long-term memory ─────────────────────────────────
        contact_memory = None
        try:
            contact_memory = await load_contact_memory(org_id, contact_phone)
        except Exception as mem_err:
            log.warning("[MEMORY] Error loading contact memory: %s", mem_err)

        # ── Auto-handoff for persistent frustration ───────────────
        if sentiment_data["sentiment"] == "frustrated":
            history_check = await get_conversation_history(conversation_id)
            assistant_msgs = sum(1 for m in history_check if m.get("role") == "assistant")
            if assistant_msgs >= 2:
                log.warning(
                    "[SENTIMENT:ALERT] Lead frustrado após %d interações, sugerindo handoff conv=%s",
                    assistant_msgs, conversation_id,
                )
                await perform_handoff(
                    conversation_id=conversation_id,
                    org_id=org_id,
                    agent_config=agent_config,
                    contact_name=contact_name,
                    contact_phone=contact_phone,
                    reason="Lead demonstrando frustração persistente — transferindo para atendente humano.",
                )
                handoff_msg = (
                    "Entendo sua frustração e peço desculpas pelo inconveniente. "
                    "Vou te transferir agora para um atendente que pode te ajudar melhor, tudo bem?"
                )
                await chatwoot_client.send_message(conversation_id, handoff_msg, org_id=org_id)
                await add_message(conversation_id, "assistant", handoff_msg)
                await log_interaction(
                    org_id=org_id,
                    conversation_id=conversation_id,
                    contact_phone=contact_phone,
                    contact_name=contact_name,
                    agent_type=agent_type,
                    message_role="assistant",
                    message_text=handoff_msg,
                    skill_used="sentiment",
                    action_taken="handoff",
                )
                # Pipeline: move to negociacao + resolve (frustrated handoff)
                try:
                    await update_stage(org_id, contact_phone, conversation_id, "em_negociacao", contact_name, chatwoot_contact_id)
                    await resolve_conversation(org_id, conversation_id, "handoff_frustrado")
                except Exception as _pe:
                    log.warning("[PIPELINE] Error on frustrated handoff: %s", _pe)
                return ProcessMessageResponse(
                    action="handoff",
                    message_sent=handoff_msg,
                    skill_used="sentiment",
                    agent_type=agent_type,
                )

        # ── Layer 3: Build context ──────────────────────────────────
        try:
            system_prompt = await build_context(
                org_id=org_id,
                agent_type=agent_type,
                agent_config=agent_config,
                conversation_id=conversation_id,
                contact_name=contact_name,
                contact_phone=contact_phone,
                user_message=message,
                contact_memory=contact_memory,
                sentiment_data=sentiment_data,
            )
        except Exception as ctx_err:
            log.error("build_context failed: %s", ctx_err)
            system_prompt = ""

        if not system_prompt:
            agent_name = agent_config.get("agent_name", "Ana")
            personality = agent_config.get("personality", "")
            log.warning("Empty system prompt — using fallback for org=%s", org_id)
            system_prompt = (
                f"Você é {agent_name}, assistente virtual. "
                f"{personality} "
                "Responda de forma curta, máximo 3 linhas, sem listas, tom informal. "
                "Nunca revele que é Claude ou IA."
            ).strip()

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
        log.info(
            "[CLAUDE_RAW] conv=%s raw_response (first 500 chars): %s",
            conversation_id, raw_response[:500],
        )
        try:
            output = AgentOutput.model_validate_json(raw_response)
            log.info("[CLAUDE_PARSED] conv=%s action=%s schedule=%s", conversation_id, output.action, output.schedule is not None)
        except Exception:
            # Try to extract JSON from response
            try:
                json_start = raw_response.index("{")
                json_end = raw_response.rindex("}") + 1
                json_substr = raw_response[json_start:json_end]
                output = AgentOutput.model_validate_json(json_substr)
                log.info("[CLAUDE_PARSED] conv=%s (extracted) action=%s schedule=%s", conversation_id, output.action, output.schedule is not None)
            except Exception as parse_err:
                # Use raw text as response
                log.warning("[CLAUDE_PARSED] conv=%s JSON parse failed (%s), using raw text", conversation_id, parse_err)
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
            await chatwoot_client.send_message(conversation_id, output.text, org_id=org_id)
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

        # ── Persist agreed schedule data to Redis ──────────────────
        # Save any schedule fields Claude mentioned, even before the
        # actual booking — so they survive across message cycles.
        if output.schedule:
            agreed_data = {}
            s = output.schedule
            if s.requested_date:
                agreed_data["requested_date"] = s.requested_date
            if s.requested_time:
                agreed_data["requested_time"] = s.requested_time
            if s.attendee_name:
                agreed_data["attendee_name"] = s.attendee_name
            if s.attendee_email:
                agreed_data["attendee_email"] = s.attendee_email
            if s.participant:
                agreed_data["participant"] = s.participant
            if s.whatsapp_for_reminders:
                agreed_data["whatsapp_for_reminders"] = s.whatsapp_for_reminders
            if s.interest:
                agreed_data["interest"] = s.interest
            if agreed_data:
                await save_agreed_schedule(conversation_id, agreed_data)

        # ── Success: send response ───────────────────────────────────
        action = output.action

        # FIX 8: Validate consistency action ↔ temperature
        if action == "schedule" and output.lead_temperature != "hot":
            log.info("[PIPELINE:OVERRIDE] action=schedule but temp=%s, forcing hot", output.lead_temperature)
            output.lead_temperature = "hot"
        if action == "handoff" and output.lead_temperature == "cold":
            log.info("[PIPELINE:OVERRIDE] action=handoff but temp=cold, forcing warm")
            output.lead_temperature = "warm"

        # Log full Claude output for debugging action routing
        log.info(
            "[AGENT_OUTPUT] conv=%s action='%s' skill='%s' temp='%s' "
            "has_schedule=%s schedule_data=%s text_preview='%s'",
            conversation_id, output.action, output.skill_used,
            output.lead_temperature, output.schedule is not None,
            output.schedule.model_dump() if output.schedule else None,
            output.text[:100],
        )

        # Handle scheduling requested by the agent
        if action == "schedule":
            from app.skills.schedule import execute_scheduling

            _sched_error_msg = (
                "Opa, tive um probleminha pra confirmar o horario agora. "
                "Vou pedir pra equipe agendar manualmente e te confirmo em breve, tudo bem?"
            )

            if not output.schedule:
                log.error(
                    "[SCHEDULE] action='schedule' but output.schedule is NULL — "
                    "Claude forgot to fill schedule fields. conv=%s raw_text='%s'",
                    conversation_id, output.text[:200],
                )
                output.text = _sched_error_msg
                action = "continue"
            elif not output.schedule.requested_date or not output.schedule.requested_time:
                log.error(
                    "[SCHEDULE] action='schedule' but missing date/time — "
                    "date=%s time=%s conv=%s schedule_dump=%s",
                    output.schedule.requested_date, output.schedule.requested_time,
                    conversation_id, output.schedule.model_dump(),
                )
                output.text = _sched_error_msg
                action = "continue"
            else:
                log.info(
                    "[SCHEDULE] Attempting: conv=%s date=%s time=%s contact=%s "
                    "attendee=%s email=%s participant=%s whatsapp=%s interest=%s",
                    conversation_id, output.schedule.requested_date,
                    output.schedule.requested_time, contact_name,
                    output.schedule.attendee_name, output.schedule.attendee_email,
                    output.schedule.participant, output.schedule.whatsapp_for_reminders,
                    output.schedule.interest,
                )
                sched_result = await execute_scheduling(
                    org_id=org_id,
                    contact_name=contact_name,
                    contact_phone=contact_phone,
                    contact_email=output.schedule.attendee_email,
                    requested_date=output.schedule.requested_date,
                    requested_time=output.schedule.requested_time,
                    attendee_name=output.schedule.attendee_name,
                    participant=output.schedule.participant,
                    whatsapp_for_reminders=output.schedule.whatsapp_for_reminders,
                    interest=output.schedule.interest,
                    conversation_id=conversation_id,
                )
                if sched_result.get("success"):
                    output.text = sched_result["confirmation_message"]
                    action = "schedule"
                    log.info(
                        "[SCHEDULE] SUCCESS: conv=%s event_id=%s confirmation='%s'",
                        conversation_id, sched_result.get("event_id"),
                        sched_result.get("confirmation_message", "")[:100],
                    )
                else:
                    error_detail = sched_result.get("error", "unknown")
                    log.error(
                        "[SCHEDULE] FAILED for conv %s: %s — replacing Claude's "
                        "false confirmation with error message",
                        conversation_id, error_detail,
                    )
                    # Use specific message for past dates
                    if error_detail == "past_date":
                        output.text = (
                            sched_result.get("message")
                            or "Essa data ja passou! Pode me dizer outro dia e horario?"
                        )
                    else:
                        output.text = _sched_error_msg
                    action = "continue"

        # Dedup check (skip for handoff — those are critical)
        if action != "handoff" and await is_duplicate_response(conversation_id, output.text):
            log.warning("[DEDUP] Duplicate response skipped for conv %s", conversation_id)
            return ProcessMessageResponse(action="ignored", error="Duplicate response")

        # Handle handoff requested by the agent
        if action == "handoff":
            await chatwoot_client.send_message(conversation_id, output.text, org_id=org_id)
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
                await chatwoot_client.send_message(conversation_id, output.text, org_id=org_id)
            except Exception as send_err:
                log.warning("Chatwoot send failed (conv=%s): %s", conversation_id, send_err)
            await add_message(conversation_id, "assistant", output.text)

        # Update CRM if needed
        if action == "update_crm" or action == "schedule" or output.crm_updates:
            try:
                await sb.update_deal_ai_fields(org_id, contact_phone, agent_type)
            except Exception as crm_err:
                log.warning("CRM update failed: %s", crm_err)

        # ── Pipeline management & conversation resolution ──────────
        try:
            log.info(
                "[PIPELINE:TRIGGER] conv=%s action='%s' temp='%s' crm_stage='%s' crm_tags=%s",
                conversation_id, action, output.lead_temperature,
                output.crm_updates.stage if output.crm_updates else None,
                output.crm_updates.tags if output.crm_updates else [],
            )
            if action == "schedule":
                log.info("[PIPELINE:TRIGGER] → calling update_stage('reuniao_agendada') for conv %s", conversation_id)
                await update_stage(org_id, contact_phone, conversation_id, "reuniao_agendada", contact_name, chatwoot_contact_id)
                schedule_resolve(org_id, conversation_id, 30, "reuniao_agendada")
            elif action == "handoff":
                log.info("[PIPELINE:TRIGGER] → calling update_stage('em_negociacao') for conv %s", conversation_id)
                await update_stage(org_id, contact_phone, conversation_id, "em_negociacao", contact_name, chatwoot_contact_id)
            elif output.lead_temperature in ("hot", "warm"):
                log.info("[PIPELINE:TRIGGER] → calling update_stage('qualificado') for conv %s (temp=%s)", conversation_id, output.lead_temperature)
                await update_stage(org_id, contact_phone, conversation_id, "qualificado", contact_name, chatwoot_contact_id)
            else:
                log.info("[PIPELINE:TRIGGER] → calling ensure_contact_and_deal() for conv %s (temp=%s)", conversation_id, output.lead_temperature)
                await ensure_contact_and_deal(org_id, contact_phone, contact_name, chatwoot_contact_id, conversation_id)

            # CRM-driven stage move (if Claude specified a stage explicitly)
            if output.crm_updates and output.crm_updates.stage:
                log.info("[PIPELINE:TRIGGER] → CRM override: update_stage('%s') for conv %s", output.crm_updates.stage, conversation_id)
                await update_stage(org_id, contact_phone, conversation_id, output.crm_updates.stage, contact_name, chatwoot_contact_id)
            if output.crm_updates and output.crm_updates.tags:
                for tag in output.crm_updates.tags:
                    await add_label_to_chatwoot(org_id, conversation_id, tag)
        except Exception as pipe_err:
            log.warning("[PIPELINE] Pipeline/resolve error: %s", pipe_err, exc_info=True)

        # ── Set conversation priority based on sentiment ──────────
        try:
            await set_priority(org_id, conversation_id, sentiment_data.get("sentiment", "neutral"))
        except Exception as prio_err:
            log.warning("[PIPELINE:PRIORITY] Error: %s", prio_err)

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

        # Update long-term memory (background task, non-blocking)
        try:
            await maybe_update_memory(
                org_id=org_id,
                contact_phone=contact_phone,
                contact_name=contact_name,
                conversation_id=conversation_id,
                action=action,
                lead_temperature=output.lead_temperature,
                last_sentiment=sentiment_data.get("sentiment", "neutral"),
            )
        except Exception as mem_err:
            log.warning("[MEMORY] Error triggering memory update: %s", mem_err)

        # Schedule follow-ups after Aurora replies (if lead doesn't respond, these will fire)
        if action not in ("handoff", "blocked", "ignored"):
            try:
                conv_id_int = int(conversation_id)
                await schedule_followups_after_reply(
                    org_id=org_id,
                    conversation_id=conv_id_int,
                    contact_phone=contact_phone,
                    contact_name=contact_name,
                    action=action,
                    lead_temperature=output.lead_temperature,
                    skill_used=output.skill_used,
                )
            except Exception as fu_err:
                log.warning("[FOLLOWUP] Error scheduling follow-ups: %s", fu_err)

        return ProcessMessageResponse(
            action=action,
            message_sent=output.text,
            skill_used=output.skill_used,
            agent_type=agent_type,
        )
