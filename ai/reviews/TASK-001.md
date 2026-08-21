# Review TASK-001 – Final

Verdict: APPROVED

Reviewer: Codex/Sol

Geprüfter Stand: finale uncommitted Änderungen gegen `1a335da`

## Ergebnis

Keine verbleibenden Befunde im Scope von TASK-001.

Die letzte P1-Lücke ist geschlossen: Der Helfer verlangt nun, dass das
kanonisierte Keyring-Verzeichnis exakt
`<canon_root>/usr/share/keyrings` entspricht. Ein nach außen verlinktes
vollständiges `keyrings`-Verzeichnis wird sowohl durch
`resolve_payload` als auch durch `verify_installed` fail-closed abgelehnt.
Der offizielle relative Dateisymlink
`debian-archive-keyring.gpg -> debian-archive-keyring.pgp` bleibt zulässig.

## Akzeptanzkriterien

- [x] Offizielle Paketversion `2025.1`, HTTPS-URL und SHA-256 sind zentral
  fest verankert.
- [x] Eine falsche Paketprüfsumme wird vor Extraktion beziehungsweise
  Verwendung abgelehnt.
- [x] Jeder der drei einzeln fehlenden Debian-13-Fingerprints führt in
  deterministischen Offline-Tests zum Abbruch.
- [x] Build und ISO-Verifier verwenden dieselbe zentrale
  Fingerprintdefinition.
- [x] Absolute Datei-Symlinks, relative Traversal-Ziele, Symlinkketten und ein
  externes Keyring-Verzeichnis werden fail-closed abgelehnt.
- [x] Das echte gepinnte Paket wird nur extrahiert; Maintainer-Skripte werden
  nicht ausgeführt.
- [x] Der effektive Payload des echten Pakets ist `root:root`, Modus `0644`
  und enthält alle drei geforderten Fingerprints.
- [x] Der Build prüft den installierten Keyring erneut vor `mksquashfs`; der
  ISO-Verifier prüft ihn im read-only gemounteten SquashFS.
- [x] Die strikte Runtime-Regel `gpgv returncode == 0` ist unverändert.
- [x] Alle Produktänderungen liegen im erlaubten Dateiscope; Cursor hat weder
  Commit noch Push noch ISO-Build ausgeführt.

## Ausgeführte Kontrollen

- Fokussierte Tests:
  `12 passed, 1 optionaler Integrationstest skipped`.
- `./scripts/check.sh`:
  `134 passed, 1 optionaler Integrationstest skipped`, alle Checks bestanden.
- Exakter Workflow-ShellCheck einschließlich des neuen Helfers: Exit 0.
- `bash -n` für alle geänderten Shell-Dateien: Exit 0.
- `git diff --check`: Exit 0.
- Reproduktion des vollständigen Keyring-Verzeichnis-Ausbruchs:
  `resolve_payload` Exit 1 und `verify_installed` Exit 1.
- Reproduktion des absoluten Datei-Symlink-Ausbruchs: Exit 1.
- Legitimierter relativer Paket-Symlink: erfolgreich auf den Payload im
  temporären Rootfs aufgelöst.
- Echtes gepinntes `debian-archive-keyring_2025.1_all.deb` manuell installiert
  und geprüft: SHA-256 korrekt, Payload `root:root`/`0644`, alle drei
  Debian-13-Fingerprints vorhanden.

Der optionale Paket-Integrationstest skippt ohne Datei im lokalen APT-Cache.
Das ist kein Freigabeblocker, weil die Sicherheitslogik vollständig offline
ausgeführt wird und der identische reale Paketpfad im Review separat
erfolgreich geprüft wurde.

## Nachgelagertes Artefakt-Gate

Nach Nutzerfreigabe wurde Gate D am 2026-08-21 ausgeführt und bestanden:

- frischer kanonischer ISO-Build: PASS
- SHA-256-Prüfung: PASS
- Hybrid-/UEFI-Struktur und beide `BOOTX64.EFI`: PASS
- Debian-13-Keyring im read-only gemounteten SquashFS: PASS
- QEMU-OVMF-Live-Boot bis `ULI_LIVE_READY`: PASS
- Artefakt: `artifacts/ultimate-linux-installer-0.3.0-amd64.iso`
- SHA-256:
  `cf9fe39c5d2bbff58b2eb75995412639b20532249ecfe7502d0569c4846f24c7`

Die Freigabe ist weiterhin keine Releasefreigabe. Gate E bleibt ausstehend:
vollständige Installation auf einer entbehrlichen VM-Testdisk, ISO entfernen,
Zielsystem booten und erwarteten GRUB-/Login-Nachweis erbringen.

## Entscheidung

`APPROVED`
