"""Sentiment analysis for lead messages.

Uses keyword detection first (zero cost), falls back to Haiku only
for ambiguous messages with mixed signals.
"""
from __future__ import annotations

import re
from typing import Optional

from app.utils.logger import get_logger

log = get_logger("sentiment")

# ── Keyword dictionaries ────────────────────────────────────────────

NEGATIVE_KEYWORDS = [
    "não quero", "nao quero", "para de", "chato", "irritante", "demora",
    "lento", "caro", "absurdo", "péssimo", "pessimo", "horrível", "horrivel",
    "cancelar", "parar", "sair", "desisto", "esquece", "não preciso",
    "nao preciso", "sem interesse", "não tenho interesse", "nao tenho interesse",
    "tá caro", "ta caro", "muito caro", "não vale", "nao vale",
]

FRUSTRATED_KEYWORDS = [
    "já falei", "ja falei", "de novo", "não entendeu", "nao entendeu",
    "que saco", "inferno", "droga", "pqp", "vsf", "merda", "porra",
    "cansei", "que demora", "toda hora", "de novo isso", "pelo amor",
    "não acredito", "nao acredito", "ridículo", "ridiculo",
]

URGENT_KEYWORDS = [
    "urgente", "urgência", "urgencia", "pressa", "ontem", "agora",
    "imediato", "rápido", "rapido", "correndo", "preciso já",
    "preciso ja", "não posso esperar", "nao posso esperar",
    "o mais rápido", "o mais rapido", "pra ontem", "emergência",
    "emergencia",
]

POSITIVE_KEYWORDS = [
    "adorei", "perfeito", "maravilha", "excelente", "top", "massa",
    "show", "incrível", "incrivel", "amei", "sensacional", "fantástico",
    "fantastico", "muito bom", "ótimo", "otimo", "que legal", "demais",
    "gostei", "curti", "quero sim", "com certeza", "fechado", "bora",
    "vamos", "animado", "empolgado", "interessante",
]

# Tone adjustments per sentiment
_TONE_ADJUSTMENTS = {
    "positive": (
        "O lead está animado e engajado. Acompanhe a energia positiva, "
        "seja entusiasmada e aproveite o momento para avançar na conversa."
    ),
    "negative": (
        "O lead está desinteressado ou cético. Seja empática, não insista, "
        "tente entender a objeção e ofereça valor sem pressionar."
    ),
    "frustrated": (
        "O lead está frustrado ou irritado. Seja MUITO empática e direta, "
        "peça desculpas se necessário, resolva o problema rapidamente. "
        "Mensagens curtas e objetivas. NÃO faça perguntas desnecessárias."
    ),
    "urgent": (
        "O lead tem pressa. Seja direta, objetiva, sem rodeios. "
        "Vá direto ao ponto e ofereça a solução mais rápida possível."
    ),
    "neutral": "",
}


# ── Public API ──────────────────────────────────────────────────────


async def analyze_sentiment(message: str) -> dict:
    """Analyze lead message sentiment using keyword detection.

    Falls back to Haiku only when mixed keywords are detected.

    Returns:
        {
            "sentiment": "positive" | "neutral" | "negative" | "frustrated" | "urgent",
            "confidence": 0.0 to 1.0,
            "tone_adjustment": "instruction string for Aurora"
        }
    """
    if not message or not message.strip():
        return _result("neutral", 1.0)

    text = message.lower().strip()

    # Count matches in each category
    scores = {
        "frustrated": _count_matches(text, FRUSTRATED_KEYWORDS),
        "urgent": _count_matches(text, URGENT_KEYWORDS),
        "negative": _count_matches(text, NEGATIVE_KEYWORDS),
        "positive": _count_matches(text, POSITIVE_KEYWORDS),
    }

    # Frustrated takes priority (most sensitive)
    if scores["frustrated"] > 0:
        return _result("frustrated", min(0.7 + scores["frustrated"] * 0.1, 1.0))

    # Urgent next
    if scores["urgent"] > 0:
        return _result("urgent", min(0.7 + scores["urgent"] * 0.1, 1.0))

    # Check for mixed signals (positive + negative) → use Haiku
    if scores["positive"] > 0 and scores["negative"] > 0:
        return await _haiku_analyze(message)

    # Clear negative
    if scores["negative"] > 0:
        return _result("negative", min(0.7 + scores["negative"] * 0.1, 1.0))

    # Clear positive
    if scores["positive"] > 0:
        return _result("positive", min(0.7 + scores["positive"] * 0.1, 1.0))

    # No keywords matched → neutral (no Haiku call needed)
    return _result("neutral", 0.9)


