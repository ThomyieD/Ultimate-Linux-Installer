# Review TASK-004 – Iteration 1

Verdict: CHANGES_REQUESTED

Reviewer: Codex/Sol

Geprüfter Stand: uncommittierte Änderungen gegen `786d11c`

Handover: fehlt (`ai/handovers/TASK-004.md` nicht vorhanden)

## Befunde

### P1 – Der Paket-Preflight überspringt Variantenpakete derselben Distribution

`app/uli/install/apt_preflight.py:46-58` reduziert Auswahlen ausschließlich
nach `selection.id`. Bei einem erlaubten Multiboot-Plan mit
`debian:server` vor `debian:desktop` wird deshalb nur die Server-Paketmenge
simuliert. `task-gnome-desktop` wird nicht vorgeprüft, obwohl es nach dem Wipe
installiert werden soll. Damit ist die neue Sicherheitsgrenze aus Scope 3 für
genau den Mehrvariantenfall unvollständig.

Reproduktion des Reviews:

```text
APT_ROOTS 1
DESKTOP_PACKAGE_PREFLIGHTED False
```

Korrektur:

- Pro eindeutiger Quelle darf weiterhin nur ein isolierter APT-Root verwendet
  werden, aber dessen simulierte Paketmenge muss die Vereinigung aller für
  diese Quelle ausgewählten Varianten sein.
- Einen Regressionstest mit `debian:server` **vor** `debian:desktop` ergänzen;
  die Simulation muss unter anderem `tasksel` und `task-gnome-desktop`
  enthalten.

### P1 – Realmodus kann mit einem Dry-Run-Runner fail-open übersprungen werden

`app/uli/install/apt_preflight.py:76-80` behandelt
`dry_run=False` zusammen mit einem injizierten `runner.dry_run=True` als
erfolgreiches Überspringen. Eine widersprüchliche Realmodusverdrahtung darf die
Pre-Wipe-Grenze nicht deaktivieren.

Korrektur:

- Nur der explizite Funktionsparameter `dry_run=True` darf den Netzwerkaufruf
  überspringen.
- Bei `dry_run=False` und Dry-Run-Runner mit `AptPreflightError` abbrechen.
- Einen negativen Test für genau diese Kombination ergänzen.

### P1 – Die vorgeschriebene Architekturbindung fehlt

In `app/uli/install/apt_preflight.py:130-142` fehlt die in TASK-004
ausdrücklich geforderte Bindung an `amd64`. Der Aufruf verlässt sich momentan
auf die Host-/Live-APT-Voreinstellung.

Reproduktion des Reviews:

```text
ARCH_PINNED False
```

Korrektur:

- Den isolierten APT-Aufruf explizit an `APT::Architecture=amd64` und eine
  ausschließliche `APT::Architectures`-Liste für `amd64` binden.
- In den argv-Tests die Architekturbindung für Update und Simulation prüfen.

### P2 – Erforderliche Größe ist bei ungleichen Equal-Root-Minima falsch

`app/uli/storage/layout.py:214-225` summiert die unterschiedlichen
Root-Minima. Bei einer Strategie mit **gleich großen** Rootpartitionen muss
jedoch jede Root mindestens dem größten Einzelminimum entsprechen.

Eine 47-GiB-Disk ohne Swap/Daten mit Debian (20 GiB) und Ubuntu (25 GiB)
ergibt derzeit widersprüchlich:

```text
REQUIRED_MIB 48128
AVAILABLE_MIB 48128
REQUIRED_GT_AVAILABLE False
```

Der tatsächliche Mindestbedarf beträgt 52 GiB: 1 GiB ESP, 1 GiB Reserve und
zweimal 25 GiB Root.

Korrektur:

- Für Equal-Root den Mindestbedarf als
  `fixed_mib + max(root_minima) * number_of_roots` berechnen.
- Den obigen gemischten 47-/52-GiB-Fall als Regressionstest ergänzen und
  `required_mib > available_mib` beweisen.

### P2 – Verbotener Altname bleibt in Produktcode und Regressionstests

Akzeptanzkriterium 4 verlangt, dass weder Produktcode noch Regressionstests
den alten Paketnamen enthalten. `rg` findet ihn weiterhin in:

```text
app/uli/install/apt_preflight.py:161-162
tests/unit/test_provisioning.py:185,583
tests/unit/test_apt_preflight.py:100
```

Korrektur:

- Den Altname aus `app/` und `tests/` vollständig entfernen. Die korrekte
  Paketmenge positiv/exakt prüfen, statt den alten Namen im Produktpfad als
  Sonderfall einzubauen.
- Nachweis: `rg -n <Altname> app tests` liefert keinen Treffer. Der Name darf
  weiterhin nur in Task-/Reviewdokumenten zur Fehlerbeschreibung stehen.

### P2 – Vollständigkeit und Download des Logs sind nicht funktional getestet

`tests/unit/test_install_job.py` beweist Dateimodus und direkte Redaktion,
aber nicht, dass die Datei nach mehr als 500 In-Memory-Einträgen vollständig
bleibt. Für `app/uli/web/server.py:874-884` existiert kein Test, der den
tatsächlichen HTTP-Download, seinen exakten Inhalt und den Fehlerfall ohne Log
prüft. Der reine Stringtest in `test_web_static.py` erfüllt
Akzeptanzkriterium 9 nicht vollständig.

