"""Extract campaign/ad context from Chatwoot webhook payloads.

Detects three scenarios:
1. Click-to-WhatsApp Ads (CTWA) — Meta referral data in conversation attributes
2. Template responses — reply to a previously sent WhatsApp template
3. Campaign labels — Chatwoot labels starting with "campanha_" or "campaign_"
"""

from __future__ import annotations

from datetime import datetime, timezone


def extract_campaign_context(payload: dict) -> dict | None:
    """Extract campaign/ad context from a Chatwoot webhook payload.

    Returns a dict with campaign context or None if no campaign detected.
    """
    conversation = payload.get("conversation") or {}

    # ── Scenario 1: Click-to-WhatsApp Ad (referral) ────────────────
    # Meta sends referral data when a user clicks a CTWA ad
    # Chatwoot stores it in conversation.additional_attributes or content_attributes
    additional = conversation.get("additional_attributes") or {}
    referral = additional.get("referral") or {}

    # Also check message-level content_attributes
    if not referral:
        msg_attrs = payload.get("content_attributes") or {}
        referral = msg_attrs.get("referral") or {}

    # Also check custom_attributes on conversation
    if not referral:
        custom = conversation.get("custom_attributes") or {}
        referral = custom.get("referral") or {}

    if referral and referral.get("source_type") == "ad":
        return {
            "type": "ctwa_ad",
            "headline": referral.get("headline", ""),
            "body": referral.get("body", ""),
            "source_url": referral.get("source_url", ""),
            "ad_id": referral.get("source_id", ""),
            "media_url": referral.get("media_url", ""),
            "received_at": datetime.now(timezone.utc).isoformat(),
        }

    # ── Scenario 2: Template response (in_reply_to) ────────────────
    # When a contact replies to a template message, Chatwoot may include
    # in_reply_to referencing the original template message
    msg_attrs = payload.get("content_attributes") or {}
    in_reply_to = msg_attrs.get("in_reply_to")

    if in_reply_to:
        return {
            "type": "template_response",
            "original_message_id": str(in_reply_to),
            "received_at": datetime.now(timezone.utc).isoformat(),
        }

    # ── Scenario 3: Campaign labels ────────────────────────────────
    labels = conversation.get("labels") or []
    campaign_labels = [
        lbl for lbl in labels
        if isinstance(lbl, str) and (
            lbl.startswith("campanha_") or lbl.startswith("campaign_")
        )
    ]

    if campaign_labels:
        return {
            "type": "campaign_label",
            "labels": campaign_labels,
            "received_at": datetime.now(timezone.utc).isoformat(),
        }

    return None
