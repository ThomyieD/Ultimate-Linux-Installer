# Arbeitsregeln für KI-Agenten

Diese Datei ist die gemeinsame Verfassung für Codex/Sol und Cursor. Sie gilt
für das gesamte Repository.

## Rollen

- **Codex/Sol ist Lead und Reviewer.** Codex analysiert, plant, schreibt Tasks
  und Reviews und kontrolliert Ergebnisse. Codex ändert in diesem Arbeitsmodell
  keinen Anwendungscode.
- **Cursor ist Implementierungsagent.** Cursor bearbeitet genau den in
  `ai/ACTIVE_TASK` genannten Task und trifft keine neuen Produkt- oder
  Sicherheitsentscheidungen.
- Es schreibt immer nur ein Agent gleichzeitig im Working Tree. Vor dem
  Wechsel wird der laufende Agent beendet.

## Maßgebliche Unterlagen

In dieser Reihenfolge gelten:

1. `AGENTS.md`
2. der aktive Task aus `ai/ACTIVE_TASK`
3. `docs/architecture/overview.md`
4. `docs/architecture/decisions.md`
5. `docs/quality/quality-gates.md`
6. `README.md`
7. ursprüngliche Vorgaben unter `docs/reference/`

Bei einem Widerspruch stoppt der Implementierungsagent und dokumentiert ihn im
Handover. Architekturentscheidungen werden nicht stillschweigend geändert.

## Task-Ablauf

- Produktänderungen benötigen genau einen aktiven Task unter `ai/tasks/`.
- Nur der dort genannte Scope und die dort freigegebenen Dateien dürfen
  bearbeitet werden.
- Kein opportunistisches Refactoring und keine Umsetzung späterer Tasks.
- Cursor verändert weder den Task noch `ai/STATUS.md`, `ai/ROADMAP.md`,
  `docs/architecture/decisions.md` oder Review-Dateien.
- Cursor schreibt am Ende ausschließlich seinen Bericht nach
  `ai/handovers/<TASK-ID>.md`.
- Codex schreibt das Ergebnis der Kontrolle nach `ai/reviews/<TASK-ID>.md`.
- Ein Task ist erst nach einem Review mit `APPROVED` abgeschlossen.

## Sicherheitsregeln

ULI kann reale Datenträger vollständig löschen. Deshalb gilt ausnahmslos:

- Keine echten Installationen, Partitionierungen, Formatierungen, Reboots oder
  NVRAM-Änderungen während normaler Entwicklung und Review.
- Keine Ausführung von ISO-Builds mit `sudo`, außer der Nutzer erlaubt dies für
  den konkreten Task ausdrücklich.
- Destruktive Pfade bleiben fail-closed. Tests dürfen Schutzprüfungen nicht
  abschwächen oder umgehen.
- Keine Shell-Interpolation für Gerätepfade oder benutzerkontrollierte Werte.
- Keine neuen Produktionsabhängigkeiten ohne ausdrückliche Task-Freigabe.
- Vertrauensanker, Schlüssel, Checksummen und Paketquellen sind
  Supply-Chain-Sicherheitsgrenzen. HTTPS allein ersetzt keine kryptografische
  Verifikation.
- Tests werden nicht gelöscht, übersprungen oder gelockert, nur damit eine
  Änderung grün wird.

## Prüfen und Git

- Nach jeder Implementierung wird `./scripts/check.sh` ausgeführt.
- Zusätzlich gelten die task-spezifischen Tests und Quality Gates.
- Cursor erstellt keine Commits, pusht nicht und verändert keine Git-Historie.
- Kein Force-Push, kein Rebase veröffentlichter Branches und kein
  `git reset --hard`.
- Unabhängige Nutzeränderungen werden nicht überschrieben oder aufgeräumt.
- ISO-, Image- und Cache-Dateien bleiben außerhalb von Git.

## Blocker und Handover

Wenn Informationen fehlen, ein Test reale Hardware benötigt oder der Task eine
neue Architekturentscheidung erzwingen würde, stoppt Cursor. Der Handover muss
enthalten: geänderte Dateien, Begründung, ausgeführte Befehle mit Ergebnissen,
offene Risiken und einen reproduzierbaren Blocker.
