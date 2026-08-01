# Ultimate Linux Installer

Moderne, dunkle UEFI-Installationssoftware für Einzel- und Multiboot-Linux-Systeme.

Vom USB-Stick booten → grafischer Installer (kein manuelles Live-Desktop-Gefrickel) → Download von offiziellen Spiegelservern → unbeaufsichtigte Installation → zentrales GRUB-Menü im Stil des Soll-Zustands.

> **Deutsch ist die Standardsprache** der Oberfläche. Englisch lässt sich im Installer umschalten.  
> English documentation: [README.en.md](README.en.md)

## Fertige ISO herunterladen

Die bootfähige ISO liegt **nicht** im Git-Repository (zu groß, ändert sich mit jedem Release).

Stattdessen:

1. Öffne **[Releases](https://github.com/ThomyieD/Ultimate-Linux-Installer/releases)**
2. Lade `ultimate-linux-installer-*.iso` herunter
3. Schreibe sie mit Rufus, balenaEtcher oder `dd` auf einen USB-Stick (GPT + UEFI)

Falls noch kein Release mit ISO existiert, wird gerade die erste gebaut bzw. du kannst sie selbst erzeugen (siehe unten).

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
