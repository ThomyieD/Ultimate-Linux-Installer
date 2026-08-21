# Projektstatus

Stand: 2026-08-21

Anwendungs-Baseline: `5a696df` (`main`, mit `origin/main` synchron)

Release-Entscheidung: **NO-GO für produktive Nutzung**

Aktiver Task: `TASK-001` – Implementierung freigegeben, Gate E ausstehend

## Funktionsstand

- Vollständiger 9-Schritte-Web-Wizard mit expliziter Löschfreigabe
- Whole-Disk-Installation für x86_64/UEFI, Secure Boot aus
- Direkte Provisionierung für Debian 13 und die zur Laufzeit ermittelte aktuelle
  Ubuntu-LTS-Version, jeweils Desktop und Server
- Chef-GRUB, echte UUIDs/PARTUUIDs und abgesicherte Zielplattenidentität
- Add/Remove, Fedora, Arch und Proxmox bewusst gesperrt
- Automatisierte Baseline: `134 passed`, 1 optionaler Test übersprungen;
  Ruff, Shell-Syntax und ShellCheck grün

## Aktueller Prüfstand

- TASK-001 wurde unter `5a696df` implementiert und im Codex-Review freigegeben.
- Ein frisches ISO wurde am 2026-08-21 erfolgreich gebaut.
- Gate D ist bestanden: SHA-256, Hybrid-/UEFI-Struktur, Debian-13-Keyring im
  SquashFS und QEMU-OVMF-Live-Boot bis zum gesunden ULI-Backend wurden geprüft.
- Artefakt:
  `artifacts/ultimate-linux-installer-0.3.0-amd64.iso`
- SHA-256:
  `cf9fe39c5d2bbff58b2eb75995412639b20532249ecfe7502d0569c4846f24c7`
- Gate E bleibt offen: die korrigierte Debian-Installation muss noch auf einer
  entbehrlichen Testdisk vollständig bis zum Boot des Zielsystems laufen.

## Bekannte Inkonsistenzen nach TASK-001

- Der reale Ubuntu-Pfad ermittelt 26.04 LTS (`resolute`) zur Laufzeit, aber das
  Noble-Live-Chroot enthält `debootstrap 1.0.134ubuntu2` ohne Suite-Skript
  `resolute`. Die Quellprüfung kann deshalb erfolgreich sein, während die
  eigentliche Ubuntu-Provisionierung später scheitert. README, Architekturtext
  und Legacy-Adapter nennen außerdem teils noch 24.04/noble. Das ist der
  nachfolgende P0-Task `TASK-002`.
- Ein kompletter zerstörender VM-Durchlauf mit anschließendem Boot aller
  installierten Einträge ist noch nicht abgenommen.
- Automatische Wiederaufnahme nach Stromausfall ist nicht freigegeben.
- Die frühere `[object Object]`-Meldung wird im aktuellen Frontend formatiert;
  ältere Test-ISOs enthalten diesen Fix möglicherweise noch nicht.
