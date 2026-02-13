"""Shared test fixtures."""
import pytest
from pathlib import Path
from shopping_tool.profile.schema import UserProfile, ShippingAddress, PaymentMethod


@pytest.fixture
def sample_shipping():
    return ShippingAddress(
        full_name="Jane Doe",
        street="123 Main Street",
        apt="Apt 4B",
        city="San Francisco",
        state="CA",
        zip_code="94102",
        phone="415-555-0100",
    )


@pytest.fixture
def sample_payment():
    return PaymentMethod(
        card_type="visa",
        card_number="4111111111111234",
        expiry_month=12,
        expiry_year=2027,
        cvv="123",
    )


@pytest.fixture
def sample_profile(sample_shipping, sample_payment):
    return UserProfile(
        email="jane.doe@example.com",
        shipping=sample_shipping,
        payment=sample_payment,
    )


@pytest.fixture
def tmp_profile_dir(tmp_path):
    """Temporary directory for profile storage during tests."""
    return tmp_path / "profile"
