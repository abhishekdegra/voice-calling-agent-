"""Tests for phone normalization and order ownership verification."""

from app.utils.security import normalize_indian_phone_number, is_valid_phone_number, verify_order_ownership


def test_normalize_indian_phone():
    assert normalize_indian_phone_number("9876543210") == "919876543210"
    assert normalize_indian_phone_number("09876543210") == "919876543210"
    assert normalize_indian_phone_number("+91 9876543210") == "919876543210"
    assert normalize_indian_phone_number("919876543210") == "919876543210"


def test_is_valid_phone_number():
    assert is_valid_phone_number("9876543210") is True
    assert is_valid_phone_number("8123456789") is True
    assert is_valid_phone_number("12345") is False
    assert is_valid_phone_number("abcdef") is False


def test_verify_order_ownership():
    # Direct match on user_id in order details
    assert verify_order_ownership(
        requested_order_id="101",
        user_id=1,
        order_data={"id": "101", "user_id": 1}
    ) is True

    # User mismatch
    assert verify_order_ownership(
        requested_order_id="101",
        user_id=2,
        order_data={"id": "101", "user_id": 1}
    ) is False

    # Match in user's order history
    history = [
        {"id": "50", "grand_total": 500},
        {"id": "51", "grand_total": 800}
    ]
    assert verify_order_ownership("51", user_id=1, order_history=history) is True
    assert verify_order_ownership("99", user_id=1, order_history=history) is False