Korrektur:

- Einen Test mit mehr als 500 Logeinträgen ergänzen: In-Memory/Status bleibt
  begrenzt, `install.log` enthält weiterhin Anfang und Ende.
- Mit `TestClient` prüfen: ohne aktuelles Log fail-closed; mit Log HTTP 200,
  `text/plain`, Download-Header, `Cache-Control: no-store`, exakt derselbe
  redigierte Dateiinhalt und keine Secrets.
- Globale `_job`-Testzustände mit `monkeypatch.setattr` oder einem Fixture nach
  jedem Test wiederherstellen.

### P2 – Bestehender Web-API-Test wurde versehentlich verschmolzen

In `tests/unit/test_web_api.py:315-325` hängen die bisherigen Prüfungen für
unbekannte Distributionen und unsichere SSH-Policy nun am Ende von
`test_preview_40gib_debian_server_without_data_succeeds`. Der eigenständige
Testname `test_state_rejects_unsupported_selection_and_unsafe_ssh_policy` ist
verschwunden. Das erzeugt unnötige Kopplung an den vorherigen Disk-Mock.

Korrektur:

- Die beiden Prüfungen wieder in ihren eigenständigen Test mit dem bisherigen
  Namen auslagern; der 40-GiB-Test endet nach seiner Rootgrößenprüfung.

### Prozessblocker – Handover fehlt

Der vorgeschriebene Bericht `ai/handovers/TASK-004.md` wurde nicht angelegt.
Damit fehlen Cursor-Nachweise zu ausgeführten Befehlen, Ergebnissen und offenen
Risiken.

Korrektur:

- Handover gemäß `ai/handovers/TEMPLATE.md` erstellen und alle nach dem Rework
  ausgeführten Checks mit Ergebnis dokumentieren.

## Akzeptanzkriterien

- [x] Frischer Backend- und Frontendzustand deaktiviert die Datenpartition und
  behält 8 GiB Swap sowie den ruhenden 64-GiB-Datenwert.
- [x] Ein frischer einfacher Debian-Serverplan passt auf 40 GiB und erzeugt
  ESP, Root und Swap ohne Datenpartition.
- [x] Bewusst aktivierte 64 GiB Daten auf 40 GiB werden strukturiert und
  lokalisiert fail-closed abgelehnt.
- [ ] Der alte Paketname fehlt vollständig in Produktcode und Tests.
- [x] Debian installiert `tasksel`, führt danach den `standard`-Task aus und
  behält `task-gnome-desktop` nur für Desktop.
- [x] Reihenfolge und fataler tasksel-Exitcode sind getestet.
- [ ] Der Paket-Preflight deckt alle gewählten Varianten ab, ist explizit an
  amd64 gebunden und kann im Realmodus nicht fail-open übersprungen werden.
- [ ] Der vollständige Logerhalt und der echte API-Download inklusive
  Negativfall und Secret-Redaktion sind nachgewiesen.
- [x] Aktueller automatisierter Check ist grün.
- [ ] Vollständiger Cursor-Handover vorhanden.

## Ausgeführte Kontrollen

- `./scripts/check.sh`: `147 passed, 1 skipped`; Ruff, Syntax, ShellCheck und
  `git diff --check` grün.
- Fokussierte Task-Tests über `.venv/bin/python -m pytest`: `89 passed`.
- Reale, nichtdestruktive isolierte Debian-Trixie-APT-Prüfung in einem
  temporären Verzeichnis: PASS; 13 benannte Serverpakete erfolgreich
  aufgelöst, temporäre APT-Daten anschließend entfernt.
- Mehrvarianten-Gegenprobe mit Fake-Runner: nur ein APT-Installaufruf, aber
  `task-gnome-desktop` fehlt; Architektur nicht gebunden.
- Equal-Root-Gegenprobe Debian 20 GiB + Ubuntu 25 GiB auf 47 GiB:
  Fehler meldet fälschlich `required_mib == available_mib`.
- `rg` auf den alten Paketnamen in `app tests`: vier verbleibende Treffer.
- Scopekontrolle: alle vorliegenden Produktänderungen liegen in den für
  TASK-004 erlaubten Dateien; kein Commit, Push, ISO-Build oder destruktiver
  Befehl wurde im Review ausgeführt.

## Rest-Risiken

- Gate D und Gate E dürfen vor einem APPROVED-Review und einem neuen ISO nicht
  erneut ausgeführt werden.
- Der reale APT-Nachweis deckt nur Debian Server ab. Der korrigierte
  Mehrvariantenpfad muss vor Freigabe mindestens deterministisch getestet
  werden.

## Entscheidung

`CHANGES_REQUESTED`

Die Hauptfunktion ist weitgehend vorhanden und die Baseline bleibt grün. Die
Paketprüfung ist als Pre-Wipe-Sicherheitsgrenze jedoch noch nicht vollständig
fail-closed, und mehrere explizite Akzeptanz-/Prozessnachweise fehlen.
