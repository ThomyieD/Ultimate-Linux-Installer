# TASK-004 – Gate-E-Fehler vor dem Wipe abfangen und diagnostizierbar machen

Status: READY_FOR_CURSOR

Priorität: P0 / blockiert Gate E für Debian und weitere Hardwaretests

Owner: Cursor

Reviewer: Codex/Sol

Baseline: `a4c20ac`

## Ziel

Eine frische einfache Debian-13-Serverkonfiguration muss auf einer 40-GiB-
Testdisk einen ausführbaren Standardplan erzeugen, die offizielle Debian-
Standardauswahl ohne das nicht existente Paket `task-standard` installieren
und Paketauflösungsfehler vor dem ersten Wipe erkennen. Falls ein späterer
Fehler dennoch auftritt, muss ein vollständiges, geheimnisfreies Protokoll
auffindbar und über die lokale UI herunterladbar sein.

## Ausgangssituation und Belege

Der Gate-E-Lauf des unter TASK-001 gebauten ISO
`cf9fe39c5d2bbff58b2eb75995412639b20532249ecfe7502d0569c4846f24c7`
hat zwei voneinander unabhängige Fehler nachgewiesen.

### VMware mit 40 GiB

Die Testdisk wird als `/dev/sda` mit 40 GiB korrekt erkannt. Der frische
Wizardzustand fordert jedoch standardmäßig gleichzeitig:

- 1 GiB ESP
- 1 GiB Sicherheitsreserve
- 8 GiB Swap
- 64 GiB optionale gemeinsame Datenpartition
- mindestens 20 GiB Debian-Root

Damit verlangt der Standardzustand mindestens etwa 94 GiB und endet mit
`Disk too small for the requested layout`. Ursache sind die doppelten Defaults
`include_data=true` und `data_size_mib=65536` in `app/uli/web/server.py` sowie
`app/uli/web/static/app.js`; die Plattenerkennung ist nicht die Ursache.

### Debian-13-Server auf dem Laptop

Der Lauf erreicht 59 Prozent und protokolliert vor dem Wipe erfolgreich:

```text
verified sources: debian-trixie-InRelease
pre-wipe GRUB build verified (7 commands)
partition table and filesystems created; UUIDs refreshed
```

Anschließend scheitert die Paketinstallation mit:

```text
E: Unable to locate package task-standard
```

`app/uli/install/provision.py` verwendet `task-standard` für Debian Server
und Desktop. Debian 13 stellt dieses Paket nicht bereit. Debians `standard`-
Task ist ein besonderer tasksel-Task auf Basis der Paketprioritäten; das echte
Desktop-Metapaket `task-gnome-desktop` existiert dagegen.

Offizielle Referenzen:

- `https://wiki.debian.org/tasksel` (Abschnitt `standard task`)
- `https://sources.debian.org/src/tasksel/3.81/tasks/standard/`
- `https://packages.debian.org/trixie/tasksel`
- `https://packages.debian.org/trixie/task-gnome-desktop`
- `https://www.debian.org/releases/trixie/amd64/apbs04.en.html#pkgsel`

### Diagnose

`app/uli/install/job.py` hält höchstens 500 Zeilen nur im Speicher und die
Status-API liefert davon lediglich die letzten 80. Die UI klappt diesen
Ausschnitt bei Fehlern auf; eine dauerhafte vollständige Logdatei und ein
Download fehlen. Nach einem Neustart ist der Speicherinhalt verloren.

## Abhängigkeiten

- TASK-001: Code-Review und Gate D bestanden; Gate E hat die obigen
  Folgebefunde geliefert.

## Scope

### 1. Sicherer Standardplan für kleine Testdisks

1. In einem **frischen** Backend- und Frontend-Wizardzustand bleibt Swap mit
   8 GiB aktiviert, die optionale gemeinsame Datenpartition ist aber
   deaktiviert. Der ruhende Wert von 64 GiB darf für ein späteres bewusstes
   Aktivieren erhalten bleiben.
2. Bereits gespeicherte oder ausdrücklich gesendete Einstellungen werden nicht
   automatisch verändert: ein bewusst aktiviertes 64-GiB-Datenvolume muss auf
   einer 40-GiB-Disk weiterhin fail-closed abgelehnt werden.
3. Kapazitätsfehler erhalten im Storage-Modell einen stabilen Fehlercode sowie
   `required_mib` und `available_mib`. Die API darf für diesen bekannten Fall
   keinen internen englischen Exceptiontext als Nutzertext durchreichen.
4. Die UI rendert den Fehler auf Deutsch beziehungsweise Englisch mit
   benötigter und vorhandener Größe und nennt Daten-/Swapgröße als änderbare
   Ursache. Es erfolgt kein automatisches Verkleinern expliziter Werte.

