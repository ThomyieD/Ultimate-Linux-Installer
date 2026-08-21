# Architekturübersicht (v0.3)

## Produktgrenzen

ULI v0.3 ist ein x86_64-Whole-Disk-Installer für UEFI-Systeme mit deaktiviertem Secure Boot. Er unterstützt zwei ausführbare Modi:

| Modus | Verhalten in v0.3 |
|---|---|
| Einfach | Genau eine freigegebene Distribution, der gewählte Datenträger wird vollständig neu aufgebaut |
| Multiboot | Mindestens zwei freigegebene Distributionen, gemeinsame ESP, eigene ext4-Root-Partitionen |
| Hinzufügen | In der UI sichtbar, technisch gesperrt |
| Entfernen | In der UI sichtbar, technisch gesperrt |

Als reale Zielsysteme sind derzeit Debian 13 und Ubuntu 24.04 LTS freigegeben, jeweils als Desktop oder Server. Fedora, Arch Linux und Proxmox VE sind Katalog-/Roadmap-Einträge und werden vom Backend als nicht freigegeben abgewiesen. Proxmox bleibt im Zielbild auf den einfachen Modus beschränkt.

## Laufzeitarchitektur

```text
UEFI-Firmware (Secure Boot aus)
  └─ USB: hybrides Ubuntu-Noble-Live-Image
      ├─ LightDM + Openbox + Firefox im Kiosk-Modus (unprivilegierter Benutzer)
      └─ systemd: privilegierter lokaler ULI-Webdienst
          ├─ FastAPI: validierter Zustand und Bestätigungsprotokoll
          ├─ Storage: Erkennung, Layout, Partitionierung, Dateisysteme
          ├─ Sources: InRelease-Download und gpgv-Prüfung
          ├─ Provisioning: debootstrap, APT und chroot-Konfiguration
          ├─ State: atomisches Installationsjournal
          └─ Bootloader: gemeinsamer GRUB und Distro-Update-Hooks
```

Die primäre Oberfläche ist kein eingebetteter Distro-Installer, sondern ein lokaler Web-Kiosk. Der Browser ist reine Darstellungsschicht und besitzt keine Root-Rechte. Die frühere PySide6-Oberfläche bleibt ausschließlich als erzwungener Dry-Run-Entwicklungspfad vorhanden und kann keine reale Installation starten.

## Neun Schritte der Oberfläche

1. **Netzwerk:** Ethernet/WLAN erkennen, verbinden und Internetzugriff prüfen
2. **Modus:** einfache Installation oder Multiboot wählen; Hinzufügen/Entfernen als gesperrt kennzeichnen
3. **Distributionen:** nur freigegebene Kombinationen auswählbar machen
4. **Quellen:** Version, offizieller Spiegel und Prüfverfahren transparent anzeigen
5. **Einstellungen:** Benutzer, gehashtes Passwort, Hostnamen je System, SSH, Sprache, Tastatur, Zeitzone, DHCP, Partitionen und Bootmenü
6. **Speicher:** vom Backend erkannte Datenträger wählen und das berechnete GPT-Layout anzeigen
7. **Prüfung:** Löschwirkung, Warnungen und SHA-256-Plan-Fingerabdruck anzeigen; ausdrückliche Zustimmung einholen
8. **Installation:** Backend-Phasen, aktuelle Distribution und Protokoll verfolgen
9. **Abschluss:** nur nach realem Erfolg einen Neustart anbieten; Dry-Run eindeutig als Simulation ausweisen

## Vertrauensgrenze und Bestätigung

Der Browser darf keinen Linux-Gerätepfad und keine behauptete Datenträgergröße übergeben. `GET /api/disks` liefert eine opake ID; das Backend löst diese ID bei Vorschau, Bestätigung und Start erneut gegen die aktuelle Blockgeräteerkennung auf. Installationsmedium, gemountete Geräte und aktive Swap-Ziele werden ausgeschlossen beziehungsweise unmittelbar vor der Änderung abgewiesen.

```text
validierter Wizard-Zustand + aktuelle Disk-Identität
  → unveränderlicher Installationsplan
  → kanonischer SHA-256-Fingerabdruck
  → ausdrückliche Bestätigung
  → kurzlebiges Einmal-Token
  → erneute Prüfung von Revision, Token und Disk
  → plan.confirmed = true
  → Orchestrator darf starten
```

Jede Zustandsänderung entwertet Vorschau und Token. Nur `simple`/`multiboot` mit `wipe=true` gelangen zum Storage-Executor. Kommandos werden als Argumentlisten ohne Shell-Interpolation ausgeführt. Das Benutzerpasswort wird früh gehasht; öffentliche Zustände, Audit-Dateien und Fortschrittsmeldungen enthalten weder Klartextpasswort noch Passwort-Hash.

## Installationspipeline

