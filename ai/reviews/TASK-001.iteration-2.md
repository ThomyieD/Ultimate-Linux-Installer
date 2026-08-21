# Review TASK-001 – Iteration 2

Verdict: CHANGES_REQUESTED

Reviewer: Codex/Sol

Geprüfter Stand: aktualisierte uncommitted Änderungen gegen `1a335da`

## Ergebnis der ersten Reviewpunkte

- **Direkter Datei-Symlink-Ausbruch:** behoben. Absolute Ziele und relative
  Traversal-Ziele der Datei werden abgelehnt; der offizielle relative
  Basename-Symlink funktioniert.
- **Hostabhängige Fingerprinttests:** behoben. Erfolgsfall und jeder einzeln
  fehlende Fingerprint werden deterministisch mit einem Offline-Fake-`gpg`
  geprüft.
- **Späte Build-Abhängigkeiten:** behoben. `curl`, `dpkg-deb` und `gpg` werden
  vor dem Chroot-Bootstrap geprüft.
- **Schwache Source-Assertion:** durch konkrete Prüfungen der weiterhin
  strikten Runtime-`gpgv`-Semantik ersetzt.

## Verbleibender Befund

### P1 – Übergeordnetes Keyring-Verzeichnis kann weiterhin aus dem Rootfs zeigen

`scripts/lib-debian-archive-keyring.sh` kanonisiert `keyring_dir` und
`payload`, prüft aber nur, ob der Payload unter dem kanonisierten Verzeichnis
liegt. Es wird nicht geprüft, ob dieses kanonisierte Verzeichnis selbst dem
erwarteten `<canon_root>/usr/share/keyrings` entspricht.

Dadurch bestand eine Konstruktion mit einem nach außen verlinkten vollständigen
`keyrings`-Verzeichnis die vollständige
`uli_debian_archive_keyring_verify_installed`-Prüfung mit Exit 0. Ein
entsprechend fehlgepacktes SquashFS hätte damit den Host statt seines eigenen
Keyrings prüfen können.

Erforderliche letzte Korrektur:

1. Nach `realpath -e` muss `canon_dir` exakt dem erwarteten kanonischen Pfad
   `"$canon_root/usr/share/keyrings"` entsprechen.
2. Erst danach dürfen Payload-Containment, Eigentümer, Modus und Fingerprints
   geprüft werden.
3. Ein deterministischer Offline-Test muss das gesamte `keyrings`-Verzeichnis
   auf ein externes Verzeichnis verlinken und für `resolve_payload` sowie
   `verify_installed` Exit ungleich 0 verlangen.
4. Der echte Paketpfad und der relative offizielle Dateisymlink müssen
   weiterhin erfolgreich sein.

## Entscheidung

`CHANGES_REQUESTED`

Die erste Nachbesserung war bis auf die übergeordnete Verzeichniskette korrekt.
