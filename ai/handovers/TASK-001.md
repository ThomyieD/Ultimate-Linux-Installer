# Handover TASK-001

Status: IMPLEMENTED

## Geänderte Dateien

- `scripts/lib-debian-archive-keyring.sh`: gepinnter Keyring-Helfer; `resolve_payload` bindet `canon_dir` exakt an `<canon_root>/usr/share/keyrings` (Symlink auf das Keyring-Verzeichnis fail-closed); Datei-Symlinks nur als relativer Basename; Installation ohne Maintainer-Skripte
- `scripts/build-iso-simple.sh`: Keyring-Pin vor SquashFS; frühe `need`-Prüfung inkl. `curl`, `dpkg-deb`, `gpg`
- `scripts/verify-iso-uefi.sh`: SquashFS-Mount + dieselbe `verify_installed`-Prüfung
- `.github/workflows/release-iso.yml`: Helfer in ShellCheck-Liste
- `tests/unit/test_debian_archive_keyring.py`: Offline-Hash-/Fingerprint-/Datei-Symlink- und Verzeichnis-Symlink-Ausbruch-Tests
- `ai/handovers/TASK-001.md`: dieser Bericht

## Umsetzung

Iteration-2-Korrektur (verbleibender P1):

- Vor Payload-Prüfung: `expected_dir="$canon_root/usr/share/keyrings"`; Ablehnung wenn dieses Verzeichnis selbst ein Symlink ist oder `realpath` nicht exakt `expected_dir` ergibt.
- Offline-Regression: gesamtes `keyrings`-Verzeichnis auf externes Ziel verlinkt → `resolve_payload` und `verify_installed` Exit ≠ 0.
- Offizieller relativer Dateisymlink `debian-archive-keyring.gpg → debian-archive-keyring.pgp` und echter Paketpfad bleiben erlaubt.

## Ausgeführte Checks

- Review-Repro Verzeichnis-Symlink-Ausbruch: `DIR_ESCAPE_EXIT:1` (`Refusing symlinked Debian archive keyring directory`)
- `.venv/bin/python -m pytest -q tests/unit/test_debian_archive_keyring.py`: Exit 0 — **12 passed, 1 skipped**
- Exakter Workflow-ShellCheck:

  ```bash
  shellcheck scripts/build-iso.sh scripts/build-iso-simple.sh \
    scripts/lib-runtime-bundle.sh \
    scripts/lib-debian-archive-keyring.sh \
    scripts/generate-theme-assets.sh scripts/install-firefox-tarball.sh \
    scripts/lib-iso-uefi.sh scripts/verify-iso-uefi.sh
  ```

  Exit 0
- `./scripts/check.sh`: Exit 0 — **134 passed, 1 skipped**

Kein Commit, kein Push, kein ISO-Build.

## Abweichungen oder offene Risiken

- Gate D/E (ISO-Build, Verifier, VM) bleibt ausstehend.
- Optionaler `.deb`-Integrationstest skippt ohne lokalen Cache; Sicherheitslogik ist offline abgedeckt.
- `scripts/check.sh` listet den Helfer weiterhin nicht (ursprünglicher Scope); CI prüft ihn über `release-iso.yml`.

## Git

- `git status --short`:

```text
 M .github/workflows/release-iso.yml
 M scripts/build-iso-simple.sh
 M scripts/verify-iso-uefi.sh
?? ai/handovers/TASK-001.md
?? scripts/lib-debian-archive-keyring.sh
?? tests/unit/test_debian_archive_keyring.py
```

- kein Commit, kein Push
