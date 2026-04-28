"""
Parser de Meta Lead Ads vindos via Chatwoot.

Quando um lead preenche um formulário Meta Lead Ad e a integração
entrega no Chatwoot, o sender vira "John Doe" (placeholder) e os
dados reais ficam no content da mensagem como texto formatado:

    Pergunta 1: Resposta 1
    Full name: Nome Real
    Phone number: (XX) XXXXX-XXXX
    City: Cidade
    Pergunta 2: Resposta 2
    ...

Este módulo extrai esses dados pra que possam ser usados para
atualizar o contato com informação real.
"""
from __future__ import annotations

import re
from typing import Optional

# Heurística de detecção: precisa ter PELO MENOS 2 destes campos
# pra considerar que é um Lead Ad do Meta
_REQUIRED_MARKERS = ("Full name:", "Phone number:")


def parse_meta_lead_ad(content: str) -> Optional[dict]:
    """
    Parse Meta Lead Ad form data from message content.

    Args:
        content: Texto da mensagem do Chatwoot (payload.content)

    Returns:
        dict com chaves: name, phone, email, city, custom_attributes
        ou None se não for detectado como Lead Ad

    Example:
        >>> content = '''Etapa: Cria
        ... Full name: Jose Vieira dos Santos
        ... Phone number: (38) 9996-7762
        ... City: Brasília de Minas'''
        >>> result = parse_meta_lead_ad(content)
        >>> result["name"]
        'Jose Vieira dos Santos'
        >>> result["phone"]
        '(38) 9996-7762'
    """
    if not content or not isinstance(content, str):
        return None

    # Heurística: precisa ter pelo menos 2 marcadores típicos (case-insensitive)
    content_lower = content.lower()
    markers_found = sum(1 for m in _REQUIRED_MARKERS if m.lower() in content_lower)
    if markers_found < 2:
        return None

    parsed = {
        "name": "",
        "phone": "",
        "email": "",
        "city": "",
        "custom_attributes": {},
    }

    for raw_line in content.split("\n"):
        line = raw_line.strip()
        if not line or ":" not in line:
            continue

        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()

        if not key or not value:
            continue

        key_lower = key.lower()

        if key_lower == "full name":
            parsed["name"] = value
        elif key_lower in ("phone number", "phone", "telefone"):
            parsed["phone"] = value
        elif key_lower in ("email", "e-mail"):
            parsed["email"] = value
        elif key_lower == "city":
            parsed["city"] = value
        else:
            # Custom attributes (perguntas customizadas do form)
            parsed["custom_attributes"][key] = value

    # Só retorna se conseguiu extrair pelo menos o nome
    if not parsed["name"]:
        return None

    return parsed


def is_likely_meta_lead_ad(content: str, sender_name: str = "") -> bool:
    """
    Verifica rapidamente se a mensagem parece ser de um Meta Lead Ad.

    Args:
        content: Texto da mensagem
        sender_name: Nome do sender (geralmente "John Doe" pra leads)

    Returns:
        True se parecer Lead Ad, False caso contrário
    """
    if not content:
        return False

    # Sender genérico é forte indício
    generic_senders = {"john doe", "lead", "facebook lead", ""}
    sender_is_generic = (sender_name or "").strip().lower() in generic_senders

    # Marcadores no content são essenciais
    has_markers = sum(1 for m in _REQUIRED_MARKERS if m in content) >= 2

    return sender_is_generic and has_markers