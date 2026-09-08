from __future__ import annotations

import base64
import binascii
import json
import mimetypes
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import Repository, normalize_name


FORMAT = "mosrechnung-backup"
VERSION = 1
MAX_BACKUP_BYTES = 25 * 1024 * 1024
MAX_LOGO_BYTES = 5 * 1024 * 1024

SETTING_NAMES = {
    "companyName": "company_name",
    "companyAddress": "company_address",
    "companySeat": "company_seat",
    "companyIban": "company_iban",
    "companyBic": "company_bic",
    "companyTaxOffice": "company_tax_office",
    "companyTaxNumber": "company_tax_number",
    "companyVatId": "company_vat_id",
    "companyPhone": "company_phone",
    "companyEmail": "company_email",
    "invoicePattern": "invoice_number_pattern",
    "nextInvoiceNumber": "next_invoice_number",
    "taxRate": "invoice_tax_rate",
}


def _logo_data_url(path_text: str) -> str:
    path = Path(path_text).expanduser() if path_text.strip() else None
    if not path or not path.is_file():
        return ""
    content = path.read_bytes()
    if len(content) > MAX_LOGO_BYTES:
        raise ValueError("Das Firmenlogo ist größer als 5 MB.")
    mime = mimetypes.guess_type(path.name)[0]
    if mime not in {"image/png", "image/jpeg", "image/webp"}:
        raise ValueError("Das Firmenlogo muss PNG, JPEG oder WebP sein.")
    return f"data:{mime};base64,{base64.b64encode(content).decode('ascii')}"


def backup_data(repository: Repository) -> dict[str, Any]:
    settings = repository.get_settings()
    customers = repository.list_customers()
    services = repository.list_services()
    invoices = repository.list_invoices()
    web_settings: dict[str, Any] = {
        web_name: settings.get(python_name, "")
        for web_name, python_name in SETTING_NAMES.items()
    }
    web_settings["nextInvoiceNumber"] = int(web_settings["nextInvoiceNumber"] or 1)
    web_settings["taxRate"] = int(web_settings["taxRate"] or 0)
    web_settings["companyLogo"] = _logo_data_url(settings.get("company_logo", ""))
    return {
        "format": FORMAT,
        "version": VERSION,
        "exportedAt": datetime.now(timezone.utc).isoformat(),
        "settings": web_settings,
        "customers": [
            {
                "id": customer.id,
                "name": customer.name,
                "street": customer.street,
                "postalCode": customer.postal_code,
                "city": customer.city,
                "phone": customer.phone,
                "dogs": customer.dog_names,
            }
            for customer in customers
        ],
        "services": [
            {"id": service.id, "description": service.description, "priceCents": service.standard_price_cents}
            for service in services
        ],
        "invoices": [
            {
                "id": invoice.id,
                "number": invoice.number,
                "invoiceDate": invoice.invoice_date.isoformat(),
                "customerId": invoice.customer_id,
                "customerName": invoice.customer_name,
                "customerAddress": invoice.customer_address,
                "customerPhone": invoice.customer_phone,
                "customerDogs": invoice.customer_dog_names,
                "items": [
                    {
                        "serviceId": item.service_id,
                        "description": item.description,
                        "quantity": item.quantity,
                        "unitPriceCents": item.unit_price_cents,
                        "totalCents": item.total_cents,
                    }
                    for item in invoice.items
                ],
                "taxRate": invoice.tax_rate_percent,
                "netCents": invoice.net_total_cents,
                "taxCents": invoice.tax_cents,
                "totalCents": invoice.total_cents,
            }
            for invoice in invoices
        ],
    }


def export_backup(repository: Repository, destination: str | Path) -> Path:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(backup_data(repository), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)
    return path


def _text(value: Any, field: str, *, required: bool = False, maximum: int = 10_000) -> str:
    if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()):
        raise ValueError(f"Ungültiger Text im Backup: {field}.")
    return value


def _integer(value: Any, field: str, *, minimum: int = 0, maximum: int = 2**53 - 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"Ungültiger Zahlenwert im Backup: {field}.")
    return value


