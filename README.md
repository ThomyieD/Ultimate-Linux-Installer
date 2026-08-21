# Ultimate Linux Installer

Der Ultimate Linux Installer (ULI) ist ein grafischer Installer für ein einzelnes Linux-System oder ein kontrolliertes Linux-Multiboot-Setup auf einem vollständigen Datenträger.

Vom USB-Stick booten → deutschsprachiger Web-Kiosk → Installationsplan prüfen und ausdrücklich bestätigen → Systeme direkt aus offiziellen Paketquellen installieren → über ein gemeinsames GRUB-Menü starten.

> **Deutsch ist die Standardsprache** der Oberfläche. Englisch lässt sich im Installer umschalten.
> English documentation: [README.en.md](README.en.md)

## Freigegebener Umfang von v0.3

v0.3 konzentriert sich bewusst auf einen kleinen, überprüfbaren Installationspfad:

- **Plattform:** x86_64-Rechner im UEFI-Modus, Secure Boot deaktiviert
- **Zieldatenträger:** ein kompletter, leerbarer Datenträger; GPT, gemeinsame EFI-Systempartition und ext4-Root-Partitionen
- **Modi:** einfache Installation mit genau einem System oder Multiboot mit mindestens zwei Systemen
- **Freigegebene Systeme:** Debian 13 und Ubuntu 24.04 LTS, jeweils als Desktop oder Server
- **Installation:** direkt mit `debootstrap`/APT aus den offiziellen Debian- und Ubuntu-Repositories; keine Distro-ISOs auf dem Installationsstick
- **Quellenprüfung:** OpenPGP-signiertes `InRelease` wird vor der ersten destruktiven Aktion geprüft; APT/debootstrap prüft anschließend die Pakete gegen die signierten Metadaten
- **Oberfläche:** primäre, bildschirmfüllende Web-Kiosk-UI mit neun Schritten: Netzwerk, Modus, Distributionen, Quellen, Einstellungen, Speicher, Prüfung, Installation und Abschluss
- **Speicher:** gleichmäßige oder individuelle Root-Größen sowie optional Swap und Datenpartition
- **Bootloader:** ein zentraler GRUB unter `EFI/UltimateInstaller`, erzeugt erst nach dem Formatieren mit den echten UUIDs/PARTUUIDs; UEFI-Fallback unter `EFI/BOOT`

Fedora, Arch Linux und Proxmox VE sowie die Modi **Distribution hinzufügen** und **Distribution entfernen** bleiben als geplanter Produktumfang in der Oberfläche sichtbar. Sie sind in v0.3 technisch gesperrt, damit kein unfertiger Pfad Daten verändert. Proxmox ist auch perspektivisch nur für die einfache Installation vorgesehen.

## Sicherheitsmodell

Die Weboberfläche darf weder Gerätepfade noch Datenträgergrößen vorgeben. Sie wählt nur eine vom privilegierten Backend gelieferte Datenträger-ID. Vor dem Start gilt:

1. Das Backend validiert Einstellungen, Distributionen und Mindestgrößen.
2. Die Speichervorschau bindet den vollständigen Plan an einen SHA-256-Fingerabdruck und den aktuell erkannten Datenträger.
3. Erst die ausdrückliche Bestätigung erzeugt ein kurzlebiges Einmal-Token.
4. Beim Start werden Token, Konfigurationsstand und Datenträger erneut geprüft.
5. Signierte Paketquellen, UEFI/Secure-Boot-Voraussetzungen und ein echter GRUB-Testbuild werden vor dem Löschen geprüft.
6. Reale Ziele ohne stabile Seriennummer oder WWN werden nicht angeboten; unmittelbar vor `wipefs` werden Hardwarekennung, Modell, Größe und Kernel-Geräteidentität erneut verglichen.

Passwörter werden beim Übernehmen gehasht und weder über die öffentliche Status-API noch im Audit-Protokoll im Klartext ausgegeben. Das Live-System betreibt das privilegierte Backend als eigenen Dienst; der Kiosk-Benutzer erhält keine pauschalen `sudo`-Rechte.

## ISO herunterladen

