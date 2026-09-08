from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from urllib.parse import quote

try:
    from PySide6.QtCore import QAbstractTableModel, QDate, QModelIndex, Qt, QTimer, QUrl, Signal
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import (
        QAbstractItemView, QApplication, QComboBox, QCompleter, QDateEdit, QDialog,
        QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QGroupBox,
        QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox,
        QPushButton, QScrollArea, QSpinBox, QTabWidget, QTableView, QTableWidget,
        QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
    )
except ImportError:  # Ubuntu 22.04/24.04 liefern PySide2 statt PySide6.
    from PySide2.QtCore import QAbstractTableModel, QDate, QModelIndex, Qt, QTimer, QUrl, Signal
    from PySide2.QtGui import QDesktopServices
    from PySide2.QtWidgets import (
        QAbstractItemView, QApplication, QComboBox, QCompleter, QDateEdit, QDialog,
        QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QGroupBox,
        QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox,
        QPushButton, QScrollArea, QSpinBox, QTabWidget, QTableView, QTableWidget,
        QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
    )

from .db import DuplicateInvoiceNumberError, Repository
from .backup import export_backup, import_backup
from .models import Customer, Invoice, InvoiceItem, Service
from .money import cents_to_text, text_to_cents
from .ods_import import import_customers, parse_cell_address
from .pdf import generate_invoice_pdf


def show_error(parent: QWidget, title: str, error: Exception | str) -> None:
    QMessageBox.critical(parent, title, str(error))


class CustomerDialog(QDialog):
    def __init__(self, parent: QWidget, customer: Customer | None = None):
        super().__init__(parent)
        self.customer = customer
        self.setWindowTitle("Kunde bearbeiten" if customer else "Neuer Kunde")
        self.setMinimumWidth(480)
        form = QFormLayout(self)
        self.name = QLineEdit(customer.name if customer else "")
        self.street = QLineEdit(customer.street if customer else "")
        self.postal_code = QLineEdit(customer.postal_code if customer else "")
        self.postal_code.setMaxLength(10)
        self.city = QLineEdit(customer.city if customer else "")
        self.phone = QLineEdit(customer.phone if customer else "")
        self.dogs = QLineEdit(customer.dog_names if customer else "")
        form.addRow("Name *", self.name)
        form.addRow("Straße + Hausnummer *", self.street)
        form.addRow("PLZ *", self.postal_code)
        form.addRow("Ort *", self.city)
        form.addRow("Telefon", self.phone)
        form.addRow("Hundename(n)", self.dogs)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _validate(self) -> None:
        required = (self.name, self.street, self.postal_code, self.city)
        if any(not field.text().strip() for field in required):
            show_error(self, "Fehlende Angaben", "Name, Straße/Hausnummer, PLZ und Ort sind Pflichtfelder.")
            return
        self.accept()

    def value(self) -> Customer:
        return Customer(
            name=self.name.text(), street=self.street.text(), postal_code=self.postal_code.text(),
            city=self.city.text(), phone=self.phone.text(), dog_names=self.dogs.text(),
            id=self.customer.id if self.customer else None,
        )


class CustomerTableModel(QAbstractTableModel):
    HEADERS = ("Name", "Anschrift", "Telefon", "Hundename(n)")

    def __init__(self, customers: list[Customer] | None = None):
        super().__init__()
        self.customers = customers or []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.customers)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.HEADERS)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or role != Qt.DisplayRole:
            return None
        customer = self.customers[index.row()]
        return (
            customer.name,
            customer.address.replace("\n", ", "),
            customer.phone,
            customer.dog_names,
        )[index.column()]

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return super().headerData(section, orientation, role)

    def replace(self, customers: list[Customer]) -> None:
        self.beginResetModel()
        self.customers = customers
        self.endResetModel()


