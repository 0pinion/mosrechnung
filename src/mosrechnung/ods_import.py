from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .db import Repository
from .models import Customer, split_address


CELL_RE = re.compile(r"^([A-Za-z]+)([1-9][0-9]*)$")


@dataclass(slots=True)
class ImportResult:
    sheets: int = 0
    created: int = 0
    updated: int = 0
    duplicates: int = 0
    skipped: int = 0
    warnings: list[str] = field(default_factory=list)


def parse_cell_address(address: str) -> tuple[int, int]:
    match = CELL_RE.fullmatch(address.strip())
    if not match:
        raise ValueError(f"Ungültige Zelladresse: {address!r}")
    column_text, row_text = match.groups()
    column = 0
    for character in column_text.upper():
        column = column * 26 + ord(character) - ord("A") + 1
    return int(row_text) - 1, column - 1


def _cell_text(cell: object) -> str:
    from odf import teletype
    from odf.text import P

    paragraphs = [teletype.extractText(paragraph).strip() for paragraph in cell.getElementsByType(P)]
    text = "\n".join(paragraph for paragraph in paragraphs if paragraph)
    if not text:
        text = str(cell.getAttribute("stringvalue") or cell.getAttribute("value") or "").strip()
    return "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()).strip()


def read_cells(sheet: object, addresses: dict[str, str]) -> dict[str, str]:
    from odf.namespaces import TABLENS

    targets = {key: parse_cell_address(address) for key, address in addresses.items() if address.strip()}
    values = {key: "" for key in addresses}
    rows = [node for node in sheet.childNodes if getattr(node, "qname", None) == (TABLENS, "table-row")]
    physical_row = 0
    unresolved = set(targets)

    for row in rows:
        row_repeat = int(row.getAttribute("numberrowsrepeated") or 1)
        matching_keys = [
            key for key in unresolved if physical_row <= targets[key][0] < physical_row + row_repeat
        ]
        if matching_keys:
            cells = [
                node for node in row.childNodes
                if getattr(node, "qname", None) in {
                    (TABLENS, "table-cell"), (TABLENS, "covered-table-cell")
                }
            ]
            physical_column = 0
            for cell in cells:
                column_repeat = int(cell.getAttribute("numbercolumnsrepeated") or 1)
                for key in list(matching_keys):
                    target_column = targets[key][1]
                    if physical_column <= target_column < physical_column + column_repeat:
                        values[key] = _cell_text(cell)
                        unresolved.discard(key)
                        matching_keys.remove(key)
                physical_column += column_repeat
                if not matching_keys:
                    break
        physical_row += row_repeat
        if not unresolved:
            break
    return values


def import_customers(
    path: str | Path,
    repository: Repository,
    addresses: dict[str, str],
) -> ImportResult:
    from odf.opendocument import load
    from odf.table import Table

    source = Path(path)
    if source.suffix.casefold() != ".ods":
        raise ValueError("Bitte eine LibreOffice-Calc-Datei im .ods-Format auswählen.")
    document = load(str(source))
    result = ImportResult()
    for sheet in document.spreadsheet.getElementsByType(Table):
        result.sheets += 1
        sheet_name = sheet.getAttribute("name") or f"Tabelle {result.sheets}"
        values = read_cells(sheet, addresses)
        name = values.get("name", "").strip()
        street_value = values.get("street", "").strip()
        postal_city_value = values.get("postal_city", "").strip()
        address = values.get("address", "").strip()
        if street_value:
            address = "\n".join(part for part in (street_value, postal_city_value) if part)
        if not name and not address:
            result.skipped += 1
            continue
        if not name or not address:
            missing = "Name" if not name else "Anschrift"
            result.skipped += 1
            result.warnings.append(f"{sheet_name}: {missing} fehlt; übersprungen.")
            continue
        street, postal_code, city = split_address(address)
        customer = Customer(
            name=name,
            street=street,
            postal_code=postal_code,
            city=city,
            phone=values.get("phone", ""),
            dog_names=values.get("dogs", ""),
        )
        outcome = repository.merge_imported_customer(customer)
        if outcome == "created":
            result.created += 1
        elif outcome == "updated":
            result.updated += 1
        else:
            result.duplicates += 1
    return result
