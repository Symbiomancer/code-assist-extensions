"""Output sanitization — redact PII, credit cards, and credentials before returning to LLM."""
import re

# Credential patterns (from email-agent)
_CREDENTIAL_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*[=:]\s*\S+"),
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),      # OpenAI/Stripe keys
    re.compile(r"ghp_[a-zA-Z0-9]{36}"),       # GitHub tokens
    re.compile(r"AKIA[A-Z0-9]{16}"),          # AWS keys
]

# Credit card number patterns (13-19 digits, optionally separated)
_CARD_NUMBER_PATTERN = re.compile(
    r"\b(?:\d{4}[-\s]?){2,4}\d{1,4}\b"
)

# SSN pattern
_SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

# ANSI escape codes
_ANSI_PATTERN = re.compile(r"\x1b\[[0-9;]*m")


def redact_card_number(number: str) -> str:
    """Mask a card number to show only last 4 digits."""
    digits = re.sub(r"\D", "", number)
    if len(digits) < 4:
        return "****"
    return f"****-****-****-{digits[-4:]}"


def redact_email(email: str) -> str:
    """Partially redact an email address."""
    if "@" not in email:
        return email
    local, domain = email.split("@", 1)
    return f"{local[0]}***@{domain}"


def sanitize_output(text: str, max_chars: int = 50000) -> str:
    """
    Sanitize text before returning to the LLM.

    - Strips ANSI escape codes
    - Redacts credential patterns
    - Redacts credit card numbers
    - Redacts SSNs
    - Truncates to max_chars
    """
    # Strip ANSI
    text = _ANSI_PATTERN.sub("", text)

    # Redact credentials
    for pattern in _CREDENTIAL_PATTERNS:
        text = pattern.sub("[REDACTED]", text)

    # Redact credit card numbers
    text = _CARD_NUMBER_PATTERN.sub("[CARD REDACTED]", text)

    # Redact SSNs
    text = _SSN_PATTERN.sub("[SSN REDACTED]", text)

    # Truncate
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n[... truncated at {max_chars} chars]"

    return text
