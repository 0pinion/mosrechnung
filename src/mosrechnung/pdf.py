from __future__ import annotations

import os
import re
from pathlib import Path
from xml.sax.saxutils import escape

from .models import Invoice
from .money import cents_to_text


def safe_filename(number: str) -> str:
    filename = re.sub(r"[^A-Za-z0-9._-]+", "_", number.strip()).strip("._")
    if not filename:
        raise ValueError("Aus der Rechnungsnummer kann kein Dateiname erzeugt werden.")
    return f"{filename}.pdf"


def generate_invoice_pdf(invoice: Invoice, settings: dict[str, str], destination: str | Path | None = None) -> Path:
    required_settings = {
        "company_name": "Firmenname", "company_address": "Firmenanschrift",
        "company_seat": "Firmensitz", "company_iban": "IBAN", "company_bic": "BIC",
        "company_tax_office": "zuständiges Finanzamt", "company_tax_number": "Steuernummer",
    }
    missing = [label for key, label in required_settings.items() if not settings.get(key, "").strip()]
    if missing:
        raise ValueError("Fehlende Firmendaten für die Rechnung: " + ", ".join(missing))
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        BaseDocTemplate, Frame, Image, KeepTogether, PageTemplate, Paragraph,
        Spacer, Table, TableStyle,
    )

    output_dir = Path(destination or settings.get("invoice_output_dir") or Path.home())
    output_dir.mkdir(parents=True, exist_ok=True)
    final_path = output_dir / safe_filename(invoice.number)
    temporary_path = final_path.with_suffix(".pdf.tmp")

    styles = getSampleStyleSheet()
    normal = ParagraphStyle(
        "InvoiceNormal", parent=styles["Normal"], fontName="Helvetica", fontSize=9.5,
        leading=13, textColor=colors.HexColor("#202124"), spaceAfter=2 * mm,
    )
    small = ParagraphStyle("InvoiceSmall", parent=normal, fontSize=8, leading=10)
    heading = ParagraphStyle(
        "InvoiceHeading", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=20,
        leading=24, textColor=colors.HexColor("#1F4E5F"), spaceAfter=7 * mm,
    )
    right = ParagraphStyle("InvoiceRight", parent=normal, alignment=TA_RIGHT)
    address_style = ParagraphStyle("InvoiceAddress", parent=normal, alignment=TA_LEFT, leading=14)
    item_style = ParagraphStyle("InvoiceItem", parent=normal, fontSize=9, leading=11)

    page_width, page_height = A4
    left = right_margin = 20 * mm
    top = 22 * mm
    bottom = 22 * mm
    frame = Frame(left, bottom, page_width - left - right_margin, page_height - top - bottom, id="content")

    company_name = settings.get("company_name", "").strip()
    company_address = settings.get("company_address", "").strip()
    company_seat = settings.get("company_seat", "").strip()
    company_phone = settings.get("company_phone", "").strip()
    company_email = settings.get("company_email", "").strip()

    def draw_page(canvas: object, document: object) -> None:
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#D7DEE2"))
        canvas.line(left, 16 * mm, page_width - right_margin, 16 * mm)
        canvas.setFillColor(colors.HexColor("#687078"))
        canvas.setFont("Helvetica", 7.5)
        footer = " · ".join(
            value for value in (
                company_name,
                company_email,
                settings.get("company_iban", "").strip() and f"IBAN {settings['company_iban'].strip()}",
                settings.get("company_tax_number", "").strip() and f"St.-Nr. {settings['company_tax_number'].strip()}",
            ) if value
        )
        canvas.drawString(left, 10 * mm, footer[:150])
        canvas.restoreState()

    document = BaseDocTemplate(
        str(temporary_path), pagesize=A4, leftMargin=left, rightMargin=right_margin,
        topMargin=top, bottomMargin=bottom, title=f"Rechnung {invoice.number}",
        author=company_name,
    )
    document.addPageTemplates([PageTemplate(id="invoice", frames=[frame], onPage=draw_page)])

    story: list[object] = []
    configured_logo = settings.get("company_logo", "").strip()
    logo_candidates = [
        Path(configured_logo) if configured_logo else None,
        Path(__file__).with_name("logoicon1.png"),
        Path(__file__).resolve().parents[2] / "logoicon1.png",
        Path.cwd() / "logoicon1.png",
    ]
    logo_path = next((path for path in logo_candidates if path and path.is_file()), None)
    header_parts: list[object] = []
    if company_name:
        company_lines = [f"<b>{escape(company_name)}</b>"]
        if company_address:
            company_lines.append(escape(company_address).replace(chr(10), "<br/>"))
        if company_phone:
            company_lines.append(f"Telefon: {escape(company_phone)}")
        if company_email:
            company_lines.append(escape(company_email))
        header_parts.append(Paragraph("<br/>".join(company_lines), normal))
    else:
        header_parts.append(Paragraph("", normal))
    if logo_path and logo_path.is_file():
        try:
            logo = Image(str(logo_path), width=42 * mm, height=51 * mm, kind="proportional")
            logo.hAlign = "RIGHT"
            header_parts.append(logo)
        except Exception:
            header_parts.append(Paragraph("", normal))
    else:
        header_parts.append(Paragraph("", normal))
    header = Table([header_parts], colWidths=[110 * mm, 60 * mm])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (1, 0), (1, 0), "RIGHT")]))
    story.extend([header, Spacer(1, 10 * mm)])

    recipient = escape(invoice.customer_name)
    if invoice.customer_dog_names.strip():
        recipient += f"<br/><font size='8'>Hund: {escape(invoice.customer_dog_names)}</font>"
    recipient += f"<br/>{escape(invoice.customer_address).replace(chr(10), '<br/>')}"
    story.extend([Paragraph(recipient, address_style), Spacer(1, 10 * mm)])

    meta = Table(
        [[Paragraph(f"<b>Rechnung {escape(invoice.number)}</b>", heading), ""],
         [Paragraph("Rechnungsdatum", normal), Paragraph(invoice.invoice_date.strftime("%d.%m.%Y"), right)]],
        colWidths=[125 * mm, 45 * mm],
    )
    meta.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("SPAN", (0, 0), (1, 0))]))
    story.extend([meta, Spacer(1, 4 * mm), Paragraph("Für die folgenden Leistungen berechnen wir:", normal), Spacer(1, 3 * mm)])

    rows: list[list[object]] = [[
        Paragraph("<b>Leistung</b>", item_style), Paragraph("<b>Anzahl</b>", item_style),
        Paragraph("<b>Einzelpreis</b>", right), Paragraph("<b>Gesamt</b>", right),
    ]]
    for item in invoice.items:
        rows.append([
            Paragraph(escape(item.description).replace("\n", "<br/>"), item_style),
            Paragraph(str(item.quantity), right), Paragraph(cents_to_text(item.unit_price_cents, True), right),
            Paragraph(cents_to_text(item.total_cents, True), right),
        ])
    table_arguments = {
        "colWidths": [100 * mm, 18 * mm, 26 * mm, 26 * mm],
        "repeatRows": 1,
        "splitByRow": 1,
    }
    try:
        positions = Table(rows, splitInRow=1, **table_arguments)
    except TypeError:  # ReportLab 3.6 auf Ubuntu 22.04
        positions = Table(rows, **table_arguments)
    positions.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CCD5DA")),
        ("BOX", (0, 0), (-1, 0), 1.2, colors.HexColor("#202124")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.5 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2.5 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
        ("BACKGROUND", (0, 1), (-1, -1), colors.white),
    ]))
    total = Table(
        [
            [Paragraph("Nettobetrag", right), Paragraph(cents_to_text(invoice.net_total_cents, True), right)],
            [Paragraph(f"Umsatzsteuer {invoice.tax_rate_percent} %", right),
             Paragraph(cents_to_text(invoice.tax_cents, True), right)],
            [Paragraph("<b>Bruttobetrag</b>", right),
             Paragraph(f"<b>{cents_to_text(invoice.total_cents, True)}</b>", right)],
        ],
        colWidths=[144 * mm, 26 * mm],
    )
    total.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, 0), 1, colors.HexColor("#1F4E5F")),
        ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
    ]))
    story.extend([positions, Spacer(1, 3 * mm), KeepTogether([total, Spacer(1, 10 * mm)])])

    story.extend([
        Paragraph("Lieferdatum entspricht Rechnungsdatum.", normal),
        Paragraph("Zahlbar sofort ohne Abzug.", normal),
        Paragraph("Bitte überweisen Sie den Gesamtbetrag auf das unten genannte Konto.", normal),
        Spacer(1, 4 * mm),
    ])
    business_details = [
        company_name,
        company_seat,
        settings.get("company_iban", "").strip() and f"IBAN: {settings['company_iban'].strip()}",
        settings.get("company_bic", "").strip() and f"BIC: {settings['company_bic'].strip()}",
        settings.get("company_tax_office", "").strip() and
        f"Zuständiges Finanzamt: {settings['company_tax_office'].strip()}",
        settings.get("company_tax_number", "").strip() and
        f"Steuernummer: {settings['company_tax_number'].strip()}",
    ]
    story.append(Paragraph("<br/>".join(escape(value) for value in business_details if value), small))

    try:
        document.build(story)
        os.replace(temporary_path, final_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return final_path
