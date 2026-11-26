"""Validate channel identifiers before configuring tenant routing."""

import pytest
from pydantic import ValidationError

from app.schemas.tenant import WhatsAppConfig


@pytest.mark.parametrize("value", ["", "abc", "123 456", "１２３", "1" * 33])
def test_whatsapp_phone_identifier_must_be_ascii_digits(value):
    with pytest.raises(ValidationError):
        WhatsAppConfig(phone_number_id=value, access_token="token", verify_token="verify")


def test_whatsapp_phone_identifier_is_normalized():
    value = WhatsAppConfig(phone_number_id=" 12345 ", access_token="token", verify_token="verify")
    assert value.phone_number_id == "12345"
