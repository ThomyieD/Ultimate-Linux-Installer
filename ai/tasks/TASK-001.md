# TASK-001 – Debian-13-Archivschlüssel im Live-ISO aktualisieren

Status: APPROVED / Gate D bestanden / Gate E ausstehend

Priorität: P0 / blockiert reale Debian-Installation

Owner: Cursor

Reviewer: Codex/Sol

Implementierungs-Commit: `5a696df`

## Ziel

Ein frisch gebautes ULI-ISO muss das offizielle Debian-13-`InRelease` mit einem
vollständigen, fest verankerten Debian-13-Keyring vor dem Wipe erfolgreich
prüfen. Manipulierte oder unerwartete Schlüsselartefakte müssen den Build
beziehungsweise die Installation weiterhin fail-closed stoppen.

## Ausgangssituation und reproduzierter Beleg

Der Screenshot zeigt bei 8 Prozent:

```text
APT source signature verification failed for debian
Good signature ... Debian Archive Automatic Signing Key (12/bookworm)
Can't check signature: No public key ... Debian 13 automatic key
Can't check signature: No public key ... Debian 13 stable release key
```

Im aktuellen Build wurde nachgewiesen:

- Live-Chroot-Keyring: `/usr/share/keyrings/debian-archive-keyring.gpg`
- Paket: `debian-archive-keyring 2023.4ubuntu1`
- der Keyring enthält Debian 12, aber nicht die Debian-13-Schlüssel
- aktuelles `trixie`-`InRelease` (Debian 13.6) ergibt `gpgv` Exit 2
- Debian-Keyring 2025.1 ergibt mit derselben Datei drei `VALIDSIG` und Exit 0

Offizielle Referenzen:

- Paket: `debian-archive-keyring 2025.1`
- Paket-URL:
  `https://deb.debian.org/debian/pool/main/d/debian-archive-keyring/debian-archive-keyring_2025.1_all.deb`
- SHA-256:
  `9ea7778e443144ca490668737a8ab22dd3e748bb99e805e22ec055abeb3c7fac`
- Debian-13-Archivschlüssel:
  `04B54C3CDCA79751B16BC6B5225629DF75B188BD`
- Debian-13-Security-Schlüssel:
  `5E04A1E3223A19A20706E20F9904613D4CCE68C6`
- Debian-13-Stable-Release-Schlüssel:
  `41587F7DB8C774BCCF131416762F67A0B2C39DE4`

Debian dokumentiert diese Fingerprints unter
`https://ftp-master.debian.org/keys.html`; Paketversion und Prüfsumme stehen
unter `https://packages.debian.org/trixie/all/debian-archive-keyring/download`.

## Abhängigkeiten

- keine

## Scope

1. Den ISO-Build so ergänzen, dass er das exakt versionierte offizielle
   `debian-archive-keyring_2025.1_all.deb` über HTTPS lädt, vor jeder Verwendung
   gegen die oben festgelegte SHA-256-Prüfsumme prüft und daraus nur das
   benötigte öffentliche Keyring-Material übernimmt.
2. Keine Maintainer-Skripte des fremden Pakets ausführen. Das Paket in ein
   temporäres Verzeichnis extrahieren und die benötigten Keyring-Dateien mit
   `root:root` und nicht schreibbar für Gruppe/Andere installieren.
3. Vor `mksquashfs` fail-closed prüfen, dass alle drei oben genannten primären
   Fingerprints im effektiven Keyring des Chroots vorhanden sind.
4. Den ISO-Verifier ebenfalls auf diese drei Fingerprints prüfen lassen, damit
   ein späterer Packaging-Fehler das Quality Gate stoppt.
5. Offline-fähige Tests für URL/Version/Hash, Fingerprintauswertung,
   Fehlerfälle und Build-/Verifier-Integration ergänzen.
6. Falls ein kleiner Hilfsbaustein nötig ist, ihn separat und testbar unter
   `scripts/` anlegen; vorhandene kanonische Skriptmuster verwenden.

## Nicht-Scope

- `gpgv`-Fehler oder `NO_PUBKEY` als Erfolg behandeln
- die Runtime-Prüfung in `app/uli/install/sources.py` lockern
- Schlüssel während einer Installation ungeprüft aus dem Netz nachladen
- Ubuntu-Versionierung, Legacy-Adapter oder Dokumentation bereinigen
- ISO bauen, VM starten, echte Installation ausführen
- andere Distributionen oder neue Produktionsabhängigkeiten

## Erlaubte Dateien

- `scripts/build-iso-simple.sh`
- `scripts/verify-iso-uefi.sh`
- ein neuer, eng begrenzter Keyring-Helfer unter `scripts/`
- `.github/workflows/release-iso.yml`, ausschließlich um einen neuen
  kanonischen Helfer zu linten/prüfen
- `tests/unit/test_iso_packaging.py`
- eine neue fokussierte Testdatei unter `tests/unit/`, falls dadurch der
  Keyring-Helfer sauberer testbar ist
- `ai/handovers/TASK-001.md`

Wenn eine andere Produktdatei erforderlich erscheint: stoppen und den Blocker
im Handover dokumentieren.

## Architektur- und Sicherheitsvorgaben

- ADR-003 und ADR-004 sind bindend.
- Die festgelegte SHA-256-Prüfsumme und die erwarteten Fingerprints müssen
  unabhängig geprüft werden.
- Ein Downloadfehler, Hashfehler, Extraktionsfehler oder fehlender Fingerprint
  muss den Build vor der SquashFS-Erzeugung mit Exit ungleich 0 beenden.
- Keine `curl | gpg`-/`curl | shell`-Kette, kein globaler GnuPG-Keyring und kein
  Vertrauen allein aufgrund des HTTPS-Hosts.
- Temporäre Pfade müssen sicher erzeugt und durch den bestehenden Build-Cleanup
  erfasst werden.
- Die bestehende strikte Runtime-Regel `gpgv returncode == 0` bleibt erhalten.

## Akzeptanzkriterien

1. Ein Test beweist, dass falsche Paketprüfsumme abgelehnt wird.
2. Ein Test beweist, dass jeder der drei fehlenden Fingerprints einzeln zum
   Abbruch führt.
3. Build und Verifier verwenden dieselbe zentrale Fingerprintdefinition; keine
   auseinanderlaufenden Kopien der Sicherheitswerte.
4. Das resultierende Chroot-Keyring ist `root:root`, nicht gruppen- oder
   weltweit schreibbar und enthält alle drei Debian-13-Fingerprints.
5. Die vorhandene `verify_source_manifest`-Semantik wird nicht abgeschwächt.
6. `./scripts/check.sh` ist vollständig grün.
7. Cursor dokumentiert den noch ausstehenden ISO-/VM-Nachweis ausdrücklich im
   Handover und erstellt weder Commit noch Push.

## Tests

Mindestens:

```bash
./scripts/check.sh
```

Zusätzlich die neu angelegten fokussierten Unit-Tests separat ausführen. Ein
echter Download darf als manuelle Diagnose dokumentiert werden, ist aber kein
Bestandteil der Unit-Test-Suite.

## Definition of Done

- alle Akzeptanzkriterien nachweisbar erfüllt
- keine Änderung außerhalb der erlaubten Dateien
- keine Schutzprüfung gelockert
- vollständiger Handover unter `ai/handovers/TASK-001.md`
- kein ISO-Build, kein Commit und kein Push