Die fertige Installer-ISO gehört nicht in den Git-Verlauf. Veröffentlichte Versionen liegen als ISO plus Prüfsumme unter **[GitHub Releases](https://github.com/ThomyieD/Ultimate-Linux-Installer/releases)**. Lokal erzeugte Test-Images liegen unter `artifacts/` und werden nicht committed.

1. Passendes `ultimate-linux-installer-<version>-amd64.iso` und `SHA256SUMS` herunterladen.
2. Prüfsumme kontrollieren.
3. Die ISO mit Rufus, balenaEtcher oder `dd` auf einen USB-Stick schreiben und im UEFI-Modus starten.

Wenn noch kein passendes Release-Asset existiert, kann die ISO lokal gebaut werden.

## Entwicklung und Tests

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Sichere Desktop-Simulation der primären Weboberfläche
uli --dry-run --simulate-disk --lang de

# Automatisierte Tests und statische Prüfung
pytest
ruff check app adapters tests
```

Die Weboberfläche läuft anschließend standardmäßig unter `http://127.0.0.1:8787`. Die frühere PySide6-Oberfläche ist nur noch als nichtdestruktive Entwicklungssimulation mit `uli --ui qt --dry-run` verfügbar; reale Installationen laufen ausschließlich über den Web-Kiosk.

### ISO lokal bauen

Auf einem Ubuntu-/Debian-Buildhost werden unter anderem `debootstrap`, `xorriso`, `squashfs-tools`, GRUB-Werkzeuge und OVMF/QEMU benötigt. Der kanonische Einstieg ist:

```bash
./scripts/generate-theme-assets.sh
sudo scripts/build-iso.sh
sudo scripts/verify-iso-uefi.sh artifacts/ultimate-linux-installer-0.3.0-amd64.iso
./scripts/run-qemu.sh
```

Das Ergebnis liegt versionsbezogen unter `artifacts/`. Der manuell gestartete GitHub-Workflow führt Tests und Build aus, stellt zunächst ein Workflow-Artefakt bereit und lädt Dateien nur dann in ein Release hoch, wenn ausdrücklich ein Release-Tag angegeben wurde.

## Aktueller Abnahmestatus

Die v0.3-Codebasis enthält den durchgängigen Orchestrierungsweg für Vorschau/Bestätigung, Partitionierung, signierte Quellen, Debian-/Ubuntu-Provisionierung und Chef-GRUB. Unit-, API-, Dry-Run- und ISO-Strukturprüfungen decken die wesentlichen Plan- und Sicherheitsgrenzen ab.

Noch **nicht** als abgeschlossen zu betrachten sind:

- die vollständige destruktive End-to-End-Abnahme auf echter Hardware für alle vier freigegebenen Varianten,
- eine breite Hardwarematrix für WLAN, Grafik, Firmware und unterschiedliche Datenträger,
- Secure-Boot-Unterstützung,
- Fedora-, Arch- und Proxmox-Installation,
- das sichere Vergrößern/Verkleinern bestehender Installationen für Hinzufügen/Entfernen,
- belastbare Wiederaufnahme über jeden denkbaren Stromausfallpunkt hinweg.

Bis diese Abnahmen erfolgt sind, sollte v0.3 auf entbehrlicher Hardware beziehungsweise in einer VM mit Wegwerf-Datenträger getestet werden. **Eine reale Installation löscht den ausgewählten Zieldatenträger vollständig.**

## Architektur und Repository

Details stehen in [docs/architecture/overview.md](docs/architecture/overview.md). Die ursprünglichen Produktvorgaben und Mockups bleiben unter `docs/reference/` als Referenz erhalten.

```text
app/uli/web/       # primäre Web-Kiosk-UI und lokale API
app/uli/install/   # Quellenprüfung, Provisionierung und Orchestrierung
app/uli/storage/   # Datenträgererkennung, Layout und geschützter Executor
app/uli/bootloader/# zentraler GRUB und Update-Hooks
adapters/          # Metadaten und Automationsbausteine pro Distribution
themes/grub/       # GRUB-Themes (uli-lenovo, uli-dark)
schemas/           # JSON-Schema des Installationsplans
scripts/           # Build-, ISO- und QEMU-Hilfen
tests/             # Unit-, API- und Provisionierungs-Tests
docs/              # Architektur und Referenzunterlagen
artifacts/         # lokale ISO-Testartefakte; nicht für Git
```

## Lizenz

MIT – siehe [LICENSE](LICENSE).
