# Projektstatus

Stand: 2026-08-21

Anwendungs-Baseline: `75fc70a`

Planungs-Baseline: `786d11c` (TASK-004-Plan)

Release-Entscheidung: **NO-GO für produktive Nutzung**

Aktiver Task: `TASK-004` – APPROVED / Gate D PASS / Gate E ausstehend

## Funktionsstand

- Vollständiger 9-Schritte-Web-Wizard mit expliziter Löschfreigabe
- Whole-Disk-Installation für x86_64/UEFI, Secure Boot aus
- Direkte Provisionierung für Debian 13 und die zur Laufzeit ermittelte aktuelle
  Ubuntu-LTS-Version, jeweils Desktop und Server
- Chef-GRUB, echte UUIDs/PARTUUIDs und abgesicherte Zielplattenidentität
- Add/Remove, Fedora, Arch und Proxmox bewusst gesperrt
- Automatisierte Baseline: `152 passed`, 1 optionaler Test übersprungen;
  Ruff, Shell-Syntax und ShellCheck grün

## Aktueller Prüfstand

- TASK-004 wurde unter `75fc70a` implementiert, im Codex-Review freigegeben und
  auf `origin/main` veröffentlicht.
- Ein frisches ISO wurde am 2026-08-21 aus diesem Commit erfolgreich gebaut.
- Gate D ist bestanden: SHA-256, Hybrid-/UEFI-Struktur, beide `BOOTX64.EFI`,
  Debian-13-Keyring im SquashFS und QEMU-OVMF-Live-Boot bis
  `ULI_LIVE_READY` wurden geprüft.
- Artefakt:
  `artifacts/ultimate-linux-installer-0.3.0-amd64.iso`
- SHA-256:
  `9cf89c070c5ac690506ff3665e4595e6b4b1936d811292cac28e1cb56b9a2c7e`
- TASK-004 deaktiviert die optionale 64-GiB-Datenpartition im frischen
  Standardzustand, ersetzt den ungültigen Debian-Paketpfad durch `tasksel`,
  prüft alle benannten Pakete isoliert vor dem Wipe und exportiert ein
  redigiertes vollständiges Installationslog.
- Der frühere Gate-E-Lauf bleibt historisch fehlgeschlagen. Ein neuer
  vollständiger Gate-E-Lauf mit dem aktuellen ISO wurde noch nicht ausgeführt.

## Bekannte Inkonsistenzen und Risiken

- Der reale Ubuntu-Pfad ermittelt 26.04 LTS (`resolute`) zur Laufzeit, aber das
  Noble-Live-Chroot enthält `debootstrap 1.0.134ubuntu2` ohne Suite-Skript
  `resolute`. Die Quellprüfung kann deshalb erfolgreich sein, während die
  eigentliche Ubuntu-Provisionierung später scheitert. README, Architekturtext
  und Legacy-Adapter nennen außerdem teils noch 24.04/noble. Das ist der
  nachfolgende P0-Task `TASK-002`.
- Ein kompletter zerstörender VM-Durchlauf mit anschließendem Boot aller
  installierten Einträge ist noch nicht abgenommen.
- Automatische Wiederaufnahme nach Stromausfall ist nicht freigegeben.
- Das neue ISO ist ausschließlich ein Gate-D-Testartefakt. Eine produktive
  Freigabe erfordert weiterhin Gate E sowie die nachfolgenden P0-Arbeiten.
- Die frühere `[object Object]`-Meldung wird im aktuellen Frontend formatiert;
  ältere Test-ISOs enthalten diesen Fix möglicherweise noch nicht.
