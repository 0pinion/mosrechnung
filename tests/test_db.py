import sqlite3
from datetime import date

import pytest

from mosrechnung.db import DuplicateInvoiceNumberError, Repository
from mosrechnung.models import Customer, Invoice, InvoiceItem, Service


@pytest.fixture
def repository(tmp_path):
    return Repository(tmp_path / "test.sqlite3")


def test_obsolete_vat_id_setting_is_removed(tmp_path):
    path = tmp_path / "settings.sqlite3"
    repository = Repository(path)
    repository.save_settings({"company_vat_id": "DE123456789"})

    reopened = Repository(path)

    assert "company_vat_id" not in reopened.get_settings()


def test_customer_deduplication_and_enrichment(repository):
    repository.save_customer(Customer("  Anna   Müller ", "Dorfstraße 1", "12345", "Dorf"))
    outcome = repository.merge_imported_customer(
        Customer("anna müller", "Andere Anschrift", phone="123", dog_names="Bello")
    )
    assert outcome == "updated"
    customers = repository.list_customers()
    assert len(customers) == 1
    assert customers[0].address == "Dorfstraße 1\n12345 Dorf"
    assert customers[0].phone == "123"
    assert customers[0].dog_names == "Bello"


def test_invoice_snapshots_items_and_advances_sequence(repository):
    customer = repository.save_customer(Customer("Anna", "Straße 1", "12345", "Dorf"))
    service = repository.save_service(Service("Hundetraining", 2500))
    number, sequence = repository.suggested_invoice_number(date(2026, 1, 2))
    invoice = Invoice(
        number, date(2026, 1, 2), customer.id, customer.name, customer.address,
        items=[InvoiceItem(service.description, 2, 2300, service.id)], sequence_value=sequence,
    )
    repository.save_invoice(invoice)
    loaded = repository.get_invoice(invoice.id)
    assert loaded is not None
    assert loaded.total_cents == 4600
    assert loaded.items[0].unit_price_cents == 2300
    assert repository.get_settings()["next_invoice_number"] == "2"


def test_duplicate_invoice_numbers_are_rejected(repository):
    customer = repository.save_customer(Customer("Anna", "Straße 1", "12345", "Dorf"))
    first = Invoice("RE-1", date.today(), customer.id, customer.name, customer.address,
                    items=[InvoiceItem("Leistung", 1, 100)])
    repository.save_invoice(first)
    second = Invoice("RE-1", date.today(), customer.id, customer.name, customer.address,
                     items=[InvoiceItem("Andere Leistung", 1, 200)])
    with pytest.raises(DuplicateInvoiceNumberError):
        repository.save_invoice(second)


def test_existing_customer_addresses_are_migrated(tmp_path):
    path = tmp_path / "existing.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE customers (
               id INTEGER PRIMARY KEY, name TEXT NOT NULL, normalized_name TEXT NOT NULL UNIQUE,
               address TEXT NOT NULL, phone TEXT NOT NULL DEFAULT '', dog_names TEXT NOT NULL DEFAULT '',
               created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
               updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"""
        )
        connection.execute(
            "INSERT INTO customers(name, normalized_name, address) VALUES (?, ?, ?)",
            ("Anna", "anna", "Straße 1\n12345 Musterstadt"),
        )

    customer = Repository(path).list_customers()[0]

    assert (customer.street, customer.postal_code, customer.city) == (
        "Straße 1", "12345", "Musterstadt",
    )


def test_default_number_format_and_tax_calculation(repository):
    number, sequence = repository.suggested_invoice_number(date(2026, 9, 1))
    invoice = Invoice(
        number=number, invoice_date=date(2026, 9, 1), customer_id=1,
        customer_name="Anna", customer_address="Straße 1\n12345 Ort",
        items=[InvoiceItem("Training", 2, 1000)], tax_rate_percent=19,
    )

    assert (number, sequence) == ("RG001/2026", 1)
    assert invoice.net_total_cents == 2000
    assert invoice.tax_cents == 380
    assert invoice.total_cents == 2380