def format_sentiment_for_prompt(sentiment_data: dict) -> str:
    """Format sentiment analysis as a prompt section.

    Returns empty string for neutral sentiment (no adjustment needed).
    """
    sentiment = sentiment_data.get("sentiment", "neutral")
    if sentiment == "neutral":
        return ""

    tone = sentiment_data.get("tone_adjustment", "")
    if not tone:
        return ""

    labels = {
        "positive": "POSITIVO/ANIMADO",
        "negative": "NEGATIVO/CÉTICO",
        "frustrated": "FRUSTRADO/IRRITADO",
        "urgent": "URGENTE/COM PRESSA",
    }
    label = labels.get(sentiment, sentiment.upper())

    return (
        f"\n\n## SENTIMENTO DETECTADO: {label}\n"
        f"{tone}"
    )


# ── Internals ───────────────────────────────────────────────────────


def _count_matches(text: str, keywords: list[str]) -> int:
    """Count how many keywords appear in the text."""
    return sum(1 for kw in keywords if kw in text)


def _result(sentiment: str, confidence: float) -> dict:
    """Build a standard result dict."""
    return {
        "sentiment": sentiment,
        "confidence": round(confidence, 2),
        "tone_adjustment": _TONE_ADJUSTMENTS.get(sentiment, ""),
    }


async def _haiku_analyze(message: str) -> dict:
    """Fallback: use Haiku for ambiguous messages with mixed signals."""
    from app.integrations.claude_client import generate_extraction

    prompt = (
        "Analise o sentimento desta mensagem de um lead conversando com uma SDR "
        "pelo WhatsApp. Responda APENAS em JSON:\n"
        '{"sentiment": "positive|neutral|negative|frustrated|urgent", '
        '"confidence": 0.0 a 1.0, '
        '"tone_adjustment": "instrução curta de como ajustar o tom"}\n\n'
        "Regras:\n"
        "- positive: animado, interessado, engajado\n"
        "- neutral: respondendo normalmente sem emoção forte\n"
        "- negative: desinteressado, cético\n"
        "- frustrated: irritado, impaciente\n"
        "- urgent: com pressa, precisa resolver rápido\n\n"
        f"Mensagem: {message}"
    )

    try:
        raw, _ = await generate_extraction(prompt, max_tokens=150)

        import json
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            import re
            match = re.search(r"\{[\s\S]*\}", raw)
            if match:
                data = json.loads(match.group())
            else:
                log.warning("[SENTIMENT] Could not parse Haiku response, defaulting to neutral")
                return _result("neutral", 0.5)

        sentiment = data.get("sentiment", "neutral")
        valid = {"positive", "neutral", "negative", "frustrated", "urgent"}
        if sentiment not in valid:
            sentiment = "neutral"

        confidence = float(data.get("confidence", 0.7))
        tone = data.get("tone_adjustment", _TONE_ADJUSTMENTS.get(sentiment, ""))

        log.info("[SENTIMENT:HAIKU] Classified as %s (%.2f) for: %s", sentiment, confidence, message[:80])
        return {
            "sentiment": sentiment,
            "confidence": round(confidence, 2),
            "tone_adjustment": tone,
        }

    except Exception as exc:
        log.warning("[SENTIMENT:HAIKU] Failed (%s), defaulting to neutral", exc)
        return _result("neutral", 0.5)
