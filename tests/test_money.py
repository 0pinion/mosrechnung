import pytest

from mosrechnung.money import cents_to_text, text_to_cents


@pytest.mark.parametrize(
    ("text", "cents"),
    [("12,50", 1250), ("12.50", 1250), ("1.234,56 €", 123456), ("0", 0)],
)
def test_text_to_cents(text, cents):
    assert text_to_cents(text) == cents


def test_money_rejects_invalid_and_negative_values():
    with pytest.raises(ValueError):
        text_to_cents("abc")
    with pytest.raises(ValueError):
        text_to_cents("-1,00")


def test_cents_to_german_text():
    assert cents_to_text(123456, True) == "1.234,56 €"

