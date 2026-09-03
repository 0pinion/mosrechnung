from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import re


POSTAL_CITY_RE = re.compile(r"^(?P<postal_code>\d{4,10})\s+(?P<city>.+)$")


def split_address(address: str) -> tuple[str, str, str]:
    lines = [line.strip() for line in address.replace(",", "\n").splitlines() if line.strip()]
    if not lines:
        return "", "", ""
    street = lines[0]
    match = POSTAL_CITY_RE.match(" ".join(lines[1:])) if len(lines) > 1 else None
    if not match:
        return street, "", ""
    return street, match.group("postal_code"), match.group("city")


@dataclass(slots=True)
class Customer:
    name: str
    street: str
    postal_code: str = ""
    city: str = ""
    phone: str = ""
    dog_names: str = ""
    id: int | None = None

    @property
    def address(self) -> str:
        place = " ".join(part for part in (self.postal_code.strip(), self.city.strip()) if part)
        return "\n".join(part for part in (self.street.strip(), place) if part)

    @property
    def display_name(self) -> str:
        return f"{self.name} – {self.dog_names}" if self.dog_names.strip() else self.name


@dataclass(slots=True)
class Service:
    description: str
    standard_price_cents: int
    id: int | None = None


@dataclass(slots=True)
class InvoiceItem:
    description: str
    quantity: int
    unit_price_cents: int
    service_id: int | None = None
    id: int | None = None

    @property
    def total_cents(self) -> int:
        return self.quantity * self.unit_price_cents


@dataclass(slots=True)
class Invoice:
    number: str
    invoice_date: date
    customer_id: int
    customer_name: str
    customer_address: str
    customer_phone: str = ""
    customer_dog_names: str = ""
    items: list[InvoiceItem] = field(default_factory=list)
    sequence_value: int | None = None
    pdf_path: str = ""
    id: int | None = None
    tax_rate_percent: int = 0

    @property
    def net_total_cents(self) -> int:
        return sum(item.total_cents for item in self.items)

    @property
    def tax_cents(self) -> int:
        return (self.net_total_cents * self.tax_rate_percent + 50) // 100

    @property
    def total_cents(self) -> int:
        return self.net_total_cents + self.tax_cents
