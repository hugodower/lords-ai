"""
Sistema de tracking de status de resolução de nome de contatos.

Gerencia estados de resolução de nome:
- 'resolved': contato tem nome real
- 'pending_capture': contato é placeholder, precisa perguntar
- 'captured': nome foi capturado via conversa

Persistência via Supabase usando contact_memory ou tabela específica.
"""
from __future__ import annotations

from typing import Optional
from datetime import datetime, timezone

from app.integrations import supabase_client as sb
from app.integrations.chatwoot import chatwoot_client
from app.utils.logger import get_logger

log = get_logger("name_resolution")

# Status possíveis
NAME_RESOLUTION_STATUSES = {
    "resolved",     # Contato tem nome real
    "pending_capture",  # Contato é placeholder, precisa capturar
    "captured"      # Nome foi capturado via conversa
}


async def get_name_resolution_status(
    org_id: str,
    contact_phone: str = "",
    chatwoot_contact_id: str = ""
) -> str:
    """
    Obtém o status atual de resolução de nome para um contato.

    Args:
        org_id: ID da organização
        contact_phone: Telefone do contato
        chatwoot_contact_id: ID do contato no Chatwoot

    Returns:
        Status: 'resolved', 'pending_capture', ou 'captured'
        Default: 'resolved' se não encontrar registro
    """
    try:
        # Buscar pelo contact_memory usando phone ou chatwoot_contact_id
        phone_digits = contact_phone.replace("+", "").replace("-", "").replace(" ", "") if contact_phone else ""

        contact_memory = await sb.get_contact_memory(
            org_id=org_id,
            phone_digits=phone_digits,
            chatwoot_contact_id=chatwoot_contact_id
        )

        if contact_memory and contact_memory.get("metadata"):
            status = contact_memory["metadata"].get("name_resolution_status", "resolved")
            if status in NAME_RESOLUTION_STATUSES:
                return status

        # Default: resolved (contato normal)
        return "resolved"

    except Exception as exc:
        log.error("[NAME_RESOLUTION] Error getting status: %s", exc)
        return "resolved"


async def set_name_resolution_status(
    org_id: str,
    status: str,
    contact_phone: str = "",
    chatwoot_contact_id: str = "",
    contact_name: str = ""
) -> bool:
    """
    Define o status de resolução de nome para um contato.

    Args:
        org_id: ID da organização
        status: Novo status ('resolved', 'pending_capture', 'captured')
        contact_phone: Telefone do contato
        chatwoot_contact_id: ID do contato no Chatwoot
        contact_name: Nome do contato (para logs)

    Returns:
        True se atualizado com sucesso, False caso contrário
    """
    if status not in NAME_RESOLUTION_STATUSES:
        log.error("[NAME_RESOLUTION] Invalid status: %s", status)
        return False

    try:
        phone_digits = contact_phone.replace("+", "").replace("-", "").replace(" ", "") if contact_phone else ""

        # Buscar contact_memory existente ou criar estrutura básica
        contact_memory = await sb.get_contact_memory(
            org_id=org_id,
            phone_digits=phone_digits,
            chatwoot_contact_id=chatwoot_contact_id
        )

        if not contact_memory:
            # Criar contact_memory básico se não existir
            contact_memory = {
                "contact_name": contact_name,
                "summary": "",
                "interests": [],
                "qualification_status": "cold",
                "metadata": {},
                "total_conversations": 0,
                "last_interaction_at": datetime.now(timezone.utc).isoformat()
            }

        # Atualizar metadata com novo status
        if "metadata" not in contact_memory:
            contact_memory["metadata"] = {}

        contact_memory["metadata"]["name_resolution_status"] = status
        contact_memory["metadata"]["name_resolution_updated_at"] = datetime.now(timezone.utc).isoformat()

        # Persistir via upsert_contact_memory
        await sb.upsert_contact_memory(
            org_id=org_id,
            phone_digits=phone_digits,
            data=contact_memory,
            chatwoot_contact_id=chatwoot_contact_id
        )

        log.info(
            "[NAME_RESOLUTION] Status updated: %s → %s (contact=%s)",
            contact_name or chatwoot_contact_id or phone_digits,
            status,
            contact_name
        )
        return True

    except Exception as exc:
        log.error("[NAME_RESOLUTION] Error setting status: %s", exc)
        return False


