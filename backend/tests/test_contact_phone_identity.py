import pytest

from app.services.contact.phone_identity import phone_variants


@pytest.mark.parametrize("value", ["212600000001", "+212600000001"])
def test_international_identifiers_have_same_two_spellings(value):
    assert phone_variants(value) == ("212600000001", "+212600000001")


@pytest.mark.parametrize("value", ["web_abcd", "0612345678", "+", "++212600000001", "٢١٢٦٠٠٠٠٠٠٠١", "+212 600000001"])
def test_other_values_are_not_reinterpreted(value):
    assert phone_variants(value) == (value,)
