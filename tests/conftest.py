from __future__ import annotations

import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Set env vars before importing app modules
os.environ.setdefault("ORG_ID", "test-org-001")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")
os.environ.setdefault("CLAUDE_API_KEY", "sk-ant-test")
os.environ.setdefault("CHATWOOT_URL", "https://chat.test.com")
os.environ.setdefault("CHATWOOT_API_TOKEN", "test-token")
os.environ.setdefault("CHATWOOT_ACCOUNT_ID", "1")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("CHROMA_URL", "http://localhost:8000")


ORG_ID = "test-org-001"


@pytest.fixture
def org_id():
    return ORG_ID


@pytest.fixture
def sample_agent_config():
    return {
        "id": "cfg-001",
        "organization_id": ORG_ID,
        "agent_type": "sdr",
        "is_active": True,
        "agent_name": "Ana",
        "personality": "Profissional, simpática e objetiva.",
        "max_messages": 10,
        "max_response_time_seconds": 10,
        "handoff_agent_id": 42,
        "handoff_agent_name": "Carlos",
    }


@pytest.fixture
def sample_products():
    return [
        {"id": "prod-001", "name": "Fisioterapia", "description": "Sessão de fisioterapia", "unit_price": 150.00, "category": "Saúde", "is_active": True},
        {"id": "prod-002", "name": "RPG", "description": "Reeducação Postural Global", "unit_price": 200.00, "category": "Saúde", "is_active": True},
        {"id": "prod-003", "name": "Pilates", "description": "Aula de pilates", "unit_price": 120.00, "category": "Saúde", "is_active": True},
    ]


@pytest.fixture
def sample_qualification_steps():
    return [
        {"step_order": 1, "question": "Qual o seu nome completo?", "is_required": True},
        {"step_order": 2, "question": "Qual serviço te interessa?", "is_required": True},
        {"step_order": 3, "question": "Você tem convênio?", "is_required": True},
        {"step_order": 4, "question": "Qual o melhor horário para atendimento?", "is_required": False},
    ]


@pytest.fixture
def sample_forbidden_topics():
    return ["política", "religião", "concorrentes"]


@pytest.fixture
def sample_company_info():
    return {
        "company_name": "Clínica Saúde Total",
        "segment": "Saúde",
        "description": "Clínica de fisioterapia e reabilitação",
        "address": "Rua das Flores, 123 - Centro",
        "website": "https://clinicasaudetotal.com.br",
        "payment_methods": "Dinheiro, PIX, Cartão (crédito/débito), Convênios",
        "differentials": "Profissionais especializados, atendimento humanizado",
    }


@pytest.fixture
def mock_supabase(
    sample_agent_config,
    sample_products,
    sample_qualification_steps,
    sample_forbidden_topics,
    sample_company_info,
):
    """Mock all Supabase calls."""
    with patch("app.integrations.supabase_client.get_supabase") as mock:
        mock.return_value = MagicMock()
        with (
            patch("app.integrations.supabase_client.get_agent_config", new_callable=AsyncMock) as cfg,
            patch("app.integrations.supabase_client.get_active_agents", new_callable=AsyncMock) as active,
            patch("app.integrations.supabase_client.get_company_info", new_callable=AsyncMock) as comp,
            patch("app.integrations.supabase_client.get_products", new_callable=AsyncMock) as prods,
            patch("app.integrations.supabase_client.get_qualification_steps", new_callable=AsyncMock) as steps,
            patch("app.integrations.supabase_client.get_quick_responses", new_callable=AsyncMock) as faq,
            patch("app.integrations.supabase_client.get_forbidden_topics", new_callable=AsyncMock) as forb,
            patch("app.integrations.supabase_client.get_hot_criteria", new_callable=AsyncMock) as hot,
            patch("app.integrations.supabase_client.get_business_hours", new_callable=AsyncMock) as bh,
            patch("app.integrations.supabase_client.get_business_hours_config", new_callable=AsyncMock) as bhc,
            patch("app.integrations.supabase_client.get_scheduling_config", new_callable=AsyncMock) as sched,
            patch("app.integrations.supabase_client.save_conversation_log", new_callable=AsyncMock) as save_log,
            patch("app.integrations.supabase_client.update_deal_ai_fields", new_callable=AsyncMock) as upd_deal,
            patch("app.integrations.supabase_client.get_conversation_logs", new_callable=AsyncMock) as get_logs,
            patch("app.integrations.supabase_client.get_metrics", new_callable=AsyncMock) as get_met,
        ):
            cfg.return_value = sample_agent_config
            active.return_value = [{"agent_type": "sdr", "agent_name": "Ana", "is_active": True}]
            comp.return_value = sample_company_info
            prods.return_value = sample_products
            steps.return_value = sample_qualification_steps
            faq.return_value = [{"trigger_keyword": "horário", "response_text": "Atendemos de seg a sex, 8h às 18h."}]
            forb.return_value = sample_forbidden_topics
            hot.return_value = "Quando demonstrar interesse claro em agendar avaliação."
            bh.return_value = []
            bhc.return_value = None
            sched.return_value = None
            save_log.return_value = None
            upd_deal.return_value = None
            get_logs.return_value = ([], 0)
            get_met.return_value = {"messages_processed": 0, "handoffs": 0, "blocked": 0, "avg_response_time_ms": 0, "cost_estimate_usd": 0}

            yield {
                "get_agent_config": cfg,
                "get_active_agents": active,
                "get_company_info": comp,
                "get_products": prods,
                "get_qualification_steps": steps,
                "get_quick_responses": faq,
                "get_forbidden_topics": forb,
                "get_hot_criteria": hot,
                "get_business_hours": bh,
                "get_business_hours_config": bhc,
                "get_scheduling_config": sched,
                "save_conversation_log": save_log,
                "update_deal_ai_fields": upd_deal,
            }


