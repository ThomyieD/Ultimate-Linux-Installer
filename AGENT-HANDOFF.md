# Agent-Handoff: Ultimate Linux Installer

> **Aktualisierung 2026-08-21 — maßgeblicher Stand**
>
> Die nachfolgenden Abschnitte dokumentieren den historischen Ausgangspunkt
> und sind teilweise überholt. Der aktuelle Implementierungsstand ist:
>
> - Version **0.3.0**: primäre Firefox-Kiosk-Weboberfläche mit dem vollständigen
>   9-Schritte-Ablauf, überprüfbarer Löschfreigabe und vollständigen
>   Benutzer-/SSH-/Locale-/GRUB-/Partitions-Einstellungen.
> - Reale, sichere Direkt-Provisionierung für **Debian 13** sowie **Ubuntu LTS**
>   (Desktop und Server): signiertes APT-InRelease vor jedem Wipe, debootstrap,
>   Systemkonfiguration und zentraler Chef-GRUB. Add/Remove, Fedora, Arch und
>   Proxmox bleiben bewusst gesperrt.
> - Storage ist Whole-Disk-only und mehrfach gegen falsche/ausgetauschte
>   Datenträger abgesichert (by-id, Serial/WWN, Kernel-Disksequence und offene
>   FD-Bindung). Keine ISO-/Release-Artefakte in Git.
> - Ubuntu wird zur Laufzeit über Canonicals Release-Index auf die aktuelle LTS
>   aufgelöst und anschließend über das signierte APT-InRelease verifiziert.
> - ISO-Build: ausschließlich `scripts/build-iso-simple.sh`; v0.3.0 wurde
>   erfolgreich per UEFI-QEMU gebootet. Nach dem DNS-Fix verwendet die Live-ISO
>   die direkt von NetworkManager per DHCP erhaltenen Resolver.
> - Stand der Nutzererprobung: ISO wird in VMware Workstation getestet.
>   `disk.EnableUUID = "TRUE"` ist für eine stabile VMware-Zieldisk erforderlich.
>   Vor einem GitHub Release sind mindestens ein vollständiger VM-Installations-
>   und Boot-Regressionstest erforderlich.

Stand: 2026-08-13
Vorheriger Chat: [Ultimate Linux Installer design](5bb26b92-179d-4c70-b7a7-4a8d1c6f19e1)

Dieses Dokument fasst den bisherigen Arbeitsstand zusammen, damit ein anderer Agent nahtlos weitermachen kann.

---

## Ziel des Projekts

UEFI-Multiboot-Linux-Installer:

1. Von USB booten
2. Grafischer Installer (kein manuelles Live-Desktop-Gefrickel)
3. Distros von offiziellen Spiegeln laden
4. Unbeaufsichtigte Installation
5. Zentrales GRUB (`EFI/UltimateInstaller`)

- **UI-Sprache:** Deutsch Standard, Englisch umschaltbar
- **Repo:** https://github.com/ThomyieD/Ultimate-Linux-Installer
- **Lokaler Workspace (QNAP):** `Z:\Neu\Ultimate-Linux-Installer`
- **Build-Host:** `dbk-dev` → `/root/Linux-Installer/github/Ultimate-Linux-Installer`
- **Wichtig:** ISO/Releases **nicht** hochladen, bis der User bestätigt, dass es funktioniert

---

## Git-Stand (bereits gepusht)

- Branch: `main`
- Letzter Commit: `0c7b9ad` — *Add web installer UI with network, storage preview, and install job*
- Remote: `git@github.com:ThomyieD/Ultimate-Linux-Installer.git` (SSH auf `dbk-dev`)
- **Nicht im Git:** `artifacts/`, `*.iso`, `.venv/`, `tmp-upload/`
- `pyproject.toml` Version steht noch auf `0.1.0` (ISO-Builds heißen intern `0.2.x`)

Git auf dem Windows/QNAP-Pfad kann wegen *dubious ownership* scheitern → **Commit/Push bevorzugt von `dbk-dev`**.

---

## Architektur (aktuell)

### Primär-UI: Web (FastAPI + Firefox-Kiosk)

- Einstieg: `--ui web` (Default im Live-System)
- Server: FastAPI auf `127.0.0.1:8787`
- Browser: Mozilla-Firefox-Tarball unter `/opt/firefox` (Ubuntu-`firefox`-Paket ist nur Snap-Stub)
- Live-Start: `/usr/local/bin/uli-start` → uvicorn → Firefox-Kiosk
- Qt bleibt als Fallback: `uli --ui qt`

### Wichtige Codepfade

| Bereich | Pfad |
|--------|------|
| Web-API | `app/uli/web/server.py` |
| Web-Frontend | `app/uli/web/static/{app.js,styles.css,index.html}` |
| Netzwerk | `app/uli/network/connectivity.py` |
| Storage | `app/uli/storage/{disks,layout,executor}.py` |
| Install-Job | `app/uli/install/{isos,job}.py` |
| Downloads | `app/uli/downloads/__init__.py` |
| Adapter | `adapters/` (auch in dist-packages im ISO-Chroot) |
| ISO-Build | `scripts/build-iso-simple.sh`, `scripts/lib-iso-uefi.sh` |
| Fix-/Diag-Skripte | `scripts/fix-*.sh`, `scripts/diag-*.sh`, `scripts/rebuild-*.sh` |

