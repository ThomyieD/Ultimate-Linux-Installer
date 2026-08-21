# Architekturentscheidungen

Diese Entscheidungen dürfen Implementierungsagenten nicht eigenständig ändern.

## ADR-001: Direkte Paket-Provisionierung

Debian und Ubuntu werden aus offiziellen, signierten APT-Repositories direkt in
die vorbereiteten Root-Dateisysteme provisioniert. ULI startet keine fremden
grafischen ISO-Installer innerhalb des Live-Systems.

## ADR-002: Aktuelle Ubuntu-LTS-Version zur Laufzeit

Der Wizard ermittelt online die aktuelle unterstützte Ubuntu-LTS-Version und
bindet Version, Codename und Quelle anschließend unveränderlich an den Plan.
Das signierte Ubuntu-`InRelease` bleibt die Autorisierung der Pakete. Neue
Point-Releases und reguläre neue LTS-Versionen sollen keine neue ULI-ISO
erfordern, solange vorhandene Vertrauensanker und Provisionierungslogik sie
unterstützen.

## ADR-003: Vertrauensanker sind Teil der ULI-Version

Archivschlüssel dürfen nicht allein aufgrund einer zur Installationszeit über
HTTPS geladenen Datei vertraut werden. Schlüsselmaterial wird beim ISO-Build
aus einem versionierten, kryptografisch festgelegten Artefakt übernommen und
gegen erwartete Fingerprints geprüft. Ein echter Schlüsselwechsel kann daher
ein neues ULI-Release erfordern; das ist eine notwendige Sicherheitsgrenze und
kein Versionsresolver-Fehler.

## ADR-004: Destruktive Schritte bleiben fail-closed

Quellen-, Plattform-, GRUB- und Zielplattenprüfungen laufen vor dem ersten
Wipe. Unbekannte Identitäten, fehlende Werkzeuge oder unvollständige
Vertrauensketten führen zum Abbruch. Eine Bequemlichkeitskorrektur darf diese
Grenze nicht in eine Warnung verwandeln.

## ADR-005: Lead-/Worker-Trennung

Codex/Sol plant und reviewt; Cursor implementiert. Ein Task darf keine
zusätzliche Architekturentscheidung an den Implementierungsagenten delegieren.
Ein Agent schreibt zu einem Zeitpunkt, Änderungen bleiben bis zum Review
uncommitted.
