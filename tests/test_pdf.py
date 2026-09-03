from datetime import date

from mosrechnung.models import Invoice, InvoiceItem
from mosrechnung.pdf import generate_invoice_pdf, safe_filename


def test_safe_filename():
    assert safe_filename("RE/2026:0042") == "RE_2026_0042.pdf"


def test_generates_pdf_with_many_wrapping_rows(tmp_path):
    invoice = Invoice(
        number="RE-2026-0042", invoice_date=date(2026, 8, 30), customer_id=1,
        customer_name="Anna Müller", customer_address="Lange Straße 1\n12345 Musterstadt",
        customer_dog_names="Bello",
        items=[
            InvoiceItem(
                f"Position {index}: Ausführliche Leistungsbeschreibung mit automatischem Zeilenumbruch",
                1, 1250,
            )
            for index in range(55)
        ],
    )
    path = generate_invoice_pdf(invoice, {
        "invoice_output_dir": str(tmp_path), "company_name": "Hundeschule Muster",
        "company_address": "Weg 2\n12345 Musterstadt", "company_iban": "DE00 0000 0000 0000 0000 00",
        "company_seat": "Musterstadt", "company_bic": "TESTDE00XXX",
        "company_tax_office": "Finanzamt Musterstadt", "company_tax_number": "12/345/67890",
    })
    assert path.name == "RE-2026-0042.pdf"
    assert path.read_bytes().startswith(b"%PDF-")
    assert path.stat().st_size > 5000
