import json
from datetime import date

import pytest

from mosrechnung.backup import export_backup, import_backup
from mosrechnung.db import Repository
from mosrechnung.models import Customer, Invoice, InvoiceItem, Service


def populated_repository(path):
    repository = Repository(path)
    customer = repository.save_customer(Customer("Anna Müller", "Dorfstraße 1", "12345", "Dorf", "123", "Bello"))
    service = repository.save_service(Service("Hundetraining", 2500))
    repository.save_settings({"company_name": "Hundeschule", "invoice_tax_rate": "19"})
    repository.save_invoice(Invoice(
        "RG001/2026", date(2026, 9, 8), customer.id, customer.name, customer.address,
        customer.phone, customer.dog_names,
        [InvoiceItem(service.description, 2, 2300, service.id)], tax_rate_percent=19,
    ))
    return repository


def test_export_is_compatible_with_webapp_format(tmp_path):
    repository = populated_repository(tmp_path / "source.sqlite3")
    path = export_backup(repository, tmp_path / "backup.json")
    data = json.loads(path.read_text(encoding="utf-8"))

    assert (data["format"], data["version"]) == ("mosrechnung-backup", 1)
    assert data["customers"][0]["postalCode"] == "12345"
    assert data["services"][0]["priceCents"] == 2500
    assert data["invoices"][0]["totalCents"] == 5474
    assert data["settings"]["companyName"] == "Hundeschule"
    assert "companyVatId" not in data["settings"]


def test_round_trip_replaces_database(tmp_path):
    source = populated_repository(tmp_path / "source.sqlite3")
    path = export_backup(source, tmp_path / "backup.json")
    target = Repository(tmp_path / "target.sqlite3")
    target.save_customer(Customer("Wird ersetzt", "Alt 1", "11111", "Altstadt"))

    import_backup(target, path)

    assert [customer.name for customer in target.list_customers()] == ["Anna Müller"]
    invoice = target.list_invoices()[0]
    assert invoice.number == "RG001/2026"
    assert invoice.items[0].unit_price_cents == 2300
    assert invoice.tax_rate_percent == 19
    assert "company_vat_id" not in target.get_settings()


def test_import_accepts_unusual_legacy_text(tmp_path):
    source = populated_repository(tmp_path / "source.sqlite3")
    path = export_backup(source, tmp_path / "backup.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    unusual_postal_code = "D-12345 / Postfach + Sonderbezirk (Altbestand)"
    data["customers"][0]["postalCode"] = unusual_postal_code
    data["customers"][0]["phone"] = 123456
    data["invoices"][0]["customerAddress"] = "Historische Anschrift " * 300
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    target = Repository(tmp_path / "target.sqlite3")

    import_backup(target, path)

    customer = target.list_customers()[0]
    assert customer.postal_code == unusual_postal_code
    assert customer.phone == "123456"
    assert len(target.list_invoices()[0].customer_address) > 2000


def test_invalid_backup_does_not_change_database(tmp_path):
    repository = populated_repository(tmp_path / "data.sqlite3")
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps({
        "format": "mosrechnung-backup", "version": 1, "settings": {},
        "customers": [], "services": [],
        "invoices": [{"id": 1, "invoiceDate": "nicht-valide"}],
    }), encoding="utf-8")

    with pytest.raises(ValueError):
        import_backup(repository, path)

    assert [customer.name for customer in repository.list_customers()] == ["Anna Müller"]
