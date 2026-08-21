# Roadmap

Die Reihenfolge folgt Risiko und Abhängigkeiten. Es wird immer nur der erste
noch nicht freigegebene Task aktiviert.

| ID | Priorität | Ziel | Voraussetzung | Status |
|---|---:|---|---|---|
| TASK-001 | P0 | Debian-13-Vertrauenskette im ISO korrigieren | – | APPROVED / Gate D PASS / Gate E FAIL → TASK-004 |
| TASK-004 | P0 | Gate-E-Blocker beheben: 40-GiB-Standardplan, Debian-Standardtask, Paket-Preflight und exportierbares Fehlerlog | TASK-001 | READY_FOR_CURSOR |
| TASK-002 | P0 | Aktuelle Ubuntu-LTS mit generischem Bootstrap-Skript wirklich installierbar machen und Versionsangaben konsolidieren | TASK-004 | PLANNED |
| TASK-003 | P0 Release | Reproduzierbarer VMware-UEFI-E2E-Test: Quelle → Installation → Reboot → GRUB → Zielsystem | TASK-001, TASK-004, TASK-002 | PLANNED |
| TASK-005 | P1 | Unterbrechungs-/Recovery-Modell spezifizieren und testen | TASK-003 | PLANNED |
| TASK-006 | P2 | Weitere Distributionen einzeln entwerfen und abnehmen | stabiler Debian-/Ubuntu-Pfad | PLANNED |
| TASK-007 | P2 | Add/Remove mit Bestandsanalyse und Erhaltungsplan entwerfen | Recovery + Storage-E2E | PLANNED |

Nicht parallel beginnen: Erst TASK-004 reviewen und freigeben. Danach folgt
TASK-002; ein neues ISO und Gate E sind erst mit beiden P0-Korrekturen sinnvoll.