def _list(value: Any, field: str, maximum: int = 100_000) -> list[Any]:
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError(f"Ungültiger Bereich im Backup: {field}.")
    return value


def _validate(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("Die Datei ist kein Mosrechnung-Backup.")
    if data.get("format", FORMAT) != FORMAT or _integer(data.get("version", 1), "Version", minimum=1) > VERSION:
        raise ValueError("Das Backup-Format wird von dieser App-Version nicht unterstützt.")
    customers = _list(data.get("customers"), "Kunden")
    services = _list(data.get("services"), "Leistungen")
    invoices = _list(data.get("invoices"), "Rechnungen")
    settings = data.get("settings", {})
    if not isinstance(settings, dict):
        raise ValueError("Ungültige Einstellungen im Backup.")

    customer_ids: set[int] = set()
    customer_names: set[str] = set()
    for customer in customers:
        if not isinstance(customer, dict):
            raise ValueError("Ungültiger Kunde im Backup.")
        customer_id = _integer(customer.get("id"), "Kunden-ID", minimum=1)
        name = _text(customer.get("name"), "Kundenname", required=True, maximum=500)
        _text(customer.get("street"), "Straße", required=True, maximum=500)
        _text(customer.get("postalCode"), "PLZ", required=True, maximum=20)
        _text(customer.get("city"), "Ort", required=True, maximum=300)
        _text(customer.get("phone", ""), "Telefon", maximum=100)
        _text(customer.get("dogs", ""), "Hundename", maximum=500)
        normalized = normalize_name(name)
        if customer_id in customer_ids or normalized in customer_names:
            raise ValueError("Das Backup enthält doppelte Kunden.")
        customer_ids.add(customer_id)
        customer_names.add(normalized)

    service_ids: set[int] = set()
    for service in services:
        if not isinstance(service, dict):
            raise ValueError("Ungültige Leistung im Backup.")
        service_id = _integer(service.get("id"), "Leistungs-ID", minimum=1)
        _text(service.get("description"), "Leistungsbezeichnung", required=True, maximum=2000)
        _integer(service.get("priceCents"), "Leistungspreis")
        if service_id in service_ids:
            raise ValueError("Das Backup enthält doppelte Leistungs-IDs.")
        service_ids.add(service_id)

    invoice_ids: set[int] = set()
    invoice_numbers: set[str] = set()
    for invoice in invoices:
        if not isinstance(invoice, dict):
            raise ValueError("Ungültige Rechnung im Backup.")
        invoice_id = _integer(invoice.get("id"), "Rechnungs-ID", minimum=1)
        number = _text(invoice.get("number"), "Rechnungsnummer", required=True, maximum=200).strip()
        invoice_date = _text(invoice.get("invoiceDate"), "Rechnungsdatum", required=True, maximum=10)
        try:
            datetime.strptime(invoice_date, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("Ungültiges Rechnungsdatum im Backup.") from exc
        if _integer(invoice.get("customerId"), "Kundenreferenz", minimum=1) not in customer_ids:
            raise ValueError("Eine Rechnung verweist auf einen fehlenden Kunden.")
        _text(invoice.get("customerName"), "Rechnungskunde", required=True, maximum=500)
        _text(invoice.get("customerAddress"), "Rechnungsanschrift", required=True, maximum=2000)
        _text(invoice.get("customerPhone", ""), "Telefon", maximum=100)
        _text(invoice.get("customerDogs", ""), "Hundename", maximum=500)
        _integer(invoice.get("taxRate"), "Steuersatz", maximum=100)
        items = _list(invoice.get("items"), "Rechnungspositionen", maximum=1000)
        if not items:
            raise ValueError("Eine Rechnung enthält keine Position.")
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("Ungültige Rechnungsposition im Backup.")
            service_id = item.get("serviceId")
            if service_id is not None:
                _integer(service_id, "Leistungsreferenz", minimum=1)
            _text(item.get("description"), "Position", required=True, maximum=5000)
            _integer(item.get("quantity"), "Menge", minimum=1)
            _integer(item.get("unitPriceCents"), "Einzelpreis")
        if invoice_id in invoice_ids or number in invoice_numbers:
            raise ValueError("Das Backup enthält doppelte Rechnungen.")
        invoice_ids.add(invoice_id)
        invoice_numbers.add(number)
    return data


def _import_logo(repository: Repository, value: Any) -> str:
    value = _text(value or "", "Firmenlogo", maximum=10 * 1024 * 1024)
    if not value:
        return ""
    match = re.fullmatch(r"data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=\r\n]+)", value, re.IGNORECASE)
    if not match:
        raise ValueError("Das Logo im Backup hat ein nicht erlaubtes Format.")
    try:
        content = base64.b64decode(match.group(2), validate=True)
    except binascii.Error as exc:
        raise ValueError("Das Logo im Backup ist beschädigt.") from exc
    if len(content) > MAX_LOGO_BYTES:
        raise ValueError("Das Logo im Backup ist größer als 5 MB.")
    suffix = {"png": ".png", "jpeg": ".jpg", "webp": ".webp"}[match.group(1).lower()]
    path = repository.path.parent / f"imported-company-logo{suffix}"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
    os.replace(temporary, path)
    return str(path)


def import_backup(repository: Repository, source: str | Path) -> None:
    path = Path(source)
    if path.stat().st_size > MAX_BACKUP_BYTES:
        raise ValueError("Die Backup-Datei ist größer als 25 MB.")
    try:
        data = _validate(json.loads(path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as exc:
        raise ValueError("Die Backup-Datei enthält kein gültiges JSON.") from exc
    web_settings = data.get("settings", {})
    imported_settings: dict[str, str] = {}
    for web_name, python_name in SETTING_NAMES.items():
        value = web_settings.get(web_name, "")
        if web_name == "nextInvoiceNumber":
            value = _integer(value, "nächste Rechnungsnummer", minimum=1)
        elif web_name == "taxRate":
            value = _integer(value, "Steuersatz", maximum=100)
        else:
            value = _text(value, web_name)
        imported_settings[python_name] = str(value)
    imported_settings["company_logo"] = _import_logo(repository, web_settings.get("companyLogo", ""))

    with repository.transaction() as connection:
        connection.execute("DELETE FROM invoice_items")
        connection.execute("DELETE FROM invoices")
        connection.execute("DELETE FROM customers")
        connection.execute("DELETE FROM services")
        for customer in data["customers"]:
            address = f"{customer['street']}\n{customer['postalCode']} {customer['city']}"
            connection.execute(
                """INSERT INTO customers(id, name, normalized_name, address, street, postal_code, city, phone, dog_names)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (customer["id"], customer["name"].strip(), normalize_name(customer["name"]), address,
                 customer["street"].strip(), customer["postalCode"].strip(), customer["city"].strip(),
                 customer.get("phone", "").strip(), customer.get("dogs", "").strip()),
            )
        for service in data["services"]:
            connection.execute(
                "INSERT INTO services(id, description, standard_price_cents) VALUES (?, ?, ?)",
                (service["id"], service["description"].strip(), service["priceCents"]),
            )
        for invoice in data["invoices"]:
            connection.execute(
                """INSERT INTO invoices(id, number, invoice_date, customer_id, customer_name, customer_address,
                   customer_phone, customer_dog_names, tax_rate_percent) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (invoice["id"], invoice["number"].strip(), invoice["invoiceDate"], invoice["customerId"],
                 invoice["customerName"], invoice["customerAddress"], invoice.get("customerPhone", ""),
                 invoice.get("customerDogs", ""), invoice["taxRate"]),
            )
            for position, item in enumerate(invoice["items"]):
                service_id = item.get("serviceId") if item.get("serviceId") in {s["id"] for s in data["services"]} else None
                connection.execute(
                    """INSERT INTO invoice_items(invoice_id, service_id, description, quantity,
                       unit_price_cents, position) VALUES (?, ?, ?, ?, ?, ?)""",
                    (invoice["id"], service_id, item["description"].strip(), item["quantity"],
                     item["unitPriceCents"], position),
                )
        connection.executemany(
            "INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            imported_settings.items(),
        )
