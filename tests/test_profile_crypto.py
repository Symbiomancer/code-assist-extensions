"""Tests for profile encryption and management."""
import pytest
from pathlib import Path

from shopping_tool.profile.crypto import ProfileCrypto
from shopping_tool.profile.manager import ProfileManager
from shopping_tool.profile.schema import UserProfile, ShippingAddress, PaymentMethod


class TestProfileCrypto:
    def test_encrypt_decrypt_roundtrip(self, tmp_path):
        crypto = ProfileCrypto(key_path=tmp_path / "test.key")
        data = {"name": "Jane", "card": "4111111111111234"}
        encrypted = crypto.encrypt(data)
        assert encrypted != data
        decrypted = crypto.decrypt(encrypted)
        assert decrypted == data

    def test_key_created_on_first_use(self, tmp_path):
        key_path = tmp_path / "test.key"
        assert not key_path.exists()
        crypto = ProfileCrypto(key_path=key_path)
        crypto.encrypt({"test": True})
        assert key_path.exists()

    def test_key_reused_across_calls(self, tmp_path):
        key_path = tmp_path / "test.key"
        crypto = ProfileCrypto(key_path=key_path)
        encrypted = crypto.encrypt({"value": 42})
        # New instance, same key path
        crypto2 = ProfileCrypto(key_path=key_path)
        decrypted = crypto2.decrypt(encrypted)
        assert decrypted == {"value": 42}

    def test_tampered_data_raises(self, tmp_path):
        crypto = ProfileCrypto(key_path=tmp_path / "test.key")
        encrypted = crypto.encrypt({"secret": "data"})
        tampered = encrypted[:-5] + b"XXXXX"
        with pytest.raises(Exception):
            crypto.decrypt(tampered)


class TestProfileManager:
    def test_save_and_load(self, tmp_path, sample_profile):
        pm = ProfileManager(profile_path=tmp_path / "profile.enc")
        pm._crypto = ProfileCrypto(key_path=tmp_path / "test.key")
        pm.save(sample_profile)
        pm.clear_cache()
        loaded = pm.load()
        assert loaded.email == sample_profile.email
        assert loaded.shipping.full_name == sample_profile.shipping.full_name
        assert loaded.payment.card_number == sample_profile.payment.card_number

    def test_exists_false_when_no_file(self, tmp_path):
        pm = ProfileManager(profile_path=tmp_path / "nope.enc")
        assert not pm.exists()

    def test_exists_true_after_save(self, tmp_path, sample_profile):
        pm = ProfileManager(profile_path=tmp_path / "profile.enc")
        pm._crypto = ProfileCrypto(key_path=tmp_path / "test.key")
        pm.save(sample_profile)
        assert pm.exists()

    def test_load_without_file_raises(self, tmp_path):
        pm = ProfileManager(profile_path=tmp_path / "nope.enc")
        with pytest.raises(FileNotFoundError):
            pm.load()

    def test_redacted_summary_hides_pii(self, tmp_path, sample_profile):
        pm = ProfileManager(profile_path=tmp_path / "profile.enc")
        pm._crypto = ProfileCrypto(key_path=tmp_path / "test.key")
        pm.save(sample_profile)

        summary = pm.get_redacted_summary()

        # Card number hidden
        assert summary["payment"]["last_four"] == "1234"
        assert "4111" not in str(summary)

        # Email partially hidden
        assert "jane.doe@" not in summary["email"]
        assert "example.com" in summary["email"]

        # Name partially hidden
        assert "Doe" not in str(summary["shipping"]["name"])
        assert summary["shipping"]["name"] == "Jane D."

        # Zip partially hidden
        assert summary["shipping"]["zip"] == "941**"

    def test_encrypted_on_disk(self, tmp_path, sample_profile):
        profile_path = tmp_path / "profile.enc"
        pm = ProfileManager(profile_path=profile_path)
        pm._crypto = ProfileCrypto(key_path=tmp_path / "test.key")
        pm.save(sample_profile)

        raw_bytes = profile_path.read_bytes()
        raw_str = raw_bytes.decode("utf-8", errors="ignore")
        # None of the plaintext PII should appear in the encrypted file
        assert "jane.doe@example.com" not in raw_str
        assert "4111111111111234" not in raw_str
        assert "123 Main Street" not in raw_str
