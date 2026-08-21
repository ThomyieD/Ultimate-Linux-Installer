# TASK-002 – Aktuelle Ubuntu-LTS wirklich provisionierbar machen

Status: PLANNED / erst nach APPROVED für TASK-001 aktivieren

Priorität: P0 / Ubuntu-26.04-Pfad ist aktuell nicht ausführbar

Owner: Cursor

Reviewer: Codex/Sol

## Ziel

Die vom Laufzeitresolver ermittelte aktuelle Ubuntu-LTS-Version muss mit dem
generischen Ubuntu-`debootstrap`-Skript des Live-Systems installierbar sein,
auch wenn für den neuen Codenamen noch kein Suite-Symlink im Noble-Paket liegt.
UI, Plan, Provisioner, Legacy-Adapter und Dokumentation dürfen keine
widersprüchlichen Versionen anzeigen.

## Ausgangssituation und Beleg

- Der Resolver wählt aktuell Ubuntu 26.04 LTS / `resolute` und das offizielle
  `InRelease` ist erreichbar.
- Das gebaute Noble-Chroot enthält `debootstrap 1.0.134ubuntu2`.
- `/usr/share/debootstrap/scripts/resolute` fehlt.
- Der vorhandene generische Ubuntu-Handler
  `/usr/share/debootstrap/scripts/gutsy` behandelt unbekannte neuere Suites;
  `noble` ist selbst nur ein Symlink auf diesen Handler.
- `Provisioner._debootstrap()` übergibt aktuell kein explizites Skript. Dadurch
  bricht `debootstrap resolute ...` trotz erfolgreicher Quellenprüfung ab.
- README/Architektur und `adapters/ubuntu` enthalten noch statische
  24.04-/noble-Angaben, obwohl die reale Pipeline 26.04 dynamisch plant.

## Vorgesehener Scope

1. Für Ubuntu explizit den vorhandenen generischen Ubuntu-Suite-Handler an
   `debootstrap` übergeben; Debian behält seinen eigenen normalen Suitepfad.
2. Die Existenz und Eignung des benötigten Skripts im Realmodus vor dem Wipe
   prüfen und im ISO-Verifier absichern.
3. Tests ergänzen, die für eine zukünftige LTS ohne namensgleichen Symlink den
   generischen Ubuntu-Handler verlangen und Debian unverändert lassen.
4. Statische Ubuntu-Releasewerte im Legacy-Adapter nicht duplizieren, sondern
   auf die zentrale Source-Auflösung zurückführen oder als nicht maßgeblichen
   Pfad entfernen.
5. README DE/EN und Architektur auf „aktuelle unterstützte Ubuntu LTS“ mit
   26.04 als aktuellem Beispiel korrigieren.
6. Einen nichtdestruktiven Integrationsnachweis für `debootstrap --print-debs`
   oder eine gleichwertige Bootstrap-Vorprüfung gegen `resolute` dokumentieren.

## Nicht-Scope

- weitere Distributionen
- Wechsel der Live-ISO-Basis
- ein zerstörender VM-Lauf; dieser folgt in TASK-003
- blindes Akzeptieren jedes zukünftigen Ubuntu-Releases ohne signierte Quelle
  und Bootstrap-Fähigkeitsprüfung

## Vor Aktivierung noch festzulegen

Codex aktualisiert Baseline, erlaubte Dateien, exakte Akzeptanzkriterien und
Testbefehle erst nach dem APPROVED-Review von TASK-001. Cursor darf diesen Task
vorher nicht beginnen.
