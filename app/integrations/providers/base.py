from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable


@dataclass
class CompletionResult:
    """Provider-agnostic result of a single LLM completion.

    `text` is the concatenated text output. `input_tokens`/`output_tokens` are
    the usage as reported by the provider — always populated, so call sites that
    today discard usage (extraction, intent/sentiment classification) still have
    the data available downstream without an extra round-trip.
    """

    text: str
    input_tokens: int
    output_tokens: int


@runtime_checkable
class LLMProvider(Protocol):
    """Minimal interface every LLM provider must implement.

    Keeps the runtime decoupled from any specific vendor SDK. `system` is
    optional — pass ``None`` to send no system prompt, matching the bare-prompt
    extraction calls that omit it today.
    """

    def complete(
        self,
        *,
        messages: list,
        model: str,
        max_tokens: int,
        temperature: float,
        system: Optional[str] = None,
        timeout: float = 60.0,
    ) -> CompletionResult: ...
