"""Profile manager — load, save, and redact user data."""
import logging
from pathlib import Path

from .crypto import ProfileCrypto
from .schema import UserProfile

logger = logging.getLogger(__name__)

# Default profile storage location
DEFAULT_PROFILE_PATH = Path.home() / ".config" / "shopping-assistant" / "profile.enc"


class ProfileManager:
    """Manages encrypted user profile. Never exposes raw PII to LLM output."""

    def __init__(self, profile_path: Path | None = None):
        self._path = profile_path or DEFAULT_PROFILE_PATH
        self._crypto = ProfileCrypto()
        self._cached: UserProfile | None = None

    def exists(self) -> bool:
        """Check if a profile exists on disk."""
        return self._path.exists()

    def save(self, profile: UserProfile) -> None:
        """Encrypt and save profile to disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        encrypted = self._crypto.encrypt(profile.model_dump())
        self._path.write_bytes(encrypted)
        self._cached = profile
        logger.info("Profile saved to %s", self._path)

    def load(self) -> UserProfile:
        """Load and decrypt profile from disk."""
        if self._cached:
            return self._cached
        if not self._path.exists():
            raise FileNotFoundError("No profile found. Use setup_profile to create one.")
        encrypted = self._path.read_bytes()
        data = self._crypto.decrypt(encrypted)
        self._cached = UserProfile(**data)
        return self._cached

    def get_redacted_summary(self) -> dict:
        """Return a summary safe for LLM output — no raw PII."""
        profile = self.load()
        name_parts = profile.shipping.full_name.split()
        redacted_name = f"{name_parts[0]} {name_parts[-1][0]}." if len(name_parts) > 1 else name_parts[0]

        return {
            "email": profile.email[0] + "***@" + profile.email.split("@")[1],
            "shipping": {
                "name": redacted_name,
                "city": profile.shipping.city,
                "state": profile.shipping.state,
                "zip": profile.shipping.zip_code[:3] + "**",
            },
            "payment": {
                "type": profile.payment.card_type.title(),
                "last_four": profile.payment.card_number[-4:],
            },
        }

    def get_shipping_for_form(self) -> dict:
        """Full shipping data for internal form-filling only. Never return to LLM."""
        profile = self.load()
        return profile.shipping.model_dump()

    def get_payment_for_form(self) -> dict:
        """Full payment data for internal form-filling only. Never return to LLM."""
        profile = self.load()
        return profile.payment.model_dump()

    def clear_cache(self) -> None:
        """Clear cached profile (for testing)."""
        self._cached = None
