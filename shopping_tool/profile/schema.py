"""Pydantic models for user profile data."""
from pydantic import BaseModel


class ShippingAddress(BaseModel):
    """Shipping address fields."""
    full_name: str
    street: str
    apt: str = ""
    city: str
    state: str
    zip_code: str
    country: str = "United States"
    phone: str


class PaymentMethod(BaseModel):
    """Payment card info — stored encrypted, never exposed to LLM."""
    card_type: str  # visa, mastercard, amex, discover
    card_number: str
    expiry_month: int
    expiry_year: int
    cvv: str
    billing_same_as_shipping: bool = True
    billing_address: ShippingAddress | None = None


class UserProfile(BaseModel):
    """Complete user profile for checkout form filling."""
    email: str
    shipping: ShippingAddress
    payment: PaymentMethod
