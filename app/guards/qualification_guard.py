"""
Guard de qualificação programático.

Detecta saudações genéricas pra impedir que Aurora suba leads pra `02-qualificacao`
em primeira mensagem sem sinal de intenção real.

Não substitui o prompt — atua como camada de defesa programática quando o prompt
não é suficiente.
"""
import re
from typing import Final

# Saudações genéricas que NÃO sinalizam intenção qualificada.
# Cada padrão tenta cobrir variações comuns em PT-BR.
_GREETING_PATTERNS: Final[list[str]] = [
    r"^\s*(ol[áa]|oi+|opa|e\s+a[íi]|hey|hi|hello)\s*[!?.\s]*$",
    r"^\s*(bom\s+dia|boa\s+tarde|boa\s+noite|bom\s+dia[!.\s]*)\s*[!?.\s]*$",
    r"^\s*(tudo\s+(bem|bom|certo|tranquilo|tranquilo[?]))\s*[!?.\s]*$",
    r"^\s*(td\s+bem|tb|blz|beleza)\s*[!?.\s]*$",
    r"^\s*(como\s+(vai|tá|esta))\s*[!?.\s]*$",
    # Emojis sozinhos (smileys, hands, hearts mais comuns)
    r"^\s*[\U0001F600-\U0001F64F\u2764\u2728\U0001F44B\U0001F44C\s]+\s*$",
]

# Limite de comprimento — saudação genérica não passa de 40 caracteres.
# "Olá tudo bem? como vc tá?" tem 27 caracteres.
# "Oi, quero saber sobre tráfego pago" tem 34 caracteres mas tem sinal.
# 40 dá margem segura sem deixar passar mensagens com conteúdo real.
_GREETING_MAX_LEN: Final[int] = 40


def is_generic_greeting(message: str) -> bool:
    """
    Retorna True se a mensagem for APENAS saudação genérica
    (sem sinal de qualificação ou intenção comercial).

    Mensagens debounceadas separadas por '\\n' são tratadas como
    sequência: cada linha precisa ser saudação OU vazia pra retornar True.

    Args:
        message: texto da mensagem (combinado pelo debounce, pode ter \\n).

    Returns:
        True se é saudação genérica pura, False caso contrário.

    Exemplos True (saudação pura):
        - "Olá"
        - "Oi tudo bem?"
        - "Bom dia"
        - "👋"
        - "Opa\\ntudo bem?" (debounce de 2 mensagens)

    Exemplos False (tem sinal):
        - "Olá, queria saber sobre tráfego pago"
        - "preciso de ajuda urgente"
        - "vcs atendem clinica?"
        - "" (vazio)
    """
    if not message or not message.strip():
        return False

    msg_clean = message.strip().lower()

    # Mensagem longa nunca é saudação pura
    if len(msg_clean) > _GREETING_MAX_LEN:
        return False

    # Tratar mensagens combinadas (debounce concatena com \n)
    # Cada linha precisa ser saudação. Se alguma não bate, retorna False.
    lines = [line.strip() for line in msg_clean.split("\n") if line.strip()]
    if not lines:
        return False

    for line in lines:
        if not any(re.match(pattern, line, re.IGNORECASE) for pattern in _GREETING_PATTERNS):
            return False

    return True