async def mark_as_pending_capture(
    org_id: str,
    contact_phone: str = "",
    chatwoot_contact_id: str = "",
    contact_name: str = ""
) -> bool:
    """
    Marca contato como precisando capturar nome.

    Usado quando detectamos contato placeholder (John Doe).
    """
    return await set_name_resolution_status(
        org_id=org_id,
        status="pending_capture",
        contact_phone=contact_phone,
        chatwoot_contact_id=chatwoot_contact_id,
        contact_name=contact_name
    )


async def mark_as_captured(
    org_id: str,
    captured_name: str,
    contact_phone: str = "",
    chatwoot_contact_id: str = ""
) -> bool:
    """
    Marca nome como capturado via conversa e atualiza Chatwoot.

    Args:
        org_id: ID da organização
        captured_name: Nome capturado na conversa
        contact_phone: Telefone do contato
        chatwoot_contact_id: ID do contato no Chatwoot

    Returns:
        True se processado com sucesso
    """
    try:
        # 1. Atualizar status interno
        await set_name_resolution_status(
            org_id=org_id,
            status="captured",
            contact_phone=contact_phone,
            chatwoot_contact_id=chatwoot_contact_id,
            contact_name=captured_name
        )

        # 2. Atualizar contato no Chatwoot se temos chatwoot_contact_id
        if chatwoot_contact_id:
            result = await chatwoot_client.update_contact(
                contact_id=int(chatwoot_contact_id),
                name=captured_name,
                org_id=org_id
            )

            if result and not result.get("error"):
                log.info(
                    "[NAME_RESOLUTION] Contact updated in Chatwoot: %s (id=%s)",
                    captured_name, chatwoot_contact_id
                )
            else:
                log.warning(
                    "[NAME_RESOLUTION] Failed to update Chatwoot contact: %s",
                    result.get("error") if result else "unknown error"
                )

        return True

    except Exception as exc:
        log.error("[NAME_RESOLUTION] Error marking as captured: %s", exc)
        return False


async def should_ask_for_name(
    org_id: str,
    contact_phone: str = "",
    chatwoot_contact_id: str = "",
    contact_name: str = ""
) -> bool:
    """
    Verifica se devemos perguntar o nome do contato.

    Returns:
        True se devemos perguntar o nome, False caso contrário
    """
    # Se já temos nome válido, não perguntar
    if contact_name and contact_name.strip().lower() not in {"john doe", "lead", "facebook lead", ""}:
        return False

    # Verificar status de resolução
    status = await get_name_resolution_status(
        org_id=org_id,
        contact_phone=contact_phone,
        chatwoot_contact_id=chatwoot_contact_id
    )

    # Perguntar apenas se status for pending_capture
    return status == "pending_capture"


def extract_name_from_message(message: str) -> Optional[str]:
    """
    Tenta extrair nome de mensagem do usuário.

    Heurística simples para detectar quando usuário responde com nome.

    Args:
        message: Mensagem do usuário

    Returns:
        Nome extraído ou None
    """
    import re

    message = message.strip()

    # Padrões comuns de resposta com nome
    patterns = [
        r"(?:me chamo|meu nome é|sou o|sou a|pode me chamar de)\s+([a-záéíóúâêîôûàèìòùçã\s]+)",
        r"^([a-záéíóúâêîôûàèìòùçã]+(?:\s+[a-záéíóúâêîôûàèìòùçã]+)*)\s*$",  # Nome sozinho
        r"(?:nome|chamo)\s*[:é]?\s*([a-záéíóúâêîôûàèìòùçã\s]+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            name = match.group(1).strip()
            # Validações básicas
            words = name.split()
            if (len(name) >= 2 and len(words) <= 5 and
                name.replace(" ", "").isalpha() and
                any(c.isupper() for c in name)):  # Pelo menos uma letra maiúscula (nomes típicos)
                return name.title()

    return None