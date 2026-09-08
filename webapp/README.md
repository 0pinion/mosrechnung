# MosRechnung WebApp

Diese Version ist eine lokale WebApp ohne Backend und ohne Cloud. Sie besteht nur aus statischen Dateien:

- `index.html`
- `styles.css`
- `app.js`
- `manifest.webmanifest`

## Technologien

- Vanilla HTML/CSS/JavaScript
- IndexedDB als lokaler Browser-Speicher
- Browser-Druckdialog fuer PDF-Erzeugung

Es gibt keinen Servercode und keine externe Datenbank. Kunden, Leistungen, Rechnungen, Einstellungen und Logo werden im Browserprofil des jeweiligen Geraets gespeichert.

## Sicherheitsmodell

- GitHub Pages oder Cloudflare Pages liefern ausschließlich statische Dateien aus.
- Es gibt kein Backend, keine Anmeldung, keine Cookies, keine Telemetrie und keine externen Skripte.
- Eine restriktive Content Security Policy blockiert Netzwerkzugriffe der App und fremde Inhalte.
- Kundendaten werden nie an den Webhost übertragen. Sie liegen in der von Safari isolierten IndexedDB der App-Origin.
- Backups sind normale, unverschlüsselte JSON-Dateien. Sie müssen in einem durch iOS beziehungsweise iCloud geschützten Speicher liegen und dürfen nicht öffentlich geteilt werden.

Absolute Risikofreiheit ist technisch nicht möglich. Das verbleibende Hauptrisiko ist der Zugriff auf ein entsperrtes iPhone oder eine exportierte Backup-Datei. Die App implementiert absichtlich weder eigene Anmeldung noch eigene Kryptografie.

## Lokal starten

Auf einem Rechner im Projektordner:

```sh
python3 -m http.server 8080 -d webapp
```

Dann im Browser oeffnen:

```text
http://localhost:8080
```

Im selben WLAN kann das iPhone die App ueber die IP-Adresse des Rechners oeffnen, zum Beispiel:

```text
http://192.168.178.20:8080
```

Danach kann die Seite in Safari ueber Teilen > Zum Home-Bildschirm als App-Symbol abgelegt werden. Die Daten bleiben lokal auf dem iPhone in Safari/der Homescreen-WebApp. Fuer die dauerhafte Installation muss die Seite einmal per HTTPS von GitHub Pages oder Cloudflare Pages geladen werden; der Service Worker hält sie danach offline verfügbar.

## Veröffentlichung

Die veröffentlichte App ist erreichbar unter:

<https://0pinion.github.io/mosrechnung/>

Der GitHub-Actions-Workflow veröffentlicht Änderungen an `webapp/` automatisch auf GitHub Pages. Die Quelle **GitHub Actions** ist im Repository bereits aktiviert. Künftige Änderungen werden nach einem Push auf den Branch `main` automatisch veröffentlicht.

Auf dem iPhone die Adresse einmal in Safari öffnen und dann **Teilen → Zum Home-Bildschirm** wählen. Danach startet MosRechnung wie eine App und ist durch den Service Worker auch ohne Netzwerkverbindung verfügbar. Für Aktualisierungen die App bei bestehender Internetverbindung einmal neu öffnen.

Cloudflare Pages kann alternativ das Repository direkt verwenden:

- Build command: leer
- Build output directory: `webapp`

Cloudflare wertet zusätzlich `_headers` aus. Auf GitHub Pages werden die wesentlichen Regeln über die CSP im HTML gesetzt; zusätzliche HTTP-Header kann GitHub Pages nicht projektspezifisch konfigurieren.

## Speicherung, Backup und Wiederherstellung

Die Daten liegen lokal in IndexedDB. Das ist fuer diese Ein-Geraet-Nutzung passend, aber nicht dasselbe wie eine Datei im Finder.

Wichtig:

- Safari-Daten nicht loeschen, sonst sind die App-Daten weg.
- Bei iOS-Backups sollten Safari/WebApp-Daten mitgesichert werden.
- In der App regelmaessig `Backup sichern` verwenden und die Datei geschützt in der Dateien-App beziehungsweise iCloud Drive ablegen.
- `Backup einlesen` prüft Format und Inhalte vollständig, bevor der lokale Datenbestand atomar ersetzt wird.
- Der Import ersetzt bewusst den kompletten lokalen Datenbestand durch das Backup.

## PDF auf iPhone

In der Rechnungsuebersicht `PDF/Drucken` antippen. Safari oeffnet den Druckdialog; dort kann die Rechnung als PDF geteilt oder gespeichert werden.
