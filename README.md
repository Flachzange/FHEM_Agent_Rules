# FHEM Agent Rules

Die maßgebliche generische Regeldatei für die angeschlossenen FHEM-Projekte ist
[AGENTS.md](AGENTS.md). Dort wird sie gepflegt; Modul-Repositories enthalten
unveränderte, versionierte Kopien und jeweils ihren eigenen Projektzusatz.
Für Arbeiten an dieser zentralen Quelle zusätzlich [AGENTS-RULES.md](AGENTS-RULES.md) lesen.

## Aufbau

- `AGENTS.md`: gemeinsame Regeln einschließlich des Rückwegs für neue Erkenntnisse.
- `AGENTS-RULES.md`: Pflege- und Tooling-Anweisungen für dieses Repository.
- `consumers.json`: ausdrückliche Liste angeschlossener Projekte und ihrer Zusätze.
- `scripts/agent_rules.py`: Prüfung und Verteilung, nur Python-Standardbibliothek und Git.
- `.github/workflows/check-consumer.yml`: wiederverwendbare, lesende Projektprüfung.
- `.github/workflows/distribute.yml`: Verteilung über Draft-PRs, anfangs deaktiviert.

Eine Projektdatei `.github/agent-rules.json` enthält `schema: 1`, unter `source`
das feste Repository `Flachzange/FHEM_Agent_Rules`, den Pfad `AGENTS.md` und einen
vollständigen Commit-SHA sowie unter `supplement` den registrierten Projektzusatz.
Die eigentliche `AGENTS.md` bleibt bytegleich; Herkunftsinformationen stehen separat.

## Rückweg für neue Erkenntnisse

1. Projektspezifische Vorgaben im Projektzusatz bearbeiten.
2. Übertragbare Erkenntnisse als zentralen Draft-PR vorschlagen: Ursprung verlinken,
   Belege, Geltungsbereich und Grenzen beschreiben sowie vorhandene Regeln auf
   Dopplungen und Widersprüche prüfen. Bestehende Bearbeitungsberechtigungen beachten.
3. Maintainer prüft die fachliche Eignung. Keine automatische semantische Freigabe.
4. Nach zentralem Merge verteilt die Automatik die neue Fassung über Projekt-PRs.

Lokale generische Änderungen lassen den Projektcheck fehlschlagen. Der Check
überschreibt nichts. Ein abweichender Text wird als Patch im Workflow-Artefakt
`agent-rules-upstream-proposal` für 14 Tage bereitgestellt; der Projektbranch bleibt
ebenfalls die ursprüngliche Quelle. Der Patch wird nicht automatisch zentral
angewendet. Er dient als Grundlage des belegten zentralen Vorschlags.

## Prüfung und reproduzierbare Übernahme

Der Projektcheck prüft die Herkunft, den vollständigen SHA, dessen Erreichbarkeit
von zentraler `main`, den vorhandenen registrierten Zusatz und die Bytegleichheit.
Unbekannte oder nicht gemergte Revisionen und lokale Sonderfassungen werden abgewiesen.
Er prüft keine inhaltliche Widerspruchsfreiheit beliebiger Projektzusätze.

Der Workflow selbst und sein `tooling-ref` werden auf denselben geprüften zentralen
Commit gepinnt. Dieser Tooling-Pin bleibt bei gewöhnlichen Regelupdates unverändert;
die Herkunftsdatei kann spätere akzeptierte Regelrevisionen übernehmen. Neuer Checker-Code
wird in einem gesonderten Projekt-PR übernommen, nicht bei jeder Textänderung mit ausgeführt.
Bei neuen Verbrauchern muss deren Registrierung auch in der übernommenen Tooling-Version
vorliegen. Die beiden Pilotprojekte sind bereits registriert.

Den tatsächlich angezeigten GitHub-Statuscheck des wiederverwendbaren Jobs
`agent-rules` in beiden Projekten als erforderlich einrichten. Die genaue Anzeige
kann den aufrufenden Jobnamen enthalten. Das ist eine Repository-Einstellung:
eine Workflow-Datei allein verhindert noch keinen Merge. Direkte Umgehungen der
Branch-Regel müssen ebenfalls passend eingeschränkt werden.

Feste Revisionen garantieren Konsistenz und Nachvollziehbarkeit, nicht sofortige
Aktualität: bis zum Merge eines Synchronisierungs-PRs gilt die ausgewiesene alte Fassung.
Bei einem Fehler beim Abruf schlägt der Check fehl; er behauptet dann keine Übereinstimmung.

## Initiale Einrichtung und Reihenfolge

