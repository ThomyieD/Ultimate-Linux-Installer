# Ultimate Linux Installer

Moderne, dunkle UEFI-Installationssoftware für Einzel- und Multiboot-Linux-Systeme.

Vom USB-Stick booten → grafischer Installer (kein manuelles Live-Desktop-Gefrickel) → Download von offiziellen Spiegelservern → unbeaufsichtigte Installation → zentrales GRUB-Menü im Stil des Soll-Zustands.

> **Deutsch ist die Standardsprache** der Oberfläche. Englisch lässt sich im Installer umschalten.  
> English documentation: [README.en.md](README.en.md)

## Fertige ISO herunterladen

**Ja: Ubuntu, Debian, Fedora usw. liegen nicht auf dem Stick.** Die werden erst während der Installation von den offiziellen Spiegeln geladen. Deshalb ist die ISO kein Multi-Gigabyte-Paket wie ein Stick voller Distro-ISOs.

Trotzdem enthält die ISO ein **komplettes bootfähiges Live-System**: Kernel, Treiber/Firmware, Netzwerk, Partitionswerkzeuge und die grafische Installer-Oberfläche (Qt). Das sind typischerweise einige hundert MB bis ca. 1–2 GB – klein im Vergleich zu „alle Distros mitnehmen“, aber **zu groß und ungeeignet für Git** (GitHub-Limits, Repo-Aufblähung, jede Version eine neue Binärdatei).

Deshalb liegt die fertige ISO unter **[Releases](https://github.com/ThomyieD/Ultimate-Linux-Installer/releases)**, nicht im Git-Tree:

1. Release öffnen und `ultimate-linux-installer-*.iso` laden
2. Mit Rufus, balenaEtcher oder `dd` auf USB schreiben (GPT + UEFI)

Solange noch kein Release mit ISO existiert, musst du sie einmal bauen (siehe unten) – oder wir erzeugen sie und hängen sie an ein Release.

## Funktionen (MVP)

- **Modi:** Einfache Installation · Multiboot · Distribution hinzufügen · entfernen
- **Distributionen:** Debian, Ubuntu (Desktop/Server), Fedora (Workstation/Server), Arch, Proxmox VE (nur Einfach)
- **Oberfläche:** modernes Dark Theme, Deutsch standardmäßig, Englisch umschaltbar
- **Speicher:** gleichmäßige Aufteilung oder Plan, ESP + Roots + optional Swap/Daten; Installations-USB nie als Ziel
- **Bootloader:** ein Chef-GRUB (`EFI/UltimateInstaller`) mit Theme; UEFI-Firmware-Einstellungen zuletzt
- **Absicherungen** aus dem realen Multiboot-Projekt:
  - UEFI-BootOrder nach Distro-Installern zurückholen
  - stabile `/vmlinuz`- und `/initrd.img`-Symlinks inkl. Update-Hooks
  - gemeinsames Swap mit `resume=UUID=…`
  - Primärbenutzer in `sudo`/`wheel`
  - unnötige wait-online-Verzögerungen vermeiden
  - fortsetzbarer Installationszustand

## Architektur

```text
UEFI-Firmware
  → Bootloader vom USB-Stick
  → minimales Linux-Live-System
  → Ultimate Linux Installer (PySide6)
       ├── Netzwerk / Speicher / Downloads
       ├── Distro-Adapter (Preseed / Autoinstall / Kickstart / Pacstrap)
       └── zentraler GRUB + Themes
```

Details: [docs/architecture/overview.md](docs/architecture/overview.md)

## Entwicklung

### Linux-Buildhost (empfohlen: Debian/Ubuntu)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uli --dry-run --lang de          # Desktop-UI mit simulierten Festplatten
pytest
```

### ISO selbst bauen (nur für Entwickler)

```bash
sudo apt install live-build qemu-system-x86 ovmf xorriso squashfs-tools
./scripts/generate-theme-assets.sh
./scripts/build-iso.sh
./scripts/run-qemu.sh
```

Die ISO landet unter `artifacts/ultimate-linux-installer.iso` und wird für Nutzer über **GitHub Releases** bereitgestellt – nicht committed.

> Destruktive Partitionierung läuft nur im Live-Image nach Bestätigung. Desktop-Modus ist standardmäßig Dry-Run.

## Repository-Struktur

```text
app/uli/           # Python-Anwendung (UI + Kern)
adapters/          # Automation pro Distribution
themes/grub/       # GRUB-Themes (uli-lenovo, uli-dark)
live-build/        # Debian live-build Konfiguration
schemas/           # JSON-Schema für den Installationsplan
scripts/           # ISO- und QEMU-Hilfen
tests/             # Unit- / Integrations- / QEMU-Tests
docs/              # Architektur + Referenz-Mockups
```

## Status

**0.1.0 – Foundation-MVP**

Aktuell: Wizard-UI, Plan-Erzeugung, Adapter, GRUB-Rendering, Dry-Run-Partitionierung, State-Machine, Tests.

Als Nächstes: Live-ISO feinschleifen, Download+Verify-Pipeline, Multi-Install-Orchestrierung in QEMU, Hardware-Validierung.

## Lizenz

MIT – siehe [LICENSE](LICENSE).
