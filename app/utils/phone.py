import re


def normalize_phone(raw: str) -> str:
    """Normalize a Brazilian phone number to E.164 format (e.g. +5518996386912)."""
    digits = re.sub(r"\D", "", raw)

    # Already has country code
    if digits.startswith("55") and len(digits) >= 12:
        return f"+{digits}"

    # Has DDD + number (11 digits)
    if len(digits) == 11:
        return f"+55{digits}"

    # Has DDD + number without 9 prefix (10 digits, landline or old mobile)
    if len(digits) == 10:
        return f"+55{digits}"

    # Just the number without DDD — can't normalize reliably
    return f"+{digits}" if digits else raw


def format_phone_display(phone: str) -> str:
    """Format phone for display: +55 (18) 99638-6912."""
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 13 and digits.startswith("55"):
        return f"+{digits[:2]} ({digits[2:4]}) {digits[4:9]}-{digits[9:]}"
    if len(digits) == 12 and digits.startswith("55"):
        return f"+{digits[:2]} ({digits[2:4]}) {digits[4:8]}-{digits[8:]}"
    return phone
