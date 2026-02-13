"""Tests for output sanitizer — PII and credential redaction."""
from shopping_tool.output_sanitizer import sanitize_output, redact_card_number, redact_email


class TestCardRedaction:
    def test_redact_full_card_number(self):
        assert redact_card_number("4111111111111234") == "****-****-****-1234"

    def test_redact_card_with_spaces(self):
        assert redact_card_number("4111 1111 1111 1234") == "****-****-****-1234"

    def test_redact_card_with_dashes(self):
        assert redact_card_number("4111-1111-1111-1234") == "****-****-****-1234"

    def test_short_number_returns_stars(self):
        assert redact_card_number("123") == "****"


class TestEmailRedaction:
    def test_redact_email(self):
        result = redact_email("jane.doe@example.com")
        assert result == "j***@example.com"

    def test_no_at_sign(self):
        assert redact_email("not-an-email") == "not-an-email"


class TestSanitizeOutput:
    def test_redacts_card_numbers(self):
        text = "Your card 4111 1111 1111 1234 was charged."
        result = sanitize_output(text)
        assert "1111 1111" not in result
        assert "[CARD REDACTED]" in result

    def test_redacts_api_keys(self):
        text = "api_key=sk-abc123xyz789012345678901"
        result = sanitize_output(text)
        assert "sk-abc" not in result
        assert "[REDACTED]" in result

    def test_redacts_github_tokens(self):
        text = "token: ghp_abcdefghijklmnopqrstuvwxyz1234567890"
        result = sanitize_output(text)
        assert "ghp_" not in result

    def test_redacts_aws_keys(self):
        text = "key: AKIAIOSFODNN7EXAMPLE"
        result = sanitize_output(text)
        assert "AKIA" not in result

    def test_redacts_ssn(self):
        text = "SSN: 123-45-6789"
        result = sanitize_output(text)
        assert "123-45-6789" not in result
        assert "[SSN REDACTED]" in result

    def test_strips_ansi(self):
        text = "\x1b[31mred text\x1b[0m normal"
        result = sanitize_output(text)
        assert "\x1b" not in result
        assert "red text normal" in result

    def test_truncates_long_output(self):
        text = "x" * 60000
        result = sanitize_output(text, max_chars=1000)
        assert len(result) < 1100
        assert "truncated" in result

    def test_passes_clean_text(self):
        text = "Product: Wireless Mouse, Price: $29.99, Rating: 4.5/5"
        result = sanitize_output(text)
        assert result == text
