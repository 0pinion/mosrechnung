# Mosrechnung

Mosrechnung ist eine bewusst einfache native Linux-Anwendung zum Verwalten von
Kunden und zum Erstellen von PDF-Rechnungen. Die Oberfläche basiert auf Qt
Widgets, die Daten liegen lokal in SQLite und die PDF-Dateien werden mit
ReportLab erzeugt.

## Funktionen

- Kundenverwaltung mit Name, Straße/Hausnummer, PLZ, Ort, Telefon und Hundenamen
- einmaliger Import aus LibreOffice-Calc-Dateien mit einem Tabellenblatt pro Rechnung
- automatische Dublettenerkennung anhand normalisierter Kundennamen
- durchsuchbare Kundenauswahl bei der Rechnungserstellung
- vordefinierte Leistungen mit je Rechnung überschreibbaren Preisen
- konfigurierbare und automatisch fortlaufende Rechnungsnummern
- automatische Netto-, Umsatzsteuer- und Bruttoberechnung mit gespeichertem Steuersatz
- mehrseitige PDF-Rechnungen mit wiederholten Tabellenköpfen und Seitenzahlen
- Rechnungshistorie, nachträgliche Bearbeitung und erneute PDF-Erzeugung
- gemeinsames JSON-Backup für Datenaustausch mit der iPhone-WebApp

## Backup und iPhone-WebApp

Unter **Daten → Backup sichern …** wird ein versioniertes JSON-Backup mit Kunden,
Leistungen, Rechnungen, Firmendaten und Logo erstellt. Diese Datei kann in der
iPhone-WebApp über **Backup einlesen** vollständig wiederhergestellt werden.

Umgekehrt lassen sich Backups der WebApp unter **Daten → Backup einlesen …** in
die Python-Anwendung übernehmen. Der Import prüft zuerst die komplette Datei und
ersetzt anschließend Kunden, Leistungen und Rechnungen innerhalb einer einzigen
Datenbanktransaktion. Python-spezifische Einstellungen wie PDF-Ausgabeverzeichnis
und Calc-Zelladressen bleiben dabei erhalten.

Die Backup-Datei enthält personenbezogene Daten unverschlüsselt. Sie sollte nur
in einem durch das Betriebssystem geschützten Speicher liegen und weder in das
öffentliche GitHub-Repository eingecheckt noch ungeschützt versendet werden.

## Entwicklung

Vorausgesetzt werden Python 3.10 oder neuer und die in `pyproject.toml`
aufgeführten Abhängigkeiten.

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[test]'
.venv/bin/mosrechnung
```

Tests starten:

```sh
.venv/bin/pytest
```

Die Datenbank wird gemäß XDG-Konvention standardmäßig unter
`~/.local/share/mosrechnung/mosrechnung.sqlite3` gespeichert. Das Verzeichnis
für die PDFs lässt sich in der Anwendung einstellen.

## Calc-Import

Für den Import sind standardmäßig **A7** (Name), **A8** (Straße und Hausnummer)
und **A9** (PLZ und Ort, durch ein Leerzeichen getrennt) eingestellt. Die
Zelladressen für diese Felder sowie optional Telefon und Hundename(n) können
unter **Einstellungen → Calc-Import** geändert werden. Danach wird unter
**Kunden → Aus Calc importieren** die `.ods`-Datei ausgewählt. Jedes
Tabellenblatt wird einmal gelesen.

Kundennamen werden für den Vergleich Unicode-normalisiert, von mehrfachen
Leerzeichen bereinigt und ohne Beachtung der Groß-/Kleinschreibung verglichen.
Ein bereits vorhandener Kunde wird nicht erneut angelegt; bislang leere
Zusatzdaten werden beim Import ergänzt.

Neue Installationen verwenden Rechnungsnummern im Format `RG001/2026`. Format,
Startnummer und Umsatzsteuersatz sind in den Einstellungen anpassbar; die
Rechnungsnummer selbst bleibt bei jeder Rechnung editierbar.

## Ubuntu-Paket bauen

Auf Ubuntu werden zum Bauen lediglich `dpkg-dev` und die Laufzeitabhängigkeiten
benötigt:

```sh
sudo apt install dpkg-dev python3-reportlab python3-odf
./packaging/build-deb.sh
sudo apt install ./dist/mosrechnung_0.1.4_all.deb
```

Das Paket bevorzugt PySide6 auf Ubuntu 26.04 und neuer. Auf Ubuntu 22.04 und
24.04 verwendet es automatisch die dort angebotenen PySide2-/Qt-5-Pakete; die
Anwendungsfunktionen sind identisch.

Danach ist Mosrechnung im Anwendungsmenü und über den Befehl `mosrechnung`
verfügbar. Die Deinstallation entfernt bewusst nicht die persönliche Datenbank
oder erzeugte PDFs.