class CustomersWidget(QWidget):
    customers_changed = Signal()
    invoice_created = Signal()

    def __init__(self, repository: Repository):
        super().__init__()
        self.repository = repository
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Kunden oder Hund suchen …")
        self.search.setClearButtonEnabled(True)
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(200)
        self.search_timer.timeout.connect(self.refresh)
        self.search.textChanged.connect(lambda _text: self.search_timer.start())
        add = QPushButton("Neuer Kunde")
        add.clicked.connect(self.add_customer)
        add.setObjectName("primaryButton")
        self.new_invoice_button = QPushButton("Neue Rechnung")
        self.new_invoice_button.clicked.connect(self.new_invoice)
        self.new_invoice_button.setEnabled(False)
        self.edit_button = QPushButton("Bearbeiten")
        self.edit_button.clicked.connect(self.edit_customer)
        self.edit_button.setEnabled(False)
        import_button = QPushButton("Aus Calc importieren …")
        import_button.clicked.connect(self.import_ods)
        self.delete_button = QPushButton("Löschen")
        self.delete_button.clicked.connect(self.delete_customer)
        self.delete_button.setEnabled(False)
        top.addWidget(self.search, 1)
        top.addWidget(add)
        top.addWidget(self.edit_button)
        top.addWidget(self.new_invoice_button)
        top.addWidget(import_button)
        top.addWidget(self.delete_button)
        layout.addLayout(top)
        self.table = QTableView()
        self.model = CustomerTableModel()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.doubleClicked.connect(self.edit_customer)
        self.table.selectionModel().selectionChanged.connect(self._selection_changed)
        layout.addWidget(self.table, 1)
        self._customers: list[Customer] = []
        self._loaded = False

    def ensure_loaded(self) -> None:
        if not self._loaded:
            self.refresh()

    def refresh(self) -> None:
        self._customers = self.repository.list_customers(self.search.text())
        self.model.replace(self._customers)
        self._selection_changed()
        self._loaded = True

    def _selected(self) -> Customer | None:
        row = self.table.currentIndex().row()
        return self._customers[row] if 0 <= row < len(self._customers) else None

    def _selection_changed(self) -> None:
        selected = self._selected() is not None
        self.edit_button.setEnabled(selected)
        self.new_invoice_button.setEnabled(selected)
        self.delete_button.setEnabled(selected)

    def new_invoice(self) -> None:
        customer = self._selected()
        if not customer:
            show_error(self, "Kein Kunde ausgewählt", "Bitte zuerst einen Kunden in der Liste auswählen.")
            return
        dialog = InvoiceDialog(self, self.repository, customer_id=customer.id)
        if dialog.exec() == QDialog.Accepted:
            self.invoice_created.emit()

    def add_customer(self) -> None:
        dialog = CustomerDialog(self)
        if dialog.exec() == QDialog.Accepted:
            try:
                self.repository.save_customer(dialog.value())
            except (ValueError, sqlite3.IntegrityError) as exc:
                show_error(self, "Kunde konnte nicht gespeichert werden", exc)
                return
            self.refresh()
            self.customers_changed.emit()

    def edit_customer(self) -> None:
        customer = self._selected()
        if not customer:
            return
        dialog = CustomerDialog(self, customer)
        if dialog.exec() == QDialog.Accepted:
            try:
                self.repository.save_customer(dialog.value())
            except (ValueError, sqlite3.IntegrityError) as exc:
                show_error(self, "Kunde konnte nicht gespeichert werden", exc)
                return
            self.refresh()
            self.customers_changed.emit()

    def delete_customer(self) -> None:
        customer = self._selected()
        if not customer:
            return
        answer = QMessageBox.question(self, "Kunde löschen", f"„{customer.name}“ wirklich löschen?")
        if answer != QMessageBox.Yes:
            return
        try:
            self.repository.delete_customer(customer.id or 0)
        except sqlite3.IntegrityError:
            show_error(self, "Kunde kann nicht gelöscht werden", "Für diesen Kunden sind Rechnungen gespeichert.")
            return
        self.refresh()
        self.customers_changed.emit()

    def import_ods(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Calc-Datei auswählen", "", "LibreOffice Calc (*.ods)")
        if not path:
            return
        settings = self.repository.get_settings()
        addresses = {
            "name": settings.get("ods_name_cell", ""),
            "street": settings.get("ods_street_cell") or settings.get("ods_address_cell", ""),
            "postal_city": settings.get("ods_postal_city_cell", ""),
            "phone": settings.get("ods_phone_cell", ""),
            "dogs": settings.get("ods_dogs_cell", ""),
        }
        try:
            if not addresses["name"] or not addresses["street"] or not addresses["postal_city"]:
                raise ValueError("Bitte zuerst die Zellen für Name, Straße und PLZ/Ort festlegen.")
            result = import_customers(path, self.repository, addresses)
        except Exception as exc:
            show_error(self, "Import fehlgeschlagen", exc)
            return
        message = (
            f"{result.sheets} Tabellenblätter gelesen.\n\n"
            f"Neu angelegt: {result.created}\n"
            f"Ergänzt: {result.updated}\n"
            f"Dubletten: {result.duplicates}\n"
            f"Übersprungen: {result.skipped}"
        )
        if result.warnings:
            message += "\n\nHinweise:\n" + "\n".join(result.warnings[:10])
            if len(result.warnings) > 10:
                message += f"\n… und {len(result.warnings) - 10} weitere"
        QMessageBox.information(self, "Import abgeschlossen", message)
        self.refresh()
        self.customers_changed.emit()


class ServiceDialog(QDialog):
    def __init__(self, parent: QWidget, service: Service | None = None):
        super().__init__(parent)
        self.service = service
        self.setWindowTitle("Leistung bearbeiten" if service else "Neue Leistung")
        form = QFormLayout(self)
        self.description = QLineEdit(service.description if service else "")
        self.price = QLineEdit(cents_to_text(service.standard_price_cents) if service else "")
        self.price.setPlaceholderText("0,00")
        form.addRow("Bezeichnung *", self.description)
        form.addRow("Standardpreis *", self.price)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _validate(self) -> None:
        try:
            self.value()
        except ValueError as exc:
            show_error(self, "Ungültige Eingabe", exc)
            return
        self.accept()

    def value(self) -> Service:
        if not self.description.text().strip():
            raise ValueError("Bitte eine Bezeichnung eingeben.")
        return Service(
            self.description.text(), text_to_cents(self.price.text()),
            self.service.id if self.service else None,
        )


class SettingsWidget(QScrollArea):
    settings_changed = Signal()

    def __init__(self, repository: Repository):
        super().__init__()
        self.repository = repository
        self.setWidgetResizable(True)
        content = QWidget()
        self.setWidget(content)
        layout = QVBoxLayout(content)

        company_box = QGroupBox("Eigene Firmendaten")
        company_form = QFormLayout(company_box)
        self.company_name = QLineEdit()
        self.company_address = QTextEdit()
        self.company_address.setFixedHeight(80)
        self.company_seat = QLineEdit()
        self.company_iban = QLineEdit()
        self.company_bic = QLineEdit()
        self.company_tax_office = QLineEdit()
        self.company_tax = QLineEdit()
        self.company_phone = QLineEdit()
        self.company_email = QLineEdit()
        self.logo = QLineEdit()
        logo_row = QHBoxLayout()
        logo_row.addWidget(self.logo, 1)
        logo_button = QPushButton("Auswählen …")
        logo_button.clicked.connect(self.choose_logo)
        logo_row.addWidget(logo_button)
        company_form.addRow("Name *", self.company_name)
        company_form.addRow("Anschrift *", self.company_address)
        company_form.addRow("Firmensitz *", self.company_seat)
        company_form.addRow("IBAN *", self.company_iban)
        company_form.addRow("BIC *", self.company_bic)
        company_form.addRow("Zuständiges Finanzamt *", self.company_tax_office)
        company_form.addRow("Steuernummer *", self.company_tax)
        company_form.addRow("Telefon", self.company_phone)
        company_form.addRow("E-Mail", self.company_email)
        company_form.addRow("Logo", logo_row)
        layout.addWidget(company_box)

        invoice_box = QGroupBox("Rechnungen")
        invoice_form = QFormLayout(invoice_box)
        self.output_dir = QLineEdit()
        output_row = QHBoxLayout()
        output_row.addWidget(self.output_dir, 1)
        output_button = QPushButton("Auswählen …")
        output_button.clicked.connect(self.choose_output_dir)
        output_row.addWidget(output_button)
        self.number_pattern = QLineEdit()
        self.number_pattern.setToolTip("Erlaubte Platzhalter: {year} und {number}, z. B. RG{number:03d}/{year}")
        self.next_number = QSpinBox()
        self.next_number.setRange(1, 999999999)
        self.tax_rate = QSpinBox()
        self.tax_rate.setRange(0, 100)
        self.tax_rate.setSuffix(" %")
        invoice_form.addRow("PDF-Verzeichnis", output_row)
        invoice_form.addRow("Nummernformat", self.number_pattern)
        invoice_form.addRow("Nächste Startnummer", self.next_number)
        invoice_form.addRow("Umsatzsteuersatz", self.tax_rate)
        layout.addWidget(invoice_box)

        import_box = QGroupBox("Calc-Import: Zelladressen in jedem Tabellenblatt")
        import_form = QFormLayout(import_box)
        self.ods_name = QLineEdit()
        self.ods_street = QLineEdit()
        self.ods_postal_city = QLineEdit()
        self.ods_phone = QLineEdit()
        self.ods_dogs = QLineEdit()
        import_form.addRow("Name *", self.ods_name)
        import_form.addRow("Straße + Hausnummer *", self.ods_street)
        import_form.addRow("PLZ Ort *", self.ods_postal_city)
        import_form.addRow("Telefon", self.ods_phone)
        import_form.addRow("Hundename(n)", self.ods_dogs)
        layout.addWidget(import_box)

        service_box = QGroupBox("Vordefinierte Leistungen")
        service_layout = QVBoxLayout(service_box)
        self.service_table = QTableWidget(0, 2)
        self.service_table.setHorizontalHeaderLabels(["Bezeichnung", "Standardpreis"])
        self.service_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.service_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.service_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.service_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.service_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.service_table.verticalHeader().setVisible(False)
        self.service_table.doubleClicked.connect(self.edit_service)
        service_layout.addWidget(self.service_table)
        service_actions = QHBoxLayout()
        add_service = QPushButton("Leistung hinzufügen")
        add_service.clicked.connect(self.add_service)
        edit_service = QPushButton("Bearbeiten")
        edit_service.clicked.connect(self.edit_service)
        delete_service = QPushButton("Löschen")
        delete_service.clicked.connect(self.delete_service)
        service_actions.addWidget(add_service)
        service_actions.addStretch()
        service_actions.addWidget(edit_service)
        service_actions.addWidget(delete_service)
        service_layout.addLayout(service_actions)
        layout.addWidget(service_box)

        save = QPushButton("Einstellungen speichern")
        save.setDefault(True)
        save.clicked.connect(self.save)
        layout.addWidget(save, alignment=Qt.AlignRight)
        self._services: list[Service] = []
        self.load()

    def load(self) -> None:
        settings = self.repository.get_settings()
        self.company_name.setText(settings.get("company_name", ""))
        self.company_address.setPlainText(settings.get("company_address", ""))
        self.company_seat.setText(settings.get("company_seat", ""))
        self.company_iban.setText(settings.get("company_iban", ""))
        self.company_bic.setText(settings.get("company_bic", ""))
        self.company_tax_office.setText(settings.get("company_tax_office", ""))
        self.company_tax.setText(settings.get("company_tax_number", ""))
        self.company_phone.setText(settings.get("company_phone", ""))
        self.company_email.setText(settings.get("company_email", ""))
        self.logo.setText(settings.get("company_logo", ""))
        self.output_dir.setText(settings.get("invoice_output_dir", ""))
        self.number_pattern.setText(settings.get("invoice_number_pattern", "RG{number:03d}/{year}"))
        self.next_number.setValue(int(settings.get("next_invoice_number", "1")))
        self.tax_rate.setValue(int(settings.get("invoice_tax_rate", "19")))
        self.ods_name.setText(settings.get("ods_name_cell", "A7"))
        self.ods_street.setText(settings.get("ods_street_cell") or settings.get("ods_address_cell", "A8"))
        self.ods_postal_city.setText(settings.get("ods_postal_city_cell", "A9"))
        self.ods_phone.setText(settings.get("ods_phone_cell", ""))
        self.ods_dogs.setText(settings.get("ods_dogs_cell", ""))
        self.refresh_services()

    def save(self) -> None:
        try:
            required_company_values = (
                self.company_name.text(), self.company_address.toPlainText(), self.company_seat.text(),
                self.company_iban.text(), self.company_bic.text(), self.company_tax_office.text(),
                self.company_tax.text(),
            )
            if any(not value.strip() for value in required_company_values):
                raise ValueError("Bitte alle mit * markierten Firmendaten ausfüllen.")
            self.number_pattern.text().format(year=2026, number=1)
            for field in (self.ods_name, self.ods_street, self.ods_postal_city):
                parse_cell_address(field.text())
            for field in (self.ods_phone, self.ods_dogs):
                if field.text().strip():
                    parse_cell_address(field.text())
            if not self.output_dir.text().strip():
                raise ValueError("Bitte ein PDF-Verzeichnis auswählen.")
        except (KeyError, ValueError) as exc:
            show_error(self, "Ungültige Einstellungen", exc)
            return
        self.repository.save_settings({
            "company_name": self.company_name.text().strip(),
            "company_address": self.company_address.toPlainText().strip(),
            "company_seat": self.company_seat.text().strip(),
            "company_iban": self.company_iban.text().strip(),
            "company_bic": self.company_bic.text().strip(),
            "company_tax_office": self.company_tax_office.text().strip(),
            "company_tax_number": self.company_tax.text().strip(),
            "company_phone": self.company_phone.text().strip(),
            "company_email": self.company_email.text().strip(),
            "company_logo": self.logo.text().strip(),
            "invoice_output_dir": self.output_dir.text().strip(),
            "invoice_number_pattern": self.number_pattern.text().strip(),
            "next_invoice_number": str(self.next_number.value()),
            "invoice_tax_rate": str(self.tax_rate.value()),
            "ods_name_cell": self.ods_name.text().strip().upper(),
            "ods_street_cell": self.ods_street.text().strip().upper(),
            "ods_postal_city_cell": self.ods_postal_city.text().strip().upper(),
            "ods_phone_cell": self.ods_phone.text().strip().upper(),
            "ods_dogs_cell": self.ods_dogs.text().strip().upper(),
        })
        self.settings_changed.emit()
        QMessageBox.information(self, "Gespeichert", "Die Einstellungen wurden gespeichert.")

    def choose_logo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Logo auswählen", "", "Bilder (*.png *.jpg *.jpeg)")
        if path:
            self.logo.setText(path)

    def choose_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "PDF-Verzeichnis auswählen", self.output_dir.text())
        if path:
            self.output_dir.setText(path)

    def refresh_services(self) -> None:
        self._services = self.repository.list_services()
        self.service_table.setRowCount(len(self._services))
        for row, service in enumerate(self._services):
            self.service_table.setItem(row, 0, QTableWidgetItem(service.description))
            item = QTableWidgetItem(cents_to_text(service.standard_price_cents, True))
            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.service_table.setItem(row, 1, item)

    def _selected_service(self) -> Service | None:
        row = self.service_table.currentRow()
        return self._services[row] if 0 <= row < len(self._services) else None

    def add_service(self) -> None:
        dialog = ServiceDialog(self)
        if dialog.exec() == QDialog.Accepted:
            try:
                self.repository.save_service(dialog.value())
            except ValueError as exc:
                show_error(self, "Leistung konnte nicht gespeichert werden", exc)
                return
            self.refresh_services()
            self.settings_changed.emit()

    def edit_service(self) -> None:
        service = self._selected_service()
        if not service:
            return
        dialog = ServiceDialog(self, service)
        if dialog.exec() == QDialog.Accepted:
            self.repository.save_service(dialog.value())
            self.refresh_services()
            self.settings_changed.emit()

    def delete_service(self) -> None:
        service = self._selected_service()
        if not service:
            return
        if QMessageBox.question(self, "Leistung löschen", f"„{service.description}“ wirklich löschen?") == QMessageBox.Yes:
            self.repository.delete_service(service.id or 0)
            self.refresh_services()
            self.settings_changed.emit()


