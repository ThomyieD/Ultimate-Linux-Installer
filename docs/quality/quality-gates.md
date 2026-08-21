# Quality Gates

## Gate A – Task und Scope

- Genau ein Eintrag in `ai/ACTIVE_TASK`
- bekannte Git-Baseline und keine unzugeordneten Produktänderungen
- Ziel, Nicht-Scope, erlaubte Dateien und Akzeptanzkriterien vollständig

## Gate B – Nichtdestruktive Repository-Checks

```bash
./scripts/check.sh
```

Der Befehl führt Tests, Ruff, Python-/JSON-/JavaScript-Syntax, Shell-Syntax,
ShellCheck der kanonischen Skripte und `git diff --check` aus. Er baut keine ISO
und verändert keinen Datenträger.

## Gate C – Task-spezifische Sicherheitsprüfung

Bei Storage-, Boot- oder Supply-Chain-Code müssen negative Tests vorhanden
sein: manipulierte Kennung/Prüfsumme/Signatur muss vor jeder destruktiven Aktion
abgelehnt werden. Netzwerkzugriff gehört nicht in Unit-Tests.

## Gate D – ISO-Artefakt

Erst nach Code-Review und ausdrücklicher Nutzerfreigabe:

```bash
sudo scripts/build-iso.sh
sudo scripts/verify-iso-uefi.sh artifacts/ultimate-linux-installer-0.3.0-amd64.iso
```

Prüfsumme, Runtime-Dateirechte, Dienste, Schlüsselmaterial und positiver
UEFI-Live-Bootmarker müssen geprüft werden.

## Gate E – Wegwerf-VM-End-to-End

In VMware/QEMU mit ausschließlich entbehrlicher Testdisk:

1. Live-ISO in UEFI booten, Secure Boot aus.
2. Netzwerk, DNS und aktuelle Quellen prüfen.
3. Installation vollständig durchführen.
4. ISO entfernen und von der Testdisk booten.
5. Jeden erwarteten GRUB-Eintrag und mindestens Login/SSH-Marker prüfen.

Ein nur gestarteter Wizard oder ein erfolgreicher Dry-Run erfüllt dieses Gate
nicht.

## Gate F – Release

Ein Release benötigt APPROVED-Reviews, Gate B bis E, ISO plus SHA256SUMS und
eine dokumentierte Testmatrix. Kein Release-Upload ohne ausdrückliche Freigabe
des Nutzers.
