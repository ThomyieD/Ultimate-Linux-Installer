# Handover TASK-004

Status: IMPLEMENTED

## Geänderte Dateien

- `app/uli/storage/layout.py`: `DiskTooSmallError`; Equal-Root-Mindestbedarf über `max(root_minima) * n`
- `app/uli/install/provision.py`: Debian `tasksel` + fatal `tasksel install standard`; kein Altname
- `app/uli/install/apt_preflight.py`: isolierter Pre-Wipe-APT-Check (Paketunion pro Distro, amd64-Pin, kein Dry-Run-Runner-Fail-Open)
- `app/uli/install/job.py`: Preflight vor Wipe; vollständiges `install.log` (0600) mit Secret-Redaktion; Job-`_generation` verhindert, dass ein alter Worker die Needles eines Folgejobs löscht
- `app/uli/web/server.py`: Defaults `include_data=false`; strukturiertes `disk_too_small`; `GET /api/install/log`
- `app/uli/web/static/app.js`: Default ohne Daten; lokalisiertes Disk-zu-klein; Log-Download auf Fehlerseite
- `app/uli/i18n/de.json`, `app/uli/i18n/en.json`: `storage.disk_too_small`
- `tests/unit/test_storage_layout.py`, `test_provisioning.py`, `test_web_api.py`, `test_web_static.py`: Scope-Regressionen; getrennter SSH/Selection-Test
- `tests/unit/test_apt_preflight.py`, `tests/unit/test_install_job.py`: Preflight-/Log-/Download-Nachweise; deterministischer Zwei-Job-Nebenläufigkeitstest für Secret-Redaktion
- `ai/handovers/TASK-004.md`: dieser Bericht

## Umsetzung

### Review-Rework (Iteration 1, CHANGES_REQUESTED)

1. **Paketunion:** Pro Distro-ID ein APT-Root; simulierte Menge = Vereinigung aller Varianten.
2. **Kein Fail-Open:** Nur `dry_run=True` überspringt Netzwerk.
3. **amd64:** explizite APT-Architekturbindung.
4. **Equal-Root:** `required_mib = fixed_mib + max(root_minima) * len(distros)`.
5. **Altname:** entfernt aus `app/` und `tests/`.
6. **Log:** Vollständigkeit, Download, Redaktion.
7. **Web-API:** getrennter Selection/SSH-Test.

### Review-Rework (Iteration 2, P1 Nebenläufigkeit)

- Jeder `start_install` erhöht `_job._generation` und der Worker merkt sich seine Generation.
- Im `finally` werden `_secret_needles` nur geleert, wenn `_job._generation` noch der eigenen Generation entspricht.
- Regressionstest mit Barrieren: Job 1 pausiert zwischen terminalem Status und Cleanup; Job 2 startet; Cleanup von Job 1 lässt Needles/Redaktion von Job 2 unberührt (Passwort-Hash und SSH-Schlüssel).

## Ausgeführte Checks

- `.venv/bin/python -m pytest -q tests/unit/test_apt_preflight.py tests/unit/test_install_job.py tests/unit/test_storage_layout.py tests/unit/test_web_api.py tests/unit/test_provisioning.py tests/unit/test_web_static.py`: Exit 0, **94 passed**
- `./scripts/check.sh`: Exit 0, **152 passed, 1 skipped**; Ruff/Syntax/ShellCheck/`git diff --check` grün

Kein ISO-Build, keine VM, keine reale Installation, kein Commit, kein Push.

## Abweichungen oder offene Risiken

- Gate D/E und destruktive Installationspfade bleiben bis APPROVED und neuem ISO gesperrt.

## Git

- Arbeitsbaum mit TASK-004-Änderungen, uncommitted
- kein Commit, kein Push