class InvoiceDialog(QDialog):
    def __init__(
        self, parent: QWidget, repository: Repository, invoice: Invoice | None = None,
        customer_id: int | None = None,
    ):
        super().__init__(parent)
        self.repository = repository
        self.invoice = invoice
        self.initial_customer_id = customer_id
        self.saved_invoice: Invoice | None = None
        self.setWindowTitle("Rechnung bearbeiten" if invoice else "Neue Rechnung")
        self.resize(900, 650)
        layout = QVBoxLayout(self)
        form = QGridLayout()
        form.addWidget(QLabel("Kunde *"), 0, 0)
        self.customer_combo = QComboBox()
        self.customer_combo.setEditable(True)
        self.customer_combo.setInsertPolicy(QComboBox.NoInsert)
        self.customer_combo.lineEdit().setPlaceholderText("Name oder Hundename eingeben …")
        form.addWidget(self.customer_combo, 0, 1, 1, 3)
        form.addWidget(QLabel("Rechnungsnummer *"), 1, 0)
        self.number = QLineEdit()
        self.number.editingFinished.connect(self.check_number)
        form.addWidget(self.number, 1, 1)
        form.addWidget(QLabel("Rechnungsdatum *"), 1, 2)
        self.invoice_date = QDateEdit()
        self.invoice_date.setCalendarPopup(True)
        self.invoice_date.setDisplayFormat("dd.MM.yyyy")
        form.addWidget(self.invoice_date, 1, 3)
        form.setColumnStretch(1, 1)
        form.setColumnStretch(3, 1)
        layout.addLayout(form)

        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        layout.addWidget(divider)
        item_top = QHBoxLayout()
        item_top.addWidget(QLabel("Rechnungspositionen"))
        item_top.addStretch()
        add_item = QPushButton("Position hinzufügen")
        add_item.clicked.connect(self.add_item)
        item_top.addWidget(add_item)
        layout.addLayout(item_top)
        self.items = QTableWidget(0, 6)
        self.items.setHorizontalHeaderLabels(["Leistung", "Bezeichnung", "Anzahl", "Einzelpreis netto", "Netto", ""])
        self.items.verticalHeader().setVisible(False)
        self.items.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.items.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.items.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.items.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.items.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.items.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        layout.addWidget(self.items, 1)
        self.total_label = QLabel("Netto: 0,00 € · USt.: 0,00 € · Brutto: 0,00 €")
        self.total_label.setObjectName("invoiceTotal")
        layout.addWidget(self.total_label, alignment=Qt.AlignRight)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Speichern und PDF erstellen")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._load_customers()
        self._load_invoice()

    def _load_customers(self) -> None:
        current_id = self.invoice.customer_id if self.invoice else self.initial_customer_id
        self.customer_combo.clear()
        selected = -1
        for index, customer in enumerate(self.repository.list_customers()):
            self.customer_combo.addItem(customer.display_name, customer.id)
            if customer.id == current_id:
                selected = index
        model = self.customer_combo.model()
        completer = QCompleter(model, self.customer_combo)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        completer.setFilterMode(Qt.MatchContains)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.customer_combo.setCompleter(completer)
        if selected >= 0:
            self.customer_combo.setCurrentIndex(selected)
        elif self.customer_combo.count():
            self.customer_combo.setCurrentIndex(0)

    def _load_invoice(self) -> None:
        if self.invoice:
            self.number.setText(self.invoice.number)
            self.invoice_date.setDate(QDate(self.invoice.invoice_date.year, self.invoice.invoice_date.month, self.invoice.invoice_date.day))
            for item in self.invoice.items:
                self.add_item(item)
        else:
            number, _ = self.repository.suggested_invoice_number()
            self.number.setText(number)
            self.invoice_date.setDate(QDate.currentDate())
            if self.repository.list_services():
                self.add_item()

    def add_item(self, existing: InvoiceItem | None = None) -> None:
        services = self.repository.list_services()
        if not services and existing is None:
            show_error(self, "Keine Leistungen", "Bitte zuerst in den Einstellungen mindestens eine Leistung anlegen.")
            return
        row = self.items.rowCount()
        self.items.insertRow(row)
        service_combo = QComboBox()
        selected = 0
        for index, service in enumerate(services):
            service_combo.addItem(service.description, service.id)
            if existing and service.id == existing.service_id:
                selected = index
        if existing and existing.service_id is None:
            service_combo.insertItem(0, "Individuell", None)
            selected = 0
        service_combo.setCurrentIndex(selected)
        self.items.setCellWidget(row, 0, service_combo)
        selected_service = services[selected] if services and selected < len(services) else None
        description = existing.description if existing else (selected_service.description if selected_service else "")
        price_cents = existing.unit_price_cents if existing else (selected_service.standard_price_cents if selected_service else 0)
        description_item = QTableWidgetItem(description)
        self.items.setItem(row, 1, description_item)
        quantity = QSpinBox()
        quantity.setRange(1, 9999)
        quantity.setValue(existing.quantity if existing else 1)
        self.items.setCellWidget(row, 2, quantity)
        price = QLineEdit(cents_to_text(price_cents))
        price.setMaximumWidth(100)
        self.items.setCellWidget(row, 3, price)
        total = QTableWidgetItem(cents_to_text((existing.quantity if existing else 1) * price_cents, True))
        total.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.items.setItem(row, 4, total)
        remove = QPushButton("Entfernen")
        self.items.setCellWidget(row, 5, remove)
        service_combo.currentIndexChanged.connect(lambda _index, combo=service_combo: self._service_changed(combo))
        quantity.valueChanged.connect(self.update_totals)
        price.textChanged.connect(self.update_totals)
        remove.clicked.connect(lambda _checked=False, button=remove: self._remove_row(button))
        self.update_totals()

    def _row_for_widget(self, widget: QWidget) -> int:
        for row in range(self.items.rowCount()):
            for column in range(self.items.columnCount()):
                if self.items.cellWidget(row, column) is widget:
                    return row
        return -1

    def _service_changed(self, combo: QComboBox) -> None:
        row = self._row_for_widget(combo)
        if row < 0:
            return
        service_id = combo.currentData()
        service = next((entry for entry in self.repository.list_services() if entry.id == service_id), None)
        if service:
            self.items.item(row, 1).setText(service.description)
            price = self.items.cellWidget(row, 3)
            if isinstance(price, QLineEdit):
                price.setText(cents_to_text(service.standard_price_cents))
        self.update_totals()

    def _remove_row(self, button: QPushButton) -> None:
        row = self._row_for_widget(button)
        if row >= 0:
            self.items.removeRow(row)
            self.update_totals()

    def update_totals(self) -> None:
        total_cents = 0
        for row in range(self.items.rowCount()):
            quantity = self.items.cellWidget(row, 2)
            price = self.items.cellWidget(row, 3)
            try:
                cents = text_to_cents(price.text()) if isinstance(price, QLineEdit) else 0
            except ValueError:
                cents = 0
            count = quantity.value() if isinstance(quantity, QSpinBox) else 0
            row_total = count * cents
            total_cents += row_total
            item = self.items.item(row, 4)
            if item:
                item.setText(cents_to_text(row_total, True))
        if self.invoice:
            tax_rate = self.invoice.tax_rate_percent
        else:
            tax_rate = int(self.repository.get_settings().get("invoice_tax_rate", "19"))
        tax_cents = (total_cents * tax_rate + 50) // 100
        self.total_label.setText(
            f"Netto: {cents_to_text(total_cents, True)} · USt. {tax_rate} %: "
            f"{cents_to_text(tax_cents, True)} · Brutto: {cents_to_text(total_cents + tax_cents, True)}"
        )

    def check_number(self) -> None:
        if self.repository.invoice_number_exists(self.number.text().strip(), self.invoice.id if self.invoice else None):
            QMessageBox.warning(self, "Doppelte Rechnungsnummer", "Diese Rechnungsnummer ist bereits vergeben.")

    def _value(self) -> Invoice:
        customer_id = self.customer_combo.currentData()
        current_index = self.customer_combo.currentIndex()
        selected_text = self.customer_combo.itemText(current_index) if current_index >= 0 else ""
        if customer_id is None or self.customer_combo.currentText().strip() != selected_text:
            raise ValueError("Bitte einen Kunden aus der Liste auswählen.")
        customer = self.repository.get_customer(int(customer_id))
        if not customer:
            raise ValueError("Der ausgewählte Kunde wurde nicht gefunden.")
        number = self.number.text().strip()
        if not number:
            raise ValueError("Bitte eine Rechnungsnummer eingeben.")
        items: list[InvoiceItem] = []
        for row in range(self.items.rowCount()):
            combo = self.items.cellWidget(row, 0)
            quantity = self.items.cellWidget(row, 2)
            price = self.items.cellWidget(row, 3)
            description = self.items.item(row, 1).text().strip()
            if not description:
                raise ValueError(f"In Position {row + 1} fehlt die Bezeichnung.")
            items.append(InvoiceItem(
                description=description,
                quantity=quantity.value() if isinstance(quantity, QSpinBox) else 1,
                unit_price_cents=text_to_cents(price.text() if isinstance(price, QLineEdit) else ""),
                service_id=combo.currentData() if isinstance(combo, QComboBox) else None,
            ))
        if not items:
            raise ValueError("Bitte mindestens eine Rechnungsposition hinzufügen.")
        selected_qdate = self.invoice_date.date()
        selected_date = date(selected_qdate.year(), selected_qdate.month(), selected_qdate.day())
        sequence = self.invoice.sequence_value if self.invoice else None
        if self.invoice is None:
            suggested, suggested_sequence = self.repository.suggested_invoice_number(selected_date)
            if number == suggested:
                sequence = suggested_sequence
        return Invoice(
            number=number, invoice_date=selected_date, customer_id=customer.id or 0,
            customer_name=customer.name, customer_address=customer.address,
            customer_phone=customer.phone, customer_dog_names=customer.dog_names,
            items=items, sequence_value=sequence,
            pdf_path=self.invoice.pdf_path if self.invoice else "", id=self.invoice.id if self.invoice else None,
            tax_rate_percent=(self.invoice.tax_rate_percent if self.invoice else
                              int(self.repository.get_settings().get("invoice_tax_rate", "19"))),
        )

    def save(self) -> None:
        try:
            invoice = self._value()
            self.repository.save_invoice(invoice)
        except (ValueError, DuplicateInvoiceNumberError, sqlite3.IntegrityError) as exc:
            show_error(self, "Rechnung konnte nicht gespeichert werden", exc)
            return
        try:
            path = generate_invoice_pdf(invoice, self.repository.get_settings())
            invoice.pdf_path = str(path)
            self.repository.save_invoice(invoice)
        except Exception as exc:
            QMessageBox.warning(
                self, "Rechnung gespeichert, PDF fehlgeschlagen",
                f"Die Rechnung wurde gespeichert, das PDF konnte aber nicht erstellt werden:\n\n{exc}",
            )
            self.saved_invoice = invoice
            self.accept()
            return
        self.saved_invoice = invoice
        self.accept()