### 2. Korrekte Debian-Standardauswahl

1. `task-standard` vollständig aus dem Debian-Produktpfad entfernen.
2. Für Debian Server und Desktop das echte Paket `tasksel` installieren und
   danach im Ziel-Chroot den offiziellen Task `standard` nichtinteraktiv über
   `tasksel install standard` ausführen.
3. Debian Desktop installiert zusätzlich weiterhin das echte Paket
   `task-gnome-desktop`; Debian Server erhält kein Desktop-Metapaket.
4. Jeder Exitcode ungleich 0 bleibt fatal. Keine Fallback-Paketliste, kein
   `|| true` und kein Überspringen des Standard-Tasks.

### 3. Paketauflösung vor dem Wipe

1. Im Realmodus vor `StorageGuard.apply_plan()` für jede eindeutige
   Distributionsquelle eine isolierte APT-Prüfung ausführen:
   - eigene temporäre `Dir`-, Listen-, Cache- und Statuspfade unter dem
     geschützten Job-Arbeitsverzeichnis,
   - Architektur `amd64`, exakt die im gebundenen Plan verwendeten HTTPS-
     Quellen und den festgelegten `signed-by`-Keyring,
   - `apt-get update` und anschließend eine reine Simulation der vollständigen
     namentlichen Paketmenge für die gewählte Variante,
   - keinerlei Schreiben in `/etc/apt`, `/var/lib/apt`, die Host-dpkg-Datenbank
     oder einen Zieldatenträger.
2. Zur simulierten Debian-Paketmenge gehören mindestens `tasksel` und bei
   Desktop `task-gnome-desktop`. Der besondere `standard`-Task wird nach dem
   Bootstrap wie oben beschrieben durch tasksel ausgeführt.
3. Die Prüfung verwendet die normale APT-Signaturvalidierung. Unsichere oder
   nicht authentifizierte Repositories bleiben verboten.
4. Update-, Signatur- oder Auflösungsfehler stoppen die Installation vor dem
   Wipe mit einer verständlichen Fehlermeldung. Dry-Runs und Unit-Tests führen
   keinen echten Netzwerkzugriff aus.
5. Temporäre APT-Daten werden sicher bereinigt; im Jobprotokoll bleibt ein
   knapper positiver oder negativer Nachweis ohne Repository-Inhalte.

### 4. Vollständiges Fehlerprotokoll

1. Sobald das geschützte Job-Arbeitsverzeichnis feststeht, jede neue
   Installations- und Tracebackzeile zusätzlich nach
   `<artifact_dir>/install.log` schreiben. Die Datei hat Modus `0600` und wird
   bei einem terminalen Erfolg oder Fehler nicht gelöscht.
2. Passwort, Passwort-Hash, SSH-Schlüssel und sonstige Secret-Eingaben dürfen
   weder in dieser Datei noch in API-Antworten erscheinen. Die bestehende
   In-Memory-Begrenzung darf erhalten bleiben.
3. Einen lokalen Read-only-Endpunkt ohne frei wählbaren Pfad bereitstellen,
   der ausschließlich das Log des aktuellen Jobs als `text/plain`-Download
   liefert. Ohne vorhandenes Joblog fail-closed antworten.
4. Auf der Fehlerseite das bereits automatisch geöffnete Kurzprotokoll, den
   konkreten geschützten Pfad und eine deutsch/englisch beschriftete
   Download-Schaltfläche zeigen. Der Download darf keine Installation starten,
   wiederholen oder Konfiguration verändern.

## Nicht-Scope

- Ubuntu-26.04-Bootstrap oder sonstige Arbeiten aus TASK-002
- Änderung der Mindestgröße einer Debian-Rootpartition
- automatische Verkleinerung oder Deaktivierung explizit gewählter Partitionen
- Lockerung von Signatur-, Keyring-, Zielplatten- oder Bestätigungsprüfungen
- `trusted=yes`, `--allow-unauthenticated` oder ähnliche APT-Ausnahmen
- vollständige Wiederaufnahme nach Stromausfall
- ISO-Build, VM-Start, echte Installation, Partitionierung oder Reboot
- neue Produktionsabhängigkeiten
- Commit oder Push

## Erlaubte Dateien

- `app/uli/install/job.py`
- `app/uli/install/provision.py`
- optional `app/uli/install/apt_preflight.py`
- `app/uli/storage/layout.py`
- `app/uli/web/server.py`
- `app/uli/web/static/app.js`
- `app/uli/i18n/de.json`
- `app/uli/i18n/en.json`
- `tests/unit/test_provisioning.py`
- `tests/unit/test_storage_layout.py`
- `tests/unit/test_web_api.py`
- `tests/unit/test_web_static.py`
- optional `tests/unit/test_apt_preflight.py`
- optional `tests/unit/test_install_job.py`
- `ai/handovers/TASK-004.md`