---

## Was bisher gebaut / gefixt wurde

### 1. Web-Installer statt Qt-Only

- FastAPI-Backend + statisches Frontend
- Firefox-Kiosk im Live-ISO
- Optimistische UI-Updates, Sprachumschaltung DE/EN
- Layout: `100dvh`, nur `.main` scrollt (keine doppelten Scrollbars am Shell)

### 2. API-Body-Bug (kritisch)

- Nested Pydantic-Models + `from __future__ import annotations` → FastAPI behandelte Body als Query (`Field required loc query body`)
- Fix: **module-level** Models + `POST /api/state`

### 3. Netzwerk

- Bridged/LAN-DHCP über NetworkManager
- Robuste Connectivity-Checks
- Wi‑Fi über `wpasupplicant` / `rfkill` / sysfs
- Button „Kabelverbindung herstellen“
- VMware: `open-vm-tools` (+ desktop), vmware video, `xrandr` / `vmware-user` in `uli-start`

### 4. Storage-UI

- Echte Disk-Liste: `/api/disks`
- Partition-Preview: `/api/storage/preview`
- Soft-Fit für kleine Disks (z. B. 20 GiB VM vs. Ubuntu-25 GiB-Minimum) mit Warnung

### 5. Install-Schritt (früher Fake-„Fertig“)

Nach Partitionierung folgt Schritt **Installation**, kein Fake-Ende.

Aktueller Job kann:

1. ISO-URLs auflösen
2. ISOs mit Fortschritt laden
3. Plan / Autoinstall / Hooks / GRUB-Artefakte schreiben
4. Partitionstabelle live anwenden (`sudo -n`)

**Noch nicht:** Distro-Installer aus der heruntergeladenen ISO tatsächlich starten (unattended autoinstall/casper/etc.).

Ehrlicher Done-Text: Vorbereitung fertig; vollständige unbeaufsichtigte Installation aus der Distro-ISO ist **noch nicht** abgeschlossen.

### 6. Cache / Rechte (0.2.9)

- Problem: `[Errno 13] Permission denied: '/var/cache/uli/…'`
- Fix: schreibbaren Cache erkennen + `chmod 1777` / chown
- sudoers: `uli ALL=(root) NOPASSWD:ALL` (sollte später enger werden)
- „Weiter“ deaktiviert, solange Install-Status ≠ `done`; Retry über „Erneut versuchen“

### 7. ISO-Build / Kernel-Panic-Fix

- Squashfs: **nicht** `proc`/`sys`/`dev`/`run`/`tmp` excluden — nur `boot`
- Chroot-Mounts vor `mksquashfs` immer unmounten
- live-build-Hooks teilweise entfernt/ersetzt durch einfachen Builder (`build-iso-simple.sh`)
- Skripte auf Linux: **LF** (CRLF bricht bash)

### 8. Adapter-Packaging

- `ensure_builtin_adapters` sucht Repo-Root **und** dist-packages (Adapter neben `uli` im ISO)

---

## Aktuelle ISO

Lokal / auf Build-Host:

- `artifacts/ultimate-linux-installer-0.2.9-amd64.iso` (~1.2 GB)
- Artifacts sind gitignored

Neueste Fixes ab 0.2.8/0.2.9: Install-Flow, Cache/Sudo, Storage-Preview, Web-UI.

---

## Test-Hinweise (VMware)

- Bridged Networking
- `open-vm-tools` für Display
- Für Ubuntu-Desktop-Tests eher ≥ 40 GiB Disk (20 GiB zeigt Soft-Fit-Warnung)
- Nach Install-Fehler: „Weiter“ bleibt gesperrt bis Erfolg

---

## Nächste Produktarbeit (Priorität)

1. **Unbeaufsichtigte Installation aus geladener Distro-ISO**
   (aktuell nur Download + Artefakte + Partitionierung)
2. Sudoers enger als `NOPASSWD:ALL`
3. `pyproject.toml`-Version an ISO-Serie (`0.2.x`) angleichen
4. Erst nach User-OK: ISO an GitHub Release hängen
5. README noch Qt-lastig → Web-UI als Primärweg dokumentieren

---

## Arbeitsweise / Konventionen

- Build & Git: auf **`dbk-dev`** arbeiten
- QNAP-Workspace kann für Edit synchron sein; Sync ggf. per `scp` von Windows → `dbk-dev`
- Keine ISO/Release-Uploads ohne explizite User-Freigabe
- Commits nur auf User-Wunsch; kein Force-Push auf `main`
- Prefer LF in Shell-Skripten
- UI-Texte: Deutsch zuerst (`app/uli/i18n/de.json`, `en.json`)

---

## Kurz: Was der nächste Agent tun sollte

Wenn die Frage „was nun?“ ist: **den Install-Job von „ISO laden + partitionieren + Artefakte schreiben“ zu „Distro wirklich unattended installieren“ erweitern** — das ist die größte offene Lücke zum Produktziel.

Bei Bugs in Live-ISO: passende `scripts/fix-*.sh` / Rebuild (`rebuild-iso-full.sh` / `rebuild-iso-boot.sh`) auf `dbk-dev` nutzen, nicht blind live-build wieder einführen.
)
