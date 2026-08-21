# Review TASK-001 – Iteration 1

Verdict: CHANGES_REQUESTED

Reviewer: Codex/Sol

Geprüfter Stand: uncommitted Änderungen gegen `1a335da`

## Befunde

### P1 – Artifact-Prüfung kann auf einen Keyring außerhalb des ISO ausbrechen

`scripts/lib-debian-archive-keyring.sh:122-126` löst einen Symlink mit
`readlink -f` auf, prüft anschließend aber nicht, ob das Ergebnis weiterhin
unter `<root>/usr/share/keyrings/` liegt. Der ISO-Verifier übergibt zwar seinen
SquashFS-Mount als `root`, kann dadurch jedoch unbemerkt den Keyring des
Buildhosts prüfen.

Reproduktion im aktuellen Diff:

```bash
review_tmp=$(mktemp -d /var/tmp/uli-task001-review.XXXXXX)
mkdir -p "$review_tmp/root/usr/share/keyrings"
ln -s /usr/share/keyrings/debian-archive-keyring.gpg \
  "$review_tmp/root/usr/share/keyrings/debian-archive-keyring.gpg"
bash -c 'set -euo pipefail; source "$1"; \
  uli_debian_archive_keyring_verify_installed "$2"' \
  bash scripts/lib-debian-archive-keyring.sh "$review_tmp/root"
```

Beobachtet: Exit 0. Damit kann ein SquashFS ohne eigenen gültigen Payload das
Artifact-Gate bestehen, wenn der Host zufällig einen passenden Keyring besitzt.

Erforderliche Korrektur:

1. `root` und das erwartete Keyring-Verzeichnis kanonisch bestimmen.
2. Das aufgelöste Payload muss eine reguläre Datei innerhalb genau dieses
   Keyring-Verzeichnisses sein. Absolute Symlinkziele und relative
   `..`-Ausbrüche müssen fail-closed abgelehnt werden.
3. Der vom offiziellen Paket verwendete relative Symlink
   `debian-archive-keyring.gpg -> debian-archive-keyring.pgp` muss weiterhin
   funktionieren.
4. Offline-Regressionstests für absoluten Symlink-Ausbruch und relativen
   Traversal-Ausbruch ergänzen.

### P1 – Pflicht-Fingerprinttests können auf der CI vollständig übersprungen werden

`tests/unit/test_debian_archive_keyring.py:90-151` verwendet den zufälligen
Keyring des Testhosts. Fehlt er oder enthält er – wie auf Ubuntu Noble üblich –
noch keine Debian-13-Schlüssel, werden sowohl der Erfolgsfall als auch der in
Akzeptanzkriterium 2 verlangte Test jedes einzelnen fehlenden Fingerprints
übersprungen. Das Gate würde damit gerade auf einem frischen Noble-CI-Runner
keine Fingerprintlogik prüfen.

Erforderliche Korrektur:

1. Die Fingerprint-Logik mit einer deterministischen Offline-Fixture testen,
   beispielsweise über ein kontrolliertes Fake-`gpg` im temporären `PATH` oder
   einen eng begrenzten, im Test überschriebenen Ausgabe-Adapter.
2. Der vollständige Erfolgsfall und jeder der drei einzeln fehlenden
   Fingerprints müssen ohne Host-Keyring und ohne Netz immer ausgeführt werden.
3. Ein optionaler Integrationstest mit dem echten gepinnten `.deb` darf
   weiterhin separat skippen, darf aber nicht der einzige Nachweis für
   Sicherheitslogik, Pfadbindung oder Rechteprüfung sein.
4. Die in `test_sources_runtime_gpgv_rule_unchanged` stets wahre, nicht auf den
   Sourcecode bezogene Schluss-Assertion entfernen oder durch einen echten
   Source-/Verhaltenstest ersetzen.

### P2 – Neue Build-Abhängigkeiten werden erst nach dem langen Chroot-Build bemerkt

Der Helfer verwendet auf dem Buildhost `curl`, `dpkg-deb` und `gpg`. In
`scripts/build-iso-simple.sh:46` fehlen diese Werkzeuge jedoch in der frühen
`need`-Liste. Ein unvollständiger Buildhost kann deshalb erst in Schritt 4 nach
dem zeitintensiven Live-Chroot-Aufbau scheitern.

Erforderliche Korrektur: `curl`, `dpkg-deb` und `gpg` in die frühe
Build-Abhängigkeitsprüfung aufnehmen und die vorhandenen Tests entsprechend
ergänzen.

## Akzeptanzkriterien

- [x] Gepinnte offizielle URL, Version und SHA-256 stimmen.
- [x] Falsche Paketprüfsumme wird abgelehnt.
- [ ] Jeder fehlende Fingerprint wird in jedem CI-Lauf deterministisch geprüft.
- [x] Build und Verifier verwenden dieselbe zentrale Sicherheitsdefinition.
- [ ] Artifact-Verifier beweist, dass der geprüfte Payload im SquashFS liegt.
- [x] Effektiver Payload aus dem echten Paket ist `root:root`, Modus `0644` und
  enthält alle drei primären Debian-13-Fingerprints.
- [x] `verify_source_manifest` und seine strikte `gpgv`-Exitcode-Regel wurden
  nicht verändert.
- [x] Änderungen liegen im erlaubten Dateiscope; kein Commit/Push/ISO-Build.

## Ausgeführte Kontrollen

- `./scripts/check.sh`: 129 passed, 1 skipped; Exit 0.
- `pytest -q -rs tests/unit/test_debian_archive_keyring.py`: 7 passed,
  1 skipped; Exit 0.
- Exakter Workflow-ShellCheck einschließlich neuem Helfer: Exit 0.
- `bash -n` für alle geänderten Shell-Dateien: Exit 0.
- `git diff --check`: Exit 0.
- Offizielles `debian-archive-keyring_2025.1_all.deb` separat geladen:
  festgelegte SHA-256 stimmt.
- Helfer in temporäres Root installiert: Payload `root:root`, Modus `0644`,
  alle drei geforderten Fingerprints vorhanden.
- Aktuelles Debian-13.6-`trixie/InRelease` gegen diesen temporären Keyring:
  drei gültige Signaturen, `gpgv` Exit 0.
- Symlink-Ausbruch aus dem temporären Root auf den Host-Keyring: unerwartet
  Exit 0; Befund P1 bestätigt.

## Rest-Risiken

- Gate D/E (frischer ISO-Build, ISO-Verifier und VM-Live-Test) bleibt nach
  diesem Code-Review ausdrücklich ausstehend.
- Der optionale echte Paket-Integrationstest ist lokal mangels Datei im
  APT-Cache geskippt; die äquivalente Installation wurde im Review manuell in
  einem temporären Verzeichnis erfolgreich nachvollzogen.
- `scripts/check.sh` enthält den neuen Helfer wegen des ursprünglichen
  Task-Scopes noch nicht in seiner lokalen ShellCheck-Liste. Der GitHub-Workflow
  prüft ihn; eine spätere Lead-Aufgabe kann das lokale Gate konsolidieren.

## Entscheidung

`CHANGES_REQUESTED`

Der gepinnte Keyring und die reale Debian-Signaturprüfung funktionieren. Vor
Freigabe müssen jedoch der nachgewiesene Rootfs-Symlink-Ausbruch geschlossen,
die verpflichtenden Fingerprinttests hostunabhängig gemacht und die neuen
Buildwerkzeuge früh geprüft werden. Die Korrekturen bleiben vollständig im
bereits erlaubten TASK-001-Scope.
