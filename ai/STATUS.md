# Projektstatus

Stand: 2026-08-21

Anwendungs-Baseline: `5f3acd2` (`main`, mit `origin/main` synchron)

Release-Entscheidung: **NO-GO für produktive Nutzung**

Aktiver Task: `TASK-001`

## Funktionsstand

- Vollständiger 9-Schritte-Web-Wizard mit expliziter Löschfreigabe
- Whole-Disk-Installation für x86_64/UEFI, Secure Boot aus
- Direkte Provisionierung für Debian 13 und die zur Laufzeit ermittelte aktuelle
  Ubuntu-LTS-Version, jeweils Desktop und Server
- Chef-GRUB, echte UUIDs/PARTUUIDs und abgesicherte Zielplattenidentität
- Add/Remove, Fedora, Arch und Proxmox bewusst gesperrt
- Automatisierte Baseline: `122 passed`, Ruff, Shell-Syntax und ShellCheck grün

## Aktueller Blocker

Die reale Debian-Installation stoppt sicher vor dem Wipe bei der Prüfung von
`trixie/InRelease`. Das ISO enthält aus Ubuntu Noble
`debian-archive-keyring 2023.4ubuntu1` und damit nicht die Debian-13-Schlüssel.
Das aktuelle, dreifach signierte Debian-13.6-Manifest ergibt damit `gpgv` Exit
2. Mit `debian-archive-keyring 2025.1` werden alle Signaturen verifiziert und
`gpgv` endet mit Exit 0. Details: `ai/tasks/TASK-001.md`.

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