1. Plan, Modus, UEFI/x86_64 und Secure-Boot-Zustand fail-closed validieren; GRUB-Konfiguration, Fonts, Module und einen echten temporären EFI-Loader vorab bauen.
2. Für jede verwendete Distribution das offizielle HTTPS-`InRelease` laden und mit dem mitgelieferten Debian-/Ubuntu-Archiv-Keyring über `gpgv` prüfen.
3. Erst danach den ausgewählten Datenträger als GPT neu aufbauen und ESP, Root- sowie optionale Swap-/Datenpartitionen formatieren.
4. Echte UUIDs/PARTUUIDs nach dem Formatieren erneut einlesen.
5. Debian 13 (`trixie`) beziehungsweise Ubuntu 24.04 LTS (`noble`) mit `debootstrap` direkt in die jeweilige Root-Partition installieren.
6. APT-Quellen, Desktop-/Server-Pakete, Benutzer, sudo, SSH, Locale, Tastatur, Zeitzone, DHCP, `fstab`, Swap und Initramfs im chroot konfigurieren.
7. Jede Root-Installation prüfen und stabile Kernel-/Initrd-Verweise samt Update-Hook einrichten.
8. Aus den realen Kennungen ein minimales zentrales `grub.cfg` erstellen, Syntax prüfen und GRUB unter `EFI/UltimateInstaller` sowie als Fallback unter `EFI/BOOT` installieren.
9. Einen an die aktuelle ESP-PARTUUID gebundenen UEFI-NVRAM-Eintrag setzen, `UltimateInstaller` nachweislich an die erste Stelle der Bootreihenfolge bringen und andernfalls nicht als abgeschlossen melden.
10. Abschlusszustand atomisch schreiben; nur eine reale, vollständig erfolgreiche Installation erlaubt den Neustart über die API.

Die Distributionen werden somit nicht als ISO-Dateien heruntergeladen oder als fremde GUI-Installer ineinander gestartet. Für den aktuell unterstützten Debian-/Ubuntu-Pfad ist die signierte Paketquelle die Installationsquelle.

## Partitions- und Bootmodell

Ein neuer Plan enthält eine FAT32-ESP, eine ext4-Root-Partition pro Distribution und optional Swap beziehungsweise eine gemeinsame Datenpartition. Mindestgrößen der Adapter werden strikt geprüft. Bei gleichmäßiger Aufteilung wird nur tatsächlich verfügbarer Platz verteilt; bei individueller Aufteilung werden die gewünschten Root-Größen und der verbleibende Platz validiert.

Chef-GRUB verwendet direkte `search --fs-uuid`-/`linux`-Einträge anstelle von `os-prober`. Pro Distribution erscheint ein sauberer Haupteintrag; der Firmware-Eintrag bleibt zuletzt. Theme, Anzeigenamen, Standardsystem und Timeout stammen aus dem bestätigten Plan. Kernel-Update-Hooks in den Zielsystemen halten die stabilen Kernel-/Initrd-Pfade aktuell.

## Zustand und Wiederaufnahme

Das Installationsjournal kennt unter anderem die Phasen `validated`, `sources_verified`, `partitioning`, `filesystems`, `installing`, `verifying`, `bootloader`, `completed` und `failed`. Es wird mit restriktiven Rechten atomisch ersetzt. Das schafft die Grundlage für Diagnose und spätere Wiederaufnahme.

Die lückenlose Wiederaufnahme nach einem Stromausfall an jedem Pipeline-Punkt ist noch nicht abgenommen. Das Journal darf deshalb derzeit nicht als Garantie verstanden werden, eine unterbrochene reale Installation automatisch fertigzustellen.

## Build und Veröffentlichung

`sudo scripts/build-iso.sh` ist der kanonische Builder. Er erzeugt ein Ubuntu-Noble-basiertes Live-System mit Python-Laufzeit, lokalem Webdienst, Firefox-Kiosk, Netzwerk/Firmware, Storage-/APT-/GRUB-Werkzeugen und hybridem BIOS-/UEFI-Boot-Layout. Das Produktziel und der freigegebene Installationsmodus bleiben UEFI; die BIOS-Bootfähigkeit des Mediums erweitert nicht den unterstützten Zielumfang.

Lokale Images und Prüfsummen liegen unter `artifacts/`. Große ISO-Dateien werden nicht in Git versioniert. Der manuell ausgelöste GitHub-Workflow veröffentlicht zunächst ein Workflow-Artefakt; ein Upload zu [GitHub Releases](https://github.com/ThomyieD/Ultimate-Linux-Installer/releases) erfolgt nur mit ausdrücklich angegebenem Release-Tag.

## Prüfung und offene Abnahme

Automatisierte Unit-, API- und Dry-Run-Tests prüfen unter anderem Layoutgrenzen, verbotene Modi/Distributionen, Secret-Redaktion, Bestätigungstoken, sichere Befehlsübergabe, Provisionierungspläne und GRUB mit echten Kennungen. Der ISO-Check prüft Struktur und UEFI-Bootbestandteile; QEMU dient als Wegwerf-Testumgebung.

Nicht abgeschlossen sind die destruktive Hardware-End-to-End-Abnahme aller vier freigegebenen Varianten, eine breite Hardwarematrix, Secure Boot, die zusätzlichen Distributionen und sichere Bestandsänderungen für Hinzufügen/Entfernen. Bis dahin ist v0.3 als technisch testbarer Integrationsstand zu behandeln, nicht als auf beliebiger Hardware abgenommenes Produktionswerkzeug.