@pytest.fixture
def mock_chatwoot():
    """Mock Chatwoot client — patches at all import locations."""
    with (
        patch("app.integrations.chatwoot.chatwoot_client.send_message", new_callable=AsyncMock) as send,
        patch("app.integrations.chatwoot.chatwoot_client.send_private_note", new_callable=AsyncMock) as note,
        patch("app.integrations.chatwoot.chatwoot_client.assign_agent", new_callable=AsyncMock) as assign,
        patch("app.integrations.chatwoot.chatwoot_client.add_label", new_callable=AsyncMock) as label,
        patch("app.skills.handoff.chatwoot_client") as handoff_cw,
        patch("app.agents.base.chatwoot_client") as base_cw,
    ):
        send.return_value = {"id": 1}
        note.return_value = {"id": 2}
        assign.return_value = {"id": 3}
        label.return_value = {"payload": ["handoff-ia"]}

        for cw in (handoff_cw, base_cw):
            cw.send_message = AsyncMock(return_value={"id": 1})
            cw.send_private_note = AsyncMock(return_value={"id": 2})
            cw.assign_agent = AsyncMock(return_value={"id": 3})
            cw.add_label = AsyncMock(return_value={"payload": ["handoff-ia"]})

        yield {
            "send_message": send,
            "send_private_note": note,
            "assign_agent": assign,
            "add_label": label,
            "handoff_cw": handoff_cw,
        }


@pytest.fixture
def mock_redis():
    """Mock Redis store — patches ALL locations where redis functions are imported."""
    history = []
    now = str(time.time())

    async def mock_add_message(conv_id, role, content):
        history.append({"role": role, "content": content, "ts": 0})

    async def mock_get_history(conv_id):
        return list(history)

    async def mock_get_metadata(conv_id):
        return {"started_at": now}

    async def mock_is_paused():
        return False

    async def mock_ping():
        return True

    patches = [
        patch("app.memory.redis_store.get_redis", new_callable=AsyncMock),
        patch("app.memory.redis_store.ping_redis", side_effect=mock_ping),
        patch("app.memory.redis_store.add_message", side_effect=mock_add_message),
        patch("app.memory.redis_store.get_conversation_history", side_effect=mock_get_history),
        patch("app.memory.redis_store.get_conversation_metadata", side_effect=mock_get_metadata),
        patch("app.memory.redis_store.is_paused", side_effect=mock_is_paused),
        patch("app.memory.redis_store.clear_conversation", new_callable=AsyncMock),
        patch("app.memory.redis_store.set_conversation_metadata", new_callable=AsyncMock),
        # base.py imports
        patch("app.agents.base.is_paused", side_effect=mock_is_paused),
        patch("app.agents.base.add_message", side_effect=mock_add_message),
        patch("app.agents.base.get_conversation_history", side_effect=mock_get_history),
        # guards imports
        patch("app.guards.autonomy_limit.get_conversation_history", side_effect=mock_get_history),
        patch("app.guards.autonomy_limit.get_conversation_metadata", side_effect=mock_get_metadata),
        patch("app.guards.context_builder.get_conversation_history", side_effect=mock_get_history),
        # skills imports
        patch("app.skills.handoff.get_conversation_history", side_effect=mock_get_history),
        patch("app.skills.handoff.get_conversation_metadata", side_effect=mock_get_metadata),
        patch("app.skills.handoff.clear_conversation", new_callable=AsyncMock),
        # history module
        patch("app.memory.history.save_conversation_log", new_callable=AsyncMock),
    ]

    for p in patches:
        p.start()
    yield history
    for p in patches:
        p.stop()


@pytest.fixture
def mock_chroma():
    """Mock ChromaDB / RAG."""
    with (
        patch("app.knowledge.rag.search_knowledge", new_callable=AsyncMock) as search,
        patch("app.guards.context_builder.search_knowledge", new_callable=AsyncMock) as ctx_search,
    ):
        search.return_value = []
        ctx_search.return_value = []
        yield search
