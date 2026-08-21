# Review TASK-004 – Iteration 2

Verdict: CHANGES_REQUESTED

Reviewer: Codex/Sol

Geprüfter Stand: uncommittierte Änderungen gegen `786d11c`

Handover: `ai/handovers/TASK-004.md` vorhanden und mit dem Diff konsistent

## Ergebnis der Nachprüfung

Die sieben technischen Befunde sowie der Prozessblocker aus Iteration 1 sind
behoben. Paketunion, Realmodus-Fail-Closed, amd64-Bindung, Equal-Root-Berechnung,
Entfernung des falschen Paketnamens, vollständiger Logdownload und die
Entkopplung des Web-API-Tests sind im Diff und durch Tests nachgewiesen.

Es bleibt ein neuer sicherheitsrelevanter Nebenläufigkeitsfehler im
Job-Lebenszyklus. TASK-004 kann deshalb noch nicht freigegeben werden.

## Offener Befund

### P1 – Ein alter Worker kann die Secret-Redaktion eines neuen Jobs abschalten

`app/uli/install/job.py:198-205` beziehungsweise `:219-225` veröffentlicht den
terminalen Status `done`/`error`, bevor der Worker seinen `finally`-Block
erreicht. Ab diesem Zeitpunkt lässt `start_install()` in `:171-188` bereits
einen neuen Job zu und hinterlegt dessen Passwort-Hash und SSH-Schlüssel in
`_job._secret_needles`.

Der alte Worker leert anschließend in `:226-231` jedoch bedingungslos das
globale `_job._secret_needles`. Dadurch kann der bereits laufende Folgejob ohne
Redaktion weiterschreiben. Das verletzt das ausdrückliche Akzeptanzkriterium,
dass Passwort-Hash und SSH-Schlüssel niemals in Log oder API erscheinen.

Deterministische Review-Reproduktion mit zwei Worker-Barrieren:

```text
SECOND_JOB_STATUS running
SECOND_JOB_NEEDLES ()
SECRET_LEAKED True
```

Dabei wurde der erste Worker unmittelbar nach dem Setzen von `done`, aber vor
seinem `finally` angehalten, Job 2 gestartet und anschließend Worker 1
freigegeben. Eine danach über `_log()` geschriebene Diagnosezeile enthielt den
Passwort-Hash von Job 2 unverändert.

Korrektur:

- Jobbezogene Geheimnisse dürfen nur von dem Worker gelöscht werden, der sie
  gesetzt hat. Geeignet ist beispielsweise eine Job-/Generation-ID oder eine
  Identitätsprüfung auf einen pro Start erzeugten Jobkontext.
- Alternativ muss die gesamte Bereinigung abgeschlossen sein, bevor der
  terminale Status sichtbar wird. Dabei muss weiterhin gewährleistet sein,
  dass Fehlertext und abschließende Diagnosezeilen bis zuletzt redigiert sind.
- Einen deterministischen Regressionstest mit Barrieren ergänzen: Job 1 steht
  zwischen terminalem Status und Cleanup, Job 2 startet, danach darf das
  Cleanup von Job 1 weder die Needles noch die Redaktion von Job 2 verändern.
  Der Test muss Passwort-Hash und vollständigen SSH-Schlüssel abdecken.

## Behobene Befunde aus Iteration 1

- [x] Varianten derselben Distribution werden in einer Paketunion geprüft.
- [x] `dry_run=False` mit einem Dry-Run-Runner bricht fail-closed ab.
- [x] APT Update und Simulation sind explizit auf ausschließlich `amd64`
  gebunden.
- [x] Equal-Root verwendet das größte Einzelminimum für jede Rootpartition.
- [x] Der falsche Debian-Paketname fehlt in `app/` und `tests/` vollständig.
- [x] Vollständigkeit über 500 Zeilen, Dateimodus, Redaktion sowie positiver
  und negativer HTTP-Download sind funktional getestet.
- [x] Der Web-API-Regressionstest ist wieder eigenständig.
- [x] Der vorgeschriebene Cursor-Handover ist vorhanden.

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
- [x] Der Paket-Preflight liegt vor Storage, isoliert Host-APT, prüft alle
  Varianten, erzwingt Signaturen und ist auf `amd64` gebunden.
- [ ] Secret-Redaktion bleibt für jeden laufenden Job auch bei unmittelbar
  aufeinanderfolgenden Jobs garantiert.
- [x] Vollständiges Log, Dateirechte und Read-only-Download sind nachgewiesen.
- [x] Aktueller automatisierter Check und Handover sind vollständig grün.

## Ausgeführte Kontrollen

- Fokussierte Suite:
  `.venv/bin/python -m pytest -q tests/unit/test_apt_preflight.py tests/unit/test_install_job.py tests/unit/test_storage_layout.py tests/unit/test_web_api.py tests/unit/test_provisioning.py tests/unit/test_web_static.py`
  – `93 passed`.
- `./scripts/check.sh` – `151 passed, 1 skipped`; Ruff, Syntax, ShellCheck und
  die eingebundene Diff-Prüfung grün.
- `git diff --check` – grün.
- Reale, nichtdestruktive isolierte Debian-Trixie-APT-Prüfung mit
  `debian:server` plus `debian:desktop` – PASS; ein gemeinsamer APT-Root löst
  14 Pakete einschließlich `tasksel` und `task-gnome-desktop` gegen die
  signierte HTTPS-Quelle für `amd64` auf; temporäre Daten entfernt.
- `rg` auf den falschen Paketnamen in `app tests` – keine Treffer.
- Deterministische Zwei-Job-Nebenläufigkeitsprobe – FAIL wie oben belegt.
- Scopekontrolle – Produkt-/Teständerungen liegen in den für TASK-004
  erlaubten Dateien; kein Commit, Push, ISO-Build, VM-Start oder destruktiver
  Befehl wurde im Review ausgeführt.

## Rest-Risiken und nächster Schritt

Cursor muss ausschließlich den oben beschriebenen P1-Befund samt
Regressionstest beheben und `ai/handovers/TASK-004.md` aktualisieren. Danach ist
eine weitere Codex-Nachprüfung erforderlich. Gate D/E und ein neuer ISO-Build
bleiben bis `APPROVED` gesperrt.

## Entscheidung

`CHANGES_REQUESTED`