class InvoicesWidget(QWidget):
    def __init__(self, repository: Repository):
        super().__init__()
        self.repository = repository
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Rechnungsnummer oder Kunde suchen …")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        new_invoice = QPushButton("Neue Rechnung")
        new_invoice.setObjectName("primaryButton")
        new_invoice.clicked.connect(self.new_invoice)
        self.edit_button = QPushButton("Bearbeiten")
        self.edit_button.clicked.connect(self.edit_invoice)
        self.open_pdf_button = QPushButton("PDF öffnen")
        self.open_pdf_button.clicked.connect(self.open_pdf)
        self.whatsapp_button = QPushButton("Über WhatsApp teilen")
        self.whatsapp_button.clicked.connect(self.share_whatsapp)
        self.regenerate_button = QPushButton("PDF neu erzeugen")
        self.regenerate_button.clicked.connect(self.regenerate_pdf)
        for button in (
            self.edit_button, self.open_pdf_button, self.whatsapp_button, self.regenerate_button,
        ):
            button.setEnabled(False)
        top.addWidget(self.search, 1)
        top.addWidget(new_invoice)
        top.addWidget(self.edit_button)
        top.addWidget(self.open_pdf_button)
        top.addWidget(self.whatsapp_button)
        top.addWidget(self.regenerate_button)
        layout.addLayout(top)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Rechnungsnummer", "Datum", "Kunde", "Betrag", "PDF"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.doubleClicked.connect(self.edit_invoice)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        layout.addWidget(self.table, 1)
        self._invoices: list[Invoice] = []
        self.refresh()

    def refresh(self) -> None:
        self._invoices = self.repository.list_invoices(self.search.text())
        self.table.setRowCount(len(self._invoices))
        for row, invoice in enumerate(self._invoices):
            values = [
                invoice.number, invoice.invoice_date.strftime("%d.%m.%Y"), invoice.customer_name,
                cents_to_text(invoice.total_cents, True), "Vorhanden" if invoice.pdf_path and Path(invoice.pdf_path).is_file() else "Fehlt",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 3:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(row, column, item)
        self._selection_changed()

    def _selected(self) -> Invoice | None:
        row = self.table.currentRow()
        return self._invoices[row] if 0 <= row < len(self._invoices) else None

    def _selection_changed(self) -> None:
        invoice = self._selected()
        selected = invoice is not None
        has_pdf = bool(invoice and invoice.pdf_path and Path(invoice.pdf_path).is_file())
        self.edit_button.setEnabled(selected)
        self.regenerate_button.setEnabled(selected)
        self.open_pdf_button.setEnabled(has_pdf)
        self.whatsapp_button.setEnabled(has_pdf)

    def new_invoice(self) -> None:
        if not self.repository.list_customers():
            show_error(self, "Keine Kunden", "Bitte zuerst einen Kunden anlegen.")
            return
        dialog = InvoiceDialog(self, self.repository)
        if dialog.exec() == QDialog.Accepted:
            self.refresh()

    def edit_invoice(self) -> None:
        invoice = self._selected()
        if not invoice:
            return
        dialog = InvoiceDialog(self, self.repository, self.repository.get_invoice(invoice.id or 0))
        if dialog.exec() == QDialog.Accepted:
            self.refresh()

    def regenerate_pdf(self) -> None:
        invoice = self._selected()
        if not invoice:
            return
        try:
            path = generate_invoice_pdf(invoice, self.repository.get_settings())
            invoice.pdf_path = str(path)
            self.repository.save_invoice(invoice)
        except Exception as exc:
            show_error(self, "PDF konnte nicht erstellt werden", exc)
            return
        self.refresh()
        QMessageBox.information(self, "PDF erstellt", f"Das PDF wurde gespeichert:\n{path}")

    def open_pdf(self) -> None:
        invoice = self._selected()
        if not invoice:
            return
        path = Path(invoice.pdf_path) if invoice.pdf_path else None
        if not path or not path.is_file():
            show_error(self, "PDF nicht gefunden", "Bitte das PDF zuerst neu erzeugen.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def share_whatsapp(self) -> None:
        invoice = self._selected()
        if not invoice:
            return
        path = Path(invoice.pdf_path) if invoice.pdf_path else None
        if not path or not path.is_file():
            show_error(self, "PDF nicht gefunden", "Bitte das PDF zuerst neu erzeugen.")
            return
        company_name = self.repository.get_settings().get("company_name", "").strip()
        message = f"Rechnung {invoice.number}"
        if company_name:
            message += f" von {company_name}"
        message += f" über {cents_to_text(invoice.total_cents, True)}"
        QDesktopServices.openUrl(QUrl(f"https://wa.me/?text={quote(message)}"))
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
        QApplication.clipboard().setText(str(path))
        QMessageBox.information(
            self,
            "PDF über WhatsApp teilen",
            f"WhatsApp Web und der PDF-Ordner wurden geöffnet.\n\n"
            f"Wähle in WhatsApp den Kontakt und füge über die Büroklammer diese Datei hinzu:\n{path.name}\n\n"
            "Der vollständige Dateipfad wurde außerdem in die Zwischenablage kopiert.",
        )


class MainWindow(QMainWindow):
    def __init__(self, repository: Repository):
        super().__init__()
        self.repository = repository
        self.setWindowTitle("Mosrechnung")
        self.resize(1050, 720)
        self.tabs = QTabWidget()
        self.invoices = InvoicesWidget(repository)
        self.customers = CustomersWidget(repository)
        self.settings = SettingsWidget(repository)
        self.tabs.addTab(self.invoices, "Rechnungen")
        self.tabs.addTab(self.customers, "Kunden")
        self.tabs.addTab(self.settings, "Einstellungen")
        self.customers.invoice_created.connect(self.invoices.refresh)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.setCentralWidget(self.tabs)
        data_menu = self.menuBar().addMenu("Daten")
        export_action = data_menu.addAction("Backup sichern …")
        export_action.triggered.connect(self.export_data)
        import_action = data_menu.addAction("Backup einlesen …")
        import_action.triggered.connect(self.import_data)

    def _tab_changed(self, index: int) -> None:
        if self.tabs.widget(index) is self.customers:
            self.customers.ensure_loaded()

    def export_data(self) -> None:
        suggested = str(Path.home() / f"mosrechnung-backup-{date.today().isoformat()}.json")
        path, _ = QFileDialog.getSaveFileName(
            self, "Backup sichern", suggested, "Mosrechnung-Backup (*.json)"
        )
        if not path:
            return
        if not path.casefold().endswith(".json"):
            path += ".json"
        try:
            export_backup(self.repository, path)
        except Exception as exc:
            show_error(self, "Backup konnte nicht erstellt werden", exc)
            return
        QMessageBox.information(self, "Backup erstellt", f"Das Backup wurde gespeichert:\n{path}")

    def import_data(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Backup einlesen", "", "Mosrechnung-Backup (*.json)"
        )
        if not path:
            return
        answer = QMessageBox.warning(
            self,
            "Datenbestand ersetzen",
            "Der aktuelle lokale Datenbestand wird vollständig durch das Backup ersetzt. Fortfahren?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            import_backup(self.repository, path)
        except Exception as exc:
            show_error(self, "Backup konnte nicht eingelesen werden", exc)
            return
        self.customers.refresh()
        self.invoices.refresh()
        self.settings.load()
        QMessageBox.information(self, "Backup eingelesen", "Der Datenbestand wurde vollständig wiederhergestellt.")


STYLE = """
QWidget { font-size: 14px; }
QMainWindow { background: #f7f8f9; }
QTabWidget::pane { border: 0; background: white; }
QTabBar::tab { padding: 10px 22px; }
QTabBar::tab:selected { color: #1f4e5f; border-bottom: 2px solid #1f4e5f; }
QPushButton { min-height: 24px; padding: 9px 16px; }
QPushButton#primaryButton { background: #1f4e5f; color: white; border: 0; border-radius: 3px; }
QLineEdit, QTextEdit, QComboBox, QDateEdit, QSpinBox { min-height: 22px; padding: 6px; }
QTableWidget, QTableView { border: 1px solid #d7dee2; gridline-color: #e8ecee; }
QHeaderView::section { background: #eef2f4; padding: 7px; border: 0; border-bottom: 1px solid #d7dee2; }
QLabel#invoiceTotal { font-size: 18px; font-weight: bold; color: #1f4e5f; padding: 8px; }
QGroupBox { font-weight: bold; margin-top: 12px; padding-top: 12px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
"""


def configure_application(application: QApplication) -> None:
    application.setApplicationName("Mosrechnung")
    application.setOrganizationName("Mosrechnung")
    application.setStyle("Fusion")
    application.setStyleSheet(STYLE)
