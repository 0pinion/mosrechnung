from __future__ import annotations

import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Iterator

from .models import Customer, Invoice, InvoiceItem, Service, split_address
from .paths import default_invoice_dir


DEFAULT_SETTINGS = {
    "company_name": "",
    "company_address": "",
    "company_seat": "",
    "company_iban": "",
    "company_bic": "",
    "company_tax_office": "",
    "company_tax_number": "",
    "company_phone": "",
    "company_email": "",
    "company_logo": "",
    "invoice_output_dir": str(default_invoice_dir()),
    "invoice_number_pattern": "RG{number:03d}/{year}",
    "next_invoice_number": "1",
    "invoice_tax_rate": "19",
    "ods_name_cell": "A7",
    "ods_street_cell": "A8",
    "ods_postal_city_cell": "A9",
    "ods_address_cell": "",
    "ods_phone_cell": "",
    "ods_dogs_cell": "",
}


def normalize_name(name: str) -> str:
    text = unicodedata.normalize("NFKC", name).casefold().strip()
    return re.sub(r"\s+", " ", text)


class DuplicateInvoiceNumberError(ValueError):
    pass


class Repository:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS customers (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL UNIQUE,
                    address TEXT NOT NULL,
                    phone TEXT NOT NULL DEFAULT '',
                    dog_names TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS services (
                    id INTEGER PRIMARY KEY,
                    description TEXT NOT NULL,
                    standard_price_cents INTEGER NOT NULL CHECK (standard_price_cents >= 0)
                );
                CREATE TABLE IF NOT EXISTS invoices (
                    id INTEGER PRIMARY KEY,
                    number TEXT NOT NULL UNIQUE,
                    sequence_value INTEGER,
                    invoice_date TEXT NOT NULL,
                    customer_id INTEGER NOT NULL REFERENCES customers(id),
                    customer_name TEXT NOT NULL,
                    customer_address TEXT NOT NULL,
                    customer_phone TEXT NOT NULL DEFAULT '',
                    customer_dog_names TEXT NOT NULL DEFAULT '',
                    pdf_path TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS invoice_items (
                    id INTEGER PRIMARY KEY,
                    invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
                    service_id INTEGER REFERENCES services(id) ON DELETE SET NULL,
                    description TEXT NOT NULL,
                    quantity INTEGER NOT NULL CHECK (quantity > 0),
                    unit_price_cents INTEGER NOT NULL CHECK (unit_price_cents >= 0),
                    position INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            connection.executemany(
                "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
                DEFAULT_SETTINGS.items(),
            )
            connection.execute("DELETE FROM settings WHERE key = 'company_vat_id'")
            customer_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(customers)")
            }
            added_customer_columns = False
            for column in ("street", "postal_code", "city"):
                if column not in customer_columns:
                    connection.execute(
                        f"ALTER TABLE customers ADD COLUMN {column} TEXT NOT NULL DEFAULT ''"
                    )
                    added_customer_columns = True
            if added_customer_columns:
                for row in connection.execute("SELECT id, address FROM customers"):
                    street, postal_code, city = split_address(row["address"])
                    connection.execute(
                        "UPDATE customers SET street=?, postal_code=?, city=? WHERE id=?",
                        (street, postal_code, city, row["id"]),
                    )
            invoice_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(invoices)")
            }
            if "tax_rate_percent" not in invoice_columns:
                connection.execute(
                    "ALTER TABLE invoices ADD COLUMN tax_rate_percent INTEGER NOT NULL DEFAULT 0"
                )

    def list_customers(self, query: str = "") -> list[Customer]:
        sql = "SELECT * FROM customers"
        parameters: tuple[str, ...] = ()
        if query.strip():
            sql += " WHERE name LIKE ? COLLATE NOCASE OR dog_names LIKE ? COLLATE NOCASE"
            term = f"%{query.strip()}%"
            parameters = (term, term)
        sql += " ORDER BY name COLLATE NOCASE"
        with self.connect() as connection:
            return [self._customer(row) for row in connection.execute(sql, parameters)]

    def get_customer(self, customer_id: int) -> Customer | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
        return self._customer(row) if row else None

    def find_customer_by_name(self, name: str) -> Customer | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM customers WHERE normalized_name = ?", (normalize_name(name),)
            ).fetchone()
        return self._customer(row) if row else None

    def save_customer(self, customer: Customer) -> Customer:
        name = customer.name.strip()
        street = customer.street.strip()
        postal_code = customer.postal_code.strip()
        city = customer.city.strip()
        if not name or not street:
            raise ValueError("Name und Straße/Hausnummer sind Pflichtfelder.")
        address = "\n".join(
            part for part in (street, " ".join(part for part in (postal_code, city) if part)) if part
        )
        with self.transaction() as connection:
            if customer.id is None:
                cursor = connection.execute(
                    """INSERT INTO customers(name, normalized_name, address, street, postal_code, city,
                       phone, dog_names) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (name, normalize_name(name), address, street, postal_code, city,
                     customer.phone.strip(), customer.dog_names.strip()),
                )
                customer.id = int(cursor.lastrowid)
            else:
                connection.execute(
                    """UPDATE customers SET name=?, normalized_name=?, address=?, street=?, postal_code=?, city=?,
                       phone=?, dog_names=?,
                       updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                    (name, normalize_name(name), address, street, postal_code, city,
                     customer.phone.strip(), customer.dog_names.strip(), customer.id),
                )
        customer.name = name
        customer.street = street
        customer.postal_code = postal_code
        customer.city = city
        return customer

    def merge_imported_customer(self, customer: Customer) -> str:
        existing = self.find_customer_by_name(customer.name)
        if not existing:
            self.save_customer(customer)
            return "created"
        changed = False
        for field in ("street", "postal_code", "city", "phone", "dog_names"):
            old = getattr(existing, field).strip()
            new = getattr(customer, field).strip()
            if not old and new:
                setattr(existing, field, new)
                changed = True
        if changed:
            self.save_customer(existing)
            return "updated"
        return "duplicate"

    def delete_customer(self, customer_id: int) -> None:
        with self.transaction() as connection:
            connection.execute("DELETE FROM customers WHERE id = ?", (customer_id,))

    @staticmethod
    def _customer(row: sqlite3.Row) -> Customer:
        return Customer(
            name=row["name"], street=row["street"] or row["address"],
            postal_code=row["postal_code"], city=row["city"], phone=row["phone"],
            dog_names=row["dog_names"], id=row["id"],
        )

    def list_services(self) -> list[Service]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM services ORDER BY description COLLATE NOCASE")
            return [Service(row["description"], row["standard_price_cents"], row["id"]) for row in rows]

    def save_service(self, service: Service) -> Service:
        description = service.description.strip()
        if not description:
            raise ValueError("Bitte eine Leistungsbezeichnung eingeben.")
        with self.transaction() as connection:
            if service.id is None:
                cursor = connection.execute(
                    "INSERT INTO services(description, standard_price_cents) VALUES (?, ?)",
                    (description, service.standard_price_cents),
                )
                service.id = int(cursor.lastrowid)
            else:
                connection.execute(
                    "UPDATE services SET description=?, standard_price_cents=? WHERE id=?",
                    (description, service.standard_price_cents, service.id),
                )
        service.description = description
        return service

    def delete_service(self, service_id: int) -> None:
        with self.transaction() as connection:
            connection.execute("DELETE FROM services WHERE id = ?", (service_id,))

    def invoice_number_exists(self, number: str, exclude_id: int | None = None) -> bool:
        sql = "SELECT 1 FROM invoices WHERE number = ?"
        parameters: tuple[object, ...] = (number,)
        if exclude_id is not None:
            sql += " AND id != ?"
            parameters += (exclude_id,)
        with self.connect() as connection:
            return connection.execute(sql, parameters).fetchone() is not None

    def suggested_invoice_number(self, invoice_date: date | None = None) -> tuple[str, int]:
        settings = self.get_settings()
        sequence = int(settings.get("next_invoice_number", "1"))
        day = invoice_date or date.today()
        pattern = settings.get("invoice_number_pattern", DEFAULT_SETTINGS["invoice_number_pattern"])
        try:
            number = pattern.format(year=day.year, number=sequence)
        except (KeyError, ValueError) as exc:
            raise ValueError("Das Rechnungsnummernformat ist ungültig.") from exc
        return number, sequence

    def list_invoices(self, query: str = "") -> list[Invoice]:
        sql = "SELECT * FROM invoices"
        parameters: tuple[str, ...] = ()
        if query.strip():
            sql += " WHERE number LIKE ? COLLATE NOCASE OR customer_name LIKE ? COLLATE NOCASE"
            term = f"%{query.strip()}%"
            parameters = (term, term)
        sql += " ORDER BY invoice_date DESC, id DESC"
        with self.connect() as connection:
            rows = connection.execute(sql, parameters).fetchall()
            return [self._invoice(connection, row) for row in rows]

    def get_invoice(self, invoice_id: int) -> Invoice | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
            return self._invoice(connection, row) if row else None

    def save_invoice(self, invoice: Invoice) -> Invoice:
        if not invoice.number.strip():
            raise ValueError("Bitte eine Rechnungsnummer eingeben.")
        if not invoice.items:
            raise ValueError("Eine Rechnung benötigt mindestens eine Position.")
        if self.invoice_number_exists(invoice.number.strip(), invoice.id):
            raise DuplicateInvoiceNumberError(f"Die Rechnungsnummer {invoice.number} ist bereits vergeben.")
        with self.transaction() as connection:
            values = (
                invoice.number.strip(), invoice.sequence_value, invoice.invoice_date.isoformat(), invoice.customer_id,
                invoice.customer_name, invoice.customer_address, invoice.customer_phone,
                invoice.customer_dog_names, invoice.pdf_path, invoice.tax_rate_percent,
            )
            if invoice.id is None:
                cursor = connection.execute(
                    """INSERT INTO invoices(number, sequence_value, invoice_date, customer_id, customer_name,
                       customer_address, customer_phone, customer_dog_names, pdf_path, tax_rate_percent)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    values,
                )
                invoice.id = int(cursor.lastrowid)
            else:
                connection.execute(
                    """UPDATE invoices SET number=?, sequence_value=?, invoice_date=?, customer_id=?,
                       customer_name=?, customer_address=?, customer_phone=?, customer_dog_names=?, pdf_path=?,
                       tax_rate_percent=?,
                       updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                    values + (invoice.id,),
                )
                connection.execute("DELETE FROM invoice_items WHERE invoice_id = ?", (invoice.id,))
            connection.executemany(
                """INSERT INTO invoice_items(invoice_id, service_id, description, quantity,
                   unit_price_cents, position) VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    (invoice.id, item.service_id, item.description.strip(), item.quantity,
                     item.unit_price_cents, position)
                    for position, item in enumerate(invoice.items)
                ],
            )
            if invoice.sequence_value is not None:
                current = int(self._get_setting(connection, "next_invoice_number", "1"))
                if invoice.sequence_value >= current:
                    connection.execute(
                        "UPDATE settings SET value = ? WHERE key = 'next_invoice_number'",
                        (str(invoice.sequence_value + 1),),
                    )
        invoice.number = invoice.number.strip()
        return invoice

    @staticmethod
    def _invoice(connection: sqlite3.Connection, row: sqlite3.Row) -> Invoice:
        item_rows = connection.execute(
            "SELECT * FROM invoice_items WHERE invoice_id = ? ORDER BY position", (row["id"],)
        ).fetchall()
        items = [
            InvoiceItem(item["description"], item["quantity"], item["unit_price_cents"], item["service_id"], item["id"])
            for item in item_rows
        ]
        return Invoice(
            number=row["number"], invoice_date=date.fromisoformat(row["invoice_date"]),
            customer_id=row["customer_id"], customer_name=row["customer_name"],
            customer_address=row["customer_address"], customer_phone=row["customer_phone"],
            customer_dog_names=row["customer_dog_names"], items=items,
            sequence_value=row["sequence_value"], pdf_path=row["pdf_path"], id=row["id"],
            tax_rate_percent=row["tax_rate_percent"],
        )

    def get_settings(self) -> dict[str, str]:
        with self.connect() as connection:
            return {row["key"]: row["value"] for row in connection.execute("SELECT key, value FROM settings")}

    @staticmethod
    def _get_setting(connection: sqlite3.Connection, key: str, default: str = "") -> str:
        row = connection.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def save_settings(self, values: dict[str, str]) -> None:
        with self.transaction() as connection:
            connection.executemany(
                "INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                [(key, str(value)) for key, value in values.items()],
            )
