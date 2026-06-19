from __future__ import annotations

from typing import Optional

import anthropic

from app.integrations.providers.base import CompletionResult
from app.utils.logger import get_logger

log = get_logger("claude")


class AnthropicProvider:
    """LLMProvider backed by the Anthropic SDK.

    Owns the lazily-initialized SDK client (one per process) and encapsulates
    the ``messages.create`` call, the text-block extraction, and the usage count
    that previously lived inline in ``claude_client.py``. Behavior is unchanged —
    same model strings, params, and return data — only the location moved.
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._client: Optional[anthropic.Anthropic] = None

    def _get_client(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = anthropic.Anthropic(api_key=self._api_key)
            log.info("Claude client initialized")
        return self._client

    def complete(
        self,
        *,
        messages: list,
        model: str,
        max_tokens: int,
        temperature: float,
        system: Optional[str] = None,
        timeout: float = 60.0,
    ) -> CompletionResult:
        client = self._get_client()

        # Omit `system` entirely when not provided — sending system="" is not
        # the same request as not sending it at all.
        kwargs = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
            "timeout": timeout,
        }
        if system is not None:
            kwargs["system"] = system

        try:
            response = client.messages.create(**kwargs)
        except anthropic.APITimeoutError:
            log.error(
                "[CLAUDE] API timeout after 60s — re-raising for upstream handling"
            )
            raise

        # Extract and concatenate all text blocks, ignore tool_use/thinking/etc
        text_blocks = []
        for block in response.content:
            if hasattr(block, "text") and block.text and block.text.strip():
                text_blocks.append(block.text)
        text = "\n\n".join(text_blocks).strip()

        # Diagnostic logging for tool_use-only responses
        if not text and response.usage.output_tokens > 0:
            log.warning(
                "[CLAUDE:NO_TEXT_BLOCK] Response had %d output tokens but no text block. "
                "Likely tool_use-only response. Block types: %s",
                response.usage.output_tokens,
                [getattr(b, "type", type(b).__name__) for b in response.content],
            )

        return CompletionResult(
            text=text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
