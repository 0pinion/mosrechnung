from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


CENT = Decimal("0.01")


def text_to_cents(value: str) -> int:
    normalized = value.strip().replace("€", "").replace(" ", "")
    if not normalized:
        raise ValueError("Bitte einen Preis eingeben.")
    if "," in normalized and "." in normalized:
        if normalized.rfind(",") > normalized.rfind("."):
            normalized = normalized.replace(".", "").replace(",", ".")
        else:
            normalized = normalized.replace(",", "")
    else:
        normalized = normalized.replace(",", ".")
    try:
        amount = Decimal(normalized).quantize(CENT, rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValueError("Der Preis ist ungültig.") from exc
    if amount < 0:
        raise ValueError("Der Preis darf nicht negativ sein.")
    return int(amount * 100)


def cents_to_text(cents: int, currency: bool = False) -> str:
    value = Decimal(cents) / 100
    text = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{text} €" if currency else text

