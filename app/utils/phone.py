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


def extract_phone_number(text: str) -> str | None:
    """Extract a Brazilian phone number from free-form text.

    Handles formats like:
      (18) 99659-7391, 18996597391, +55 18 99659-7391,
      18 99659-7391, 55 18 996597391, etc.

    Returns digits in 55XXXXXXXXXXX format or None.
    """
    patterns = [
        # +55 (18) 99659-7391  or  55 18 99659-7391
        r"\+?55[\s.-]?\(?(\d{2})\)?[\s.-]?(\d{4,5})[\s.-]?(\d{4})",
        # (18) 99659-7391  or  18 99659-7391
        r"\(?(\d{2})\)?[\s.-]?(\d{4,5})[\s.-]?(\d{4})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            groups = match.groups()
            digits = "".join(groups)
            if len(digits) < 10 or len(digits) > 11:
                continue
            # Normalize to 55 + DDD + number
            return f"55{digits}" if not digits.startswith("55") else digits
    return None


def format_phone_display(phone: str) -> str:
    """Format phone for display: +55 (18) 99638-6912."""
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 13 and digits.startswith("55"):
        return f"+{digits[:2]} ({digits[2:4]}) {digits[4:9]}-{digits[9:]}"
    if len(digits) == 12 and digits.startswith("55"):
        return f"+{digits[:2]} ({digits[2:4]}) {digits[4:8]}-{digits[8:]}"
    return phone
