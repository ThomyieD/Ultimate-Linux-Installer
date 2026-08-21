# Arbeitsablauf Codex/Sol ↔ Cursor

Dieses Verzeichnis setzt den in `docs/reference/Aufbau.txt` beschriebenen
Lead-/Worker-Ablauf für ULI um. Es gibt immer genau einen aktiven Task.

## Zuständigkeiten

```text
Nutzer → Codex plant → Cursor implementiert → Codex reviewt
                                      ↑              │
                                      └── Rework ────┘
```

Codex ändert in diesem Modell nur Planungs-, Task- und Reviewunterlagen. Cursor
ändert nur die im aktiven Task freigegebenen Implementierungsdateien.

## Ablauf eines Tasks

1. Codex aktualisiert `ai/STATUS.md`, `ai/ROADMAP.md`, den Task und
   `ai/ACTIVE_TASK`.
2. Die Planungsänderungen werden als Sicherheitsnetz committed und zum Remote
   gepusht, bevor Cursor Produktcode verändert.
3. Cursor liest `AGENTS.md` und den aktiven Task vollständig, implementiert den
   Scope und führt `./scripts/check.sh` plus die Task-Checks aus.
4. Cursor schreibt `ai/handovers/<TASK-ID>.md`, aber committet und pusht nicht.
5. Codex prüft Git-Diff, Akzeptanzkriterien, Tests, Sicherheitsgrenzen und
   schreibt `ai/reviews/<TASK-ID>.md` mit `APPROVED` oder `CHANGES_REQUESTED`.
6. Bei Mängeln bearbeitet Cursor nur die bestätigten Reviewpunkte. Danach folgt
   ein neues Codex-Review.
7. Erst nach `APPROVED` werden Änderung, Commit und Push vom Nutzer freigegeben.

## Verzeichnisstruktur

- `STATUS.md`: knapper, aktueller Projekt- und Freigabestand
- `ROADMAP.md`: priorisierte Folgearbeit und Abhängigkeiten
- `ACTIVE_TASK`: Pfad zum einzigen aktiven Task
- `tasks/`: unveränderliche Arbeitsaufträge des Leads
- `handovers/`: Implementierungsberichte von Cursor
- `reviews/`: Prüfberichte von Codex
- `prompts/`: kurze, wiederverwendbare Übergabetexte

Vor dem Start von Cursor muss `git status` einen bekannten Zustand zeigen.
Codex und Cursor dürfen niemals gleichzeitig in demselben Working Tree
schreiben. Ein eigener Git-Worktree pro Task ist später möglich, für den ersten
Durchlauf bleibt der Wechsel bewusst manuell und seriell.