Wenn eine andere Produktdatei erforderlich erscheint: stoppen und den Blocker
im Handover dokumentieren.

## Architektur- und Sicherheitsvorgaben

- ADR-001, ADR-003, ADR-004 und ADR-005 sind bindend.
- Die isolierte APT-Prüfung ist eine zusätzliche Grenze nach der bestehenden
  `verify_plan_sources`-Prüfung und vor `StorageGuard.apply_plan()`. Sie ersetzt
  oder lockert keine bestehende Prüfung.
- Alle externen Prozesse erhalten argv-Listen ohne Shell-Interpolation.
- APT darf weder Hostquellen noch Hoststatus verwenden. Fehler bei der
  Isolation sind fatal und dürfen nicht in einen Host-APT-Aufruf zurückfallen.
- Der bestätigte Plan und seine expliziten Partitionsgrößen bleiben
  unveränderlich; UX-Hinweise ändern den Plan nicht selbsttätig.
- Der Logdownload akzeptiert weder Pfad noch Dateiname vom Client und darf nur
  auf die intern erzeugte `install.log` des aktuellen sicheren Planverzeichnisses
  zugreifen.
- Secrets werden nicht durch pauschales Entfernen nützlicher Diagnosedaten
  geschützt, sondern an den bekannten Eingabegrenzen gezielt redigiert. Tests
  müssen Passwort-Hash und einen vollständigen SSH-Testschlüssel abdecken.

## Akzeptanzkriterien

1. `GET /api/state` eines frischen Wizards meldet `include_data=false`; die
   initiale JavaScript-State-Definition stimmt damit überein.
2. Eine simulierte 40-GiB-Disk mit frischer einfacher Debian-13-Serverauswahl
   liefert einen gültigen Fingerprint und genau ESP, Root und Swap; Root ist
   mindestens 20 GiB und keine Datenpartition wird angelegt.
3. Dieselbe Konfiguration mit bewusst aktivierter 64-GiB-Datenpartition liefert
   keinen Fingerprint, sondern `disk_too_small` mit korrekten positiven
   `required_mib`-/`available_mib`-Werten und lokalisierter Hilfe.
4. Kein Produktcode und kein Regressionstest enthält `task-standard`.
5. Der Debian-Server-Befehlsplan installiert `tasksel`, führt danach exakt den
   Task `standard` aus und enthält kein Desktop-Metapaket. Der Desktopplan tut
   dasselbe und installiert zusätzlich `task-gnome-desktop`.
6. Ein Unit-Test beweist die Reihenfolge `tasksel`-Paketinstallation vor
   `tasksel install standard`; ein simulierter Fehler des Task-Aufrufs wird
   nicht verschluckt.
7. Ein Realmodus-Test mit vollständig gemockten Prozessen beweist, dass
   APT-Update und Paketauflösung vor dem ersten `StorageGuard`-Aufruf liegen,
   isolierte Pfade verwenden und ein Fehler exakt null destruktive Aufrufe
   hinterlässt.
8. Negative Tests beweisen, dass unsichere APT-Optionen nicht vorkommen und
   Dry-Run/Unit-Tests keinen Netzwerkprozess starten.
9. Ein absichtlich fehlgeschlagener Job erzeugt eine vollständige
   `install.log` mit Modus `0600`; API und UI bieten genau diese Datei an.
   Passwort-Hash und SSH-Testschlüssel fehlen in Log, Statusantwort und
   Downloadinhalt.
10. `./scripts/check.sh` ist vollständig grün und Cursor dokumentiert den noch
    erforderlichen neuen ISO-Build sowie Gate D/E ausdrücklich im Handover.

## Tests

Mindestens:

```bash
./scripts/check.sh
pytest -q \
  tests/unit/test_provisioning.py \
  tests/unit/test_storage_layout.py \
  tests/unit/test_web_api.py \
  tests/unit/test_web_static.py
```

Zusätzlich jede neu angelegte fokussierte Testdatei separat ausführen. Alle
externen APT-/Netzwerkaufrufe müssen in automatisierten Tests gemockt sein.

## Definition of Done

- alle Akzeptanzkriterien nachweisbar erfüllt
- keine Änderung außerhalb der erlaubten Dateien
- keine Sicherheitsprüfung gelockert und kein Secret protokolliert
- vollständiger Handover unter `ai/handovers/TASK-004.md`
- kein ISO-Build, keine VM, keine echte Installation, kein Commit und kein Push