1. Zentrale Implementierung prüfen und zuerst mergen.
2. In den beiden Anbindungs-PRs Workflow-Referenz, `tooling-ref` und Herkunfts-SHA
   auf den endgültigen zentralen `main`-Commit setzen. Nach Squash-/Rebase-Merge ist
   der vorgeschlagene Branch-SHA normalerweise nicht Bestandteil der `main`-Historie.
   Solange die Quelle nicht akzeptiert ist, sind fehlschlagende Projektchecks beabsichtigt.
3. Beide Projekt-PRs prüfen/mergen und den Statuscheck als erforderlich konfigurieren.
4. GitHub App und zentrale Variablen/Secret einrichten, anschließend Verteilung aktivieren.
5. Ersten Live-Lauf prüfen. Bestehende Selbsttests ersetzen diesen Berechtigungs- und PR-Test nicht.

## GitHub App und Verteilung

Eine eigene App auf die drei beteiligten Repositories begrenzen. Für normale
Synchronisierung benötigt sie `Contents: read and write`, `Pull requests: read and write`
und die von GitHub bereitgestellten Metadaten-Leserechte. Keine Administration oder
Workflow-Schreibrechte erforderlich: der Verteiler verändert keine Workflow-Dateien.

Nur im zentralen Repository konfigurieren:

| Typ | Name | Wert |
| --- | --- | --- |
| Variable | `AGENT_RULES_APP_ID` | ID der eigenen GitHub App |
| Secret | `AGENT_RULES_APP_PRIVATE_KEY` | Vollständiger privater App-Schlüssel |
| Variable | `AGENT_RULES_SYNC_ENABLED` | Erst nach abgeschlossener Einrichtung `true` |

Zugangsdaten nicht in Chat, Dateien oder PR-Beschreibungen kopieren. Ohne aktivierende
Variable wird der Verteilungsjob übersprungen. Das ist ausdrücklich kein erfolgreicher Live-Test.

Der zentrale Workflow startet nach passenden `main`-Änderungen, täglich um 06:23 UTC
als Nachholprüfung und manuell über GitHub Actions. Er arbeitet immer auf zentraler
`main`. Er prüft jedes Projekt zunächst lesend und wendet nur einen gültigen Plan an.
`consumers.json` und die Repository-Liste der Token-Erstellung im Workflow müssen
bei der Aufnahme weiterer Projekte gemeinsam aktualisiert werden.

Pro Projekt wird `codex/sync-agent-rules` verwendet. Der Verteiler erstellt höchstens
einen offenen Draft-PR, aktualisiert ihn bei weiteren Revisionen und schreibt bei
bereits passendem Inhalt keinen neuen Commit. Er schreibt nur `AGENTS.md` und
`.github/agent-rules.json`, nie direkt auf Projekt-`main`, und mergt/force-pusht nicht.
Ältere bereits gültige Manifestrevisionen bleiben erhalten, wenn sich nur zentrale
Werkzeuge oder Dokumentation und nicht die generischen Regeln geändert haben.

Abweichende Default-Branch-Dateien oder handbearbeitete/unabhängig erweiterte
Synchronisierungsbranches werden nicht überschrieben. Der Lauf meldet den Konflikt.
Das betroffene Projekt muss erst geprüft werden; andere registrierte Projekte können
weiterlaufen. Ein paralleler Branchfortschritt kann die nicht erzwungene Aktualisierung
ablehnen. In diesem Fall nach Prüfung erneut ausführen.

## Lokale Prüfungen

Aus dem zentralen Checkout:

```bash
bash scripts/ci.sh
```

Für einen daneben ausgecheckten WIFFI-Pilot gilt nach Abruf der zentralen `main`-Historie:

```bash
git fetch origin main:refs/remotes/origin/main
python3 scripts/agent_rules.py check --central-root . --project-root ../FHEM_Modul_Wiffi --repository Flachzange/FHEM_Modul_Wiffi --diff-output agent-rules-upstream.patch
```

Mit bereits sicher gesetztem `GH_TOKEN` kann zunächst ohne Schreibvorgang geplant werden:

```bash
python3 scripts/agent_rules.py sync --central-root .
```

Die Schreibvariante ist im vertrauenswürdigen zentralen Workflow hinterlegt.
Unit-Tests verwenden echte temporäre Git-Historien und einen zustandsbehafteten
GitHub-API-Testdouble. Sie belegen Auswahl, Ablehnungen, Dateiumfang und Idempotenz,
aber keine realen App-Rechte, Branch-Regeln oder einen ausgeführten Live-Verteilungszyklus.
