# Prompt für Codex/Sol – Kontrolle

```text
Cursor ist mit dem aktiven ULI-Task fertig. Prüfe die uncommitted Änderungen
gegen AGENTS.md, den aktiven Task, den Cursor-Handover, die Architektur und die
Quality Gates.

Ändere keinen Produktcode. Prüfe Scope, Akzeptanzkriterien, Sicherheitsgrenzen,
Fehlerbehandlung, Tests und Git-Diff. Führe angemessene nichtdestruktive Checks
selbst aus und schreibe das Ergebnis in ai/reviews/<TASK-ID>.md.

Bei Mängeln: Verdict CHANGES_REQUESTED und konkrete, kleine Anweisungen für
Cursor. Wenn alle Kriterien nachgewiesen sind: Verdict APPROVED. Committe oder
pushe nicht ohne meine ausdrückliche Aufforderung.
```
