# Projektstatus

Stand: 2026-08-21

Anwendungs-Baseline: `5a696df`

Planungs-Baseline: `a4c20ac` (`main`, mit `origin/main` synchron vor TASK-004)

Release-Entscheidung: **NO-GO für produktive Nutzung**

Aktiver Task: `TASK-004` – READY_FOR_CURSOR

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
- Gate E ist fehlgeschlagen und bleibt offen. Die Vertrauenskette aus TASK-001
  funktioniert: der Laptoplauf protokolliert erfolgreich
  `verified sources: debian-trixie-InRelease` und erreicht die
  Paketinstallation. Er scheitert erst danach bei 59 Prozent am nicht
  existierenden Paket `task-standard`.
- Der Laptoplauf hatte zu diesem Zeitpunkt Partitionstabelle und Dateisysteme
  bereits erstellt. Der Testdatenträger enthält deshalb nur eine partielle,
  nicht freigegebene Installation.
- VMware erkennt die 40-GiB-Testdisk korrekt. Der frische Wizard reserviert
  aber standardmäßig 1 GiB ESP, 1 GiB Reserve, 8 GiB Swap, 64 GiB Daten und
  mindestens 20 GiB Root; der angeforderte Plan braucht damit etwa 94 GiB.
- `TASK-004` behebt beide Gate-E-Blocker, prüft benannte Pakete isoliert vor
  dem Wipe und macht das vollständige Fehlerprotokoll exportierbar.

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
- Bis TASK-004 darf kein weiterer produktiver oder ungesicherter Debian-
  Installationsversuch erfolgen. Als vorläufiger VMware-Workaround passt eine
  einfache Debian-Installation auf 40 GiB, wenn die gemeinsame Datenpartition
  in den Einstellungen bewusst deaktiviert wird; der Paketfehler bleibt im
  aktuellen ISO trotzdem bestehen.
- Die frühere `[object Object]`-Meldung wird im aktuellen Frontend formatiert;
  ältere Test-ISOs enthalten diesen Fix möglicherweise noch nicht.
