from odf.opendocument import OpenDocumentSpreadsheet
from odf.table import Table, TableCell, TableRow
from odf.text import P

from mosrechnung.db import Repository
from mosrechnung.ods_import import import_customers, parse_cell_address


def _sheet(name, values):
    sheet = Table(name=name)
    for row_values in values:
        row = TableRow()
        for value in row_values:
            cell = TableCell(valuetype="string")
            cell.addElement(P(text=value))
            row.addElement(cell)
        sheet.addElement(row)
    return sheet


def test_parse_cell_address():
    assert parse_cell_address("A1") == (0, 0)
    assert parse_cell_address("AA12") == (11, 26)


def test_import_deduplicates_sheets(tmp_path):
    document = OpenDocumentSpreadsheet()
    document.spreadsheet.addElement(_sheet("R1", [["Anna Müller", "Straße 1", "123", "Bello"]]))
    document.spreadsheet.addElement(_sheet("R2", [["anna müller", "Straße 1", "123", "Bello"]]))
    source = tmp_path / "invoices.ods"
    document.save(str(source))
    repository = Repository(tmp_path / "test.sqlite3")
    result = import_customers(
        source, repository,
        {"name": "A1", "address": "B1", "phone": "C1", "dogs": "D1"},
    )
    assert result.created == 1
    assert result.duplicates == 1
    assert len(repository.list_customers()) == 1


def test_imports_default_cells_a7_to_a9(tmp_path):
    document = OpenDocumentSpreadsheet()
    rows = [[""] for _ in range(6)] + [["Anna Müller"], ["Straße 1"], ["12345 Musterstadt"]]
    document.spreadsheet.addElement(_sheet("Kunde", rows))
    source = tmp_path / "customers.ods"
    document.save(str(source))
    repository = Repository(tmp_path / "default-cells.sqlite3")

    result = import_customers(source, repository, {
        "name": "A7", "street": "A8", "postal_city": "A9",
        "phone": "", "dogs": "",
    })

    customer = repository.list_customers()[0]
    assert result.created == 1
    assert (customer.street, customer.postal_code, customer.city) == (
        "Straße 1", "12345", "Musterstadt",
    )
