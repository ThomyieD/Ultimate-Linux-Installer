# Review TASK-004 – Final

Verdict: APPROVED

Reviewer: Codex/Sol

Geprüfter Stand: uncommittierte Änderungen gegen `786d11c`

Handover: `ai/handovers/TASK-004.md` vorhanden und mit dem Diff konsistent

## Ergebnis

Der P1-Befund aus Iteration 2 ist behoben. Jeder Installationsstart erhöht
jetzt eine geschützte Job-Generation. Ein auslaufender Worker leert die globalen
Redaktionswerte nur noch, wenn er weiterhin Eigentümer dieser Generation ist.
Damit kann das Cleanup eines alten Jobs weder Passwort-Hash noch SSH-Schlüssel
eines laufenden Folgejobs aus der Redaktionsmenge entfernen.

Der neue deterministische Regressionstest hält Job 1 zwischen terminalem
Status und Cleanup an, startet Job 2 und prüft anschließend sowohl den Erhalt
seiner Redaktionswerte als auch die tatsächliche Redaktion einer Diagnosezeile.
Passwort-Hash und vollständiger SSH-Schlüssel werden abgedeckt.

Alle Befunde aus den Iterationen 1 und 2 sind geschlossen. Es wurden keine
neuen Blocker gefunden.

## Akzeptanzkriterien

- [x] Frischer Backend- und Frontendzustand deaktiviert die Datenpartition und
  behält 8 GiB Swap sowie den ruhenden 64-GiB-Datenwert.
- [x] Ein frischer einfacher Debian-Serverplan passt auf 40 GiB und erzeugt
  ESP, Root und Swap ohne Datenpartition.
- [x] Bewusst aktivierte 64 GiB Daten auf 40 GiB werden strukturiert und
  lokalisiert fail-closed abgelehnt.
- [x] Der falsche Debian-Paketname fehlt vollständig in Produktcode und Tests.
- [x] Debian installiert `tasksel`, führt danach den fatalen `standard`-Task
  aus und installiert `task-gnome-desktop` nur für Desktop.
- [x] Reihenfolge und fataler Task-Exitcode sind getestet.
- [x] Der Paket-Preflight liegt vor Storage, isoliert Host-APT, prüft die
  Paketunion aller Varianten, erzwingt Signaturen und ist auf `amd64` gebunden.
- [x] APT-/Auflösungsfehler hinterlassen null destruktive Storage-Aufrufe.
- [x] Vollständiges Log, Modus `0600`, API-Download und UI-Verknüpfung sind
  nachgewiesen.
- [x] Passwort-Hash und SSH-Schlüssel bleiben auch bei unmittelbar
  aufeinanderfolgenden Jobs aus Log, Status und Download entfernt.
- [x] Vollständiger Cursor-Handover vorhanden.

## Ausgeführte Kontrollen

- Fokussierte Suite einschließlich des neuen Nebenläufigkeitstests:
  `.venv/bin/python -m pytest -q tests/unit/test_install_job.py::test_stale_worker_cleanup_does_not_disable_successor_redaction tests/unit/test_install_job.py tests/unit/test_apt_preflight.py tests/unit/test_storage_layout.py tests/unit/test_web_api.py tests/unit/test_provisioning.py tests/unit/test_web_static.py`
  – `94 passed`.
- `./scripts/check.sh` – `152 passed, 1 skipped`; Ruff, Syntax, ShellCheck und
  Diff-Prüfung grün.
- `git diff --check` – grün.
- Reale, nichtdestruktive isolierte Debian-Trixie-APT-Prüfung aus Iteration 2
  mit `debian:server` plus `debian:desktop` – PASS; 14 Pakete einschließlich
  `tasksel` und `task-gnome-desktop` gegen die signierte HTTPS-Quelle für
  `amd64` aufgelöst.
- `rg` auf den falschen Paketnamen in `app tests` – keine Treffer.
- Scopekontrolle – alle Produkt-/Teständerungen liegen in den für TASK-004
  erlaubten Dateien. Reviewhistorie liegt unter `ai/reviews/`.
- Kein Commit, Push, ISO-Build, VM-Start oder destruktiver Befehl wurde im
  Review ausgeführt.

## Rest-Risiken

- Automatisierte Tests und der reale APT-Preflight ersetzen noch nicht Gate D
  und Gate E mit einem neu gebauten ISO.
- Die Freigabe gilt für den aktuell geprüften uncommittierten Arbeitsbaum. Vor
  Commit und Build darf der Produkt-Diff nicht mehr verändert werden.

## Entscheidung

`APPROVED`
