<p align="center">
  <img src="images/HYDRA_UMC_BANNER.svg" alt="HYDRA-UMC-DEV-SERVER Banner" width="100%">
</p>

# 🖥️ HYDRA-UMC-DEV-SERVER

<p align="center"><a href="README.md">🇺🇸 English</a> | <a href="README_spa.md">🇪🇸 Español</a> | <a href="README_fra.md">🇫🇷 Français</a> | <a href="README_ita.md">🇮🇹 Italiano</a> | 🇩🇪 <b>Deutsch</b> | <a href="README_zho.md">🇨🇳 简体中文</a> | <a href="README_jpn.md">🇯🇵 日本語</a> | <a href="README_por.md">🇵🇹 Português</a></p>

### 🏗️ Reproduzierbarer Entwicklungsserver für das Gesamte Ökosystem

<p align="center">
  <img src="https://img.shields.io/badge/Lizenz-GPL%203.0--or--later-blue.svg" alt="GPL 3.0 or later">
  <img src="https://img.shields.io/badge/Sprache-Python%203.11%2B-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/Kern-nur%20stdlib-brightgreen.svg" alt="Nur-stdlib-Kern">
  <img src="https://img.shields.io/badge/Lieferung-DS01--DS10%20komplett%20(funktionsfähig)-brightgreen.svg" alt="DS01-DS10 komplett, funktionsfähig">
</p>

> **Status: v0.1.9, funktionsfähig - alle zehn von zehn geliefert (gebaut und durch Tests abgedeckt; noch nicht auf realer Hardware oder realen Diensten verifiziert).** Ein reales, getestetes Konfigurationsschema
> (`config validate`), dessen Standardrichtlinie **keiner Aufgabe eine
> Deployment-Berechtigung erteilt**, sowie eine schreibgeschützte
> Manifest-Erkennung (`inventory scan`), die die eigenen
> `hydra-umc.project.json`-Dateien dieses Ökosystems findet -
> einschließlich der eigenen dieses Repositories. DS02 fügt ein
> validiertes Remote-Stationsprofil (`station validate`) hinzu, eine
> **schreibgeschützte** Host-Vorabprüfung, die nur meldet, ob ein Host
> bereit ist (`station preflight`, ändert nichts), und einen
> **Trockenlauf**-Provisionierungsplan (`station plan`, führt niemals einen Schritt aus), und eine **konservative Migration**, die nichts kopiert. DS04 fügt den **begrenzten Runner** hinzu (`task validate` / `task run`): er führt **einen** Befehl aus einer Allow-Liste in einem **pro-Task isolierten Workspace** aus (ein `..`, ein absoluter Pfad oder ein Symlink aus dem Workspace heraus wird abgelehnt; zwei Tasks teilen sich nie einen), mit einer **bereinigten Umgebung** (kein geerbtes `*_TOKEN` / `*_KEY` / `*_SECRET`), unter einem begrenzten Timeout, das **die ganze Prozessgruppe killt**. **DS05 fügt eine dauerhafte SQLite-Warteschlange + ein Ausführungsjournal** hinzu (`queue …`), die einen Neustart überstehen: ein doppeltes `enqueue` ist nie ein zweiter Job; der Lease eines abgestürzten Workers läuft ab und `reconcile` gibt die Aufgabe an `queued` zurück; ein Ergebnis von einem Worker, der den Lease nicht mehr hält, wird **abgelehnt, nicht als erledigt markiert**; eine seit dem Enqueue geänderte Basis **blockiert die Promotion selbst bei Exit-Code 0**. Es stellt weiterhin nichts bereit. DS03 fügt **konservative Migration** hinzu (`migrate inventory` / `migrate plan`): sie hasht und klassifiziert jede Datei eines Quell-Checkouts und plant jede Klasse - sauber, lokal geändert, untracked, privat - in ihr **eigenes getrenntes Ziel**, und weigert sich, wenn eine private Datei irgendwo Teilbarem landen würde. Sie kopiert nichts und rührt die Quelle nie an. Es gibt noch keinen Workspace, keinen
> Aufgaben-Runner, keine dauerhafte Warteschlange und keine
> KI-Provider-Integration - das sind DS04, DS05 und DS06, spätere
> Lieferungen. Siehe
> [docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md) für die exakte
> Kommandooberfläche, die heute existiert.

---

**Ehrlichkeitscheck - was heute wirklich läuft:** alle zweiundzwanzig unten genannten Module (`config.py`, `inventory.py`, `remote_station.py`, `preflight.py`, `provision.py`, `migration.py`, `workspace.py`, `recipe.py`, `runner.py`, `durable_queue.py`, `ai_provider.py`, `incident_transport.py`, `repair_cycle.py`, `operations.py`, `delivery.py`, `cli.py`, `api.py`, `plugins.py`, `sandbox.py`, `taskflow.py`, `worker.py`, `signing.py`) sind echter Code, keine Stubs, und werden von einer echten Testsuite abgedeckt (418 bestandene Tests in `tests/test_*.py`). Was dieser echte Code tatsächlich getan hat, konkret: JSON-Dokumente validiert, Migrationen auf der Festplatte geplant, einen echten, begrenzten Subprozess in einem echten isolierten Arbeitsbereich mit einer echten bereinigten Umgebung ausgeführt, eine echte SQLite-Warteschlange/-Journal über Neustarts hinweg persistiert und einen echten HMAC-signierten Incident-Roundtrip durchgeführt - alles gegen dieses lokale Checkout oder einen injizierbaren Test-Seam, niemals gegen die echte Ziel-Hardware Raspberry Pi 5/CM5, für die dieses Projekt gebaut wird. `provider suggest` ruft ausschließlich den deterministischen `FakeProvider` auf; die Anbindung eines echten KI-Anbieters bleibt eine explizite, noch nicht getroffene Nutzerentscheidung. `station preflight`/`station plan` beschreiben einen entfernten Host über einen injizierbaren Inspector und liefen noch nie gegen eine echte entfernte Maschine. Nichts in diesem Repository hat einen Host provisioniert oder ein Deployment ausgeführt, und die Worker-Schleife (`queue work`) lief bisher nur gegen Attrappen des Starters und von git, nie auf einem echten Host - das fest codierte `overall_maturity: "functional"` von `deliver evaluate` sagt das klar aus dem Code selbst heraus. Siehe `CHANGELOG.md` für das, was genau geliefert wurde, Delivery für Delivery.

---

> **Stand von Sicherheit (Safety) und Security:** Dieses Ökosystem ist kein zertifiziertes Sicherheitssystem. Es gibt noch keinen Hardware-E-STOP-Pfad, keine von der Firmware durchgesetzten Grenzen oder Verriegelungen und keinen verifizierten Bewegungsbefehl; Firmware-Images werden mit CRC32 und einem HMAC-SHA256 mit gemeinsamem Schlüssel geprüft, nicht mit einer asymmetrischen Signatur; TLS und gegenseitiges TLS sind optional und standardmäßig aus; noch keine eigene Platine wurde bestückt oder getestet. Lesen Sie die [Sicherheitsbasis](https://github.com/JuanenRac/HYDRA-UMC-DOCS/blob/main/docs/SECURITY_BASELINE.md) und das [Bedrohungsmodell](https://github.com/JuanenRac/HYDRA-UMC-DOCS/blob/main/docs/THREAT_MODEL.md), bevor Sie sich für die Sicherheit einer Person auf eine Aussage hier verlassen.

## 📋 Auf einen Blick

| | |
|---|---|
| Version | `0.1.9` |
| Reifegrad | Funktionsfähig |
| Tests | 347 |
| Technik | Python 3.11+ / JSON Schema / systemd (host role, Linux only) / SQLite (durable task/state journal, from DS05 onward) |
| Ziel | Ein Entwicklungsserver |
| Auf echter Hardware | Noch nicht: für diese Version ist kein Lauf auf echter Hardware vermerkt |

## 🚦 Projektstatus

Jede Zeile ist ein Teil dieses Repositorys, und die Ampel sagt, wie weit er heute ist. Sie beruht auf dem, was das Repository zeigen kann (Tests, Builds, Läufe), nicht auf dem, was geplant ist.

🟢 Fertig und überprüft · 🟡 Funktioniert, mit bekannten Grenzen · 🟠 Teilweise fertig oder noch nicht überprüft · 🔴 Nicht gemacht oder funktioniert nicht

| Bereich | Stand | Was das hier bedeutet |
|---|---|---|
| Software | 🟡 | Funktioniert für seinen Hauptzweck; die Ehrlichkeitsprüfung oben nennt, was noch fehlt |
| Tests | 🟢 | 347 automatische Tests, bei jeder Änderung ausgeführt |
| Echte Hardware | 🔴 | Noch nicht: für diese Version ist kein Lauf auf echter Hardware vermerkt |
| Dokumentation | 🟢 | README in acht Sprachen, bei jeder Änderung gegen das Manifest geprüft |

## 1. 🛠️ TECHNISCHER ÜBERBLICK

HYDRA-UMC-DEV-SERVER ist Entwicklungsinfrastruktur für das
HYDRA-UMC/URTC-Ökosystem: ein reproduzierbarer Host (Ziel: ein
Raspberry Pi 5 oder Compute Module 5, 8GB, von NVMe gestartet), der den
eigenen Quellcode dieses Ökosystems hostet und begrenzte,
richtliniengesteuerte Programmier-/Build-/Test-Aufgaben ausführt - für
Menschen ebenso wie für KI-Assistenten. Es ist **keine** neue KI, die
trainiert werden muss, **kein** Ersatz-Betriebssystem, und es
entscheidet niemals selbst, dass eine Maschine sicher zu verändern ist.

DS01 brachte zwei reale, unabhängig nützliche Teile:

1. **Konfigurationsschema** (`config validate`) - drei JSON-Dokumente
   (`HostProfile`, `ToolchainPolicy`, `TaskPolicy`), jedes mit echter
   Validierung und einem echten Negativtest für jede abgelehnte Form.
   Die vom ersten Tag an wichtigste Invariante:
   `TaskPolicy.allow_deploy` ist standardmäßig `False`, und nur ein
   Dokument, das den wörtlichen JSON-Boolean `true` setzt, kann eine
   Richtlinie erzeugen, in der das erlaubt ist.
2. **Manifest-Erkennung** (`inventory scan`) - dasselbe reale, getestete
   Muster, das die Edge-Rolle von HYDRA-UMC-OPS-AGENT bereits verwendet,
   um ein `hydra-umc.project.json` zu finden und zu validieren - hier
   wiederverwendet statt neu geschrieben.

DS02 fügt drei weitere hinzu, alle unter dem Unterbefehl `station` und
alle weiterhin "validieren und beschreiben, niemals handeln":

3. **Remote-Stationsprofil** (`station validate`) - ein JSON-Dokument
   (`RemoteIdentity` + `RemoteAccess` + benötigte Toolchains) mit
   derselben fehlersammelnden Validierung. Seine Invariante vom ersten
   Tag: der Remote-Editing-Endpunkt bindet an Loopback/privat, und eine
   routbare Adresse wird abgelehnt, sofern das Dokument nicht den
   wörtlichen Boolean `allow_public_bind: true` setzt; die Identität ist
   ein dediziertes Systemkonto, niemals `root` oder ein Login-Benutzer.
4. **Host-Vorabprüfung** (`station preflight`) - liest ein Profil und
   meldet über eine injizierbare Inspektor-Schnittstelle, ob *dieser*
   Host wirklich bereit ist, diese Station zu werden (Python-Version,
   freier Speicher, Workspace beschreibbar, Werkzeuge im `PATH`, Port
   frei, Identität ist ein echtes Systemkonto). Ändert den Host nie.
5. **Trockenlauf-Provisionierungsplan** (`station plan`) - stellt dar,
   was ein echter Installer *tun würde* (das argv jedes Schritts als
   Daten erfasst) plus den vollständigen systemd-Unit-Text, und
   verweigert einen Plan über einer fehlgeschlagenen Vorabprüfung. Es
   wird nichts ausgeführt.

DS03 fügt konservative Migration hinzu, dieselbe Regel "lesen und
beschreiben, niemals handeln" - sie kopiert nichts und rührt die
Quelle nie an:

6. **Migrations-Inventar + Plan** (`migrate inventory` / `migrate
   plan`) - läuft durch einen Quell-Checkout (nur die Dateien, die git
   als Teil des Projekts ansieht - ein lokales `.venv` oder Build-
   Output ist git-ignoriert und wird nie gesehen), bildet den SHA-256
   jeder Datei und klassifiziert jede: `tracked-clean`,
   `tracked-modified`, `untracked`, `private` (eine erweiterbare
   `PrivacyPolicy`: der Ordner für private Dokumente, `.env*`, `*.pem`, `id_ed25519*`, ...).
   Commits, die gemacht, aber nie gepusht wurden, werden separat
   erfasst. `migrate plan` bildet jede Klasse auf ihr **eigenes** Ziel
   unter vier beweisbar getrennten Wurzeln ab
   (`MigrationDestinations.from_dict` lehnt gleiche oder verschachtelte
   Wurzeln ab), bündelt die ungepushten Commits, gibt ein vollständiges
   Hash-Manifest aus und druckt `REFUSED`, wenn eine private Datei
   unter einer teilbaren Wurzel landen würde.

DS04 ist die erste Lieferung, die einen Subprozess ausführt - und sie
bleibt streng eingegrenzt:

7. **Task-Recipe + Workspace-Runner** (`task validate` / `task run`) -
   ein `TaskRecipe` legt eine `revision` fest (ein Branch-Name wird
   abgelehnt) und einen `command` aus einer Allow-Liste (`argv[0]` muss
   in `allowed_commands` der Richtlinie stehen, sonst ist der Lauf
   `rejected` und nichts wird gestartet). `task run` legt
   `<base>/<task_id>/` an - und lehnt einen bereits vorhandenen ab, also
   **teilen sich zwei Tasks nie einen Workspace** - führt den Befehl
   dort mit einer **bereinigten Umgebung** aus (nur `PATH` / `HOME` /
   `LANG` / `TZ`; nie ein geerbtes `GITHUB_TOKEN`,
   `AWS_SECRET_ACCESS_KEY`, `ANTHROPIC_API_KEY`, `SSH_AUTH_SOCK`),
   begrenzt durch `timeout_seconds`, und bei Timeout oder Abbruch
   **killt es die ganze Prozessgruppe** - bewiesen durch einen echten
   Test, der ein Enkelkind startet und bestätigt, dass beide sterben.
   Ein `..`, ein absoluter Pfad oder ein Symlink aus dem Workspace
   heraus in `input_paths` wird abgelehnt. Es stellt nichts bereit. Die Ausgabe des Kindprozesses wird während des Laufs fortlaufend gelesen und von jedem Strom werden nur die letzten 8 KiB behalten, sodass ein sehr ausführlicher Build oder Testlauf weder an einer vollen Pipe blockieren noch den Speicher des Hosts anwachsen lassen kann.

DS05 fügt Dauerhaftigkeit hinzu - eine Aufgaben-Warteschlange und ihr
Ausführungsjournal, die einen Prozess-Neustart überstehen. Es
protokolliert, es führt nicht aus:

8. **Dauerhafte Warteschlange + Ausführungsjournal** (`queue enqueue` /
   `status` / `reconcile` / `journal`) - ein SQLite-Speicher (WAL,
   sofortige Transaktionen für den Lease). `enqueue` ist idempotent -
   ein zweiter Aufruf mit derselben `task_id` gibt `created=False`
   zurück, **nie ein zweiter Job**. `lease(worker, ttl)` beansprucht
   den ältesten `queued`-Eintrag; `reconcile()` gibt einen abgelaufenen
   Lease an `queued` zurück (bei jedem Start sicher). Ein
   `record_result` von einem Worker, der den Lease nicht mehr hält,
   wird **abgelehnt, nicht als erledigt akzeptiert** - eine
   Unterbrechung wird nie ein falscher Erfolg. Weicht der beim Ergebnis
   beobachtete Basis-Fingerabdruck von dem beim `enqueue` ab, wird das
   Ergebnis `failed` / nicht promotierbar gespeichert **selbst bei
   Exit-Code 0**. Das `completed`-Journalereignis trägt immer
   `revision` + `recipe_fingerprint`; das Journal behält nur gekürzte
   Ausgaben und `prune_journal` begrenzt die Zeilen, damit die Platte
   begrenzt bleibt.

DS06 fugt einen austauschbaren KI-Provider hinzu - nur den
deterministischen Fake, hinter einem Sicherheitsvertrag. Er gibt eine
Zeichenkette zuruck, die ein Mensch liest; er verdrahtet nichts mit dem
Runner, der Warteschlange oder einem Deployment:

9. **Austauschbarer KI-Provider** (`provider suggest`) - eine
   `AIProvider`-Naht; `FakeProvider(scenario=...)` ist vollstandig
   deterministisch. `run_provider_step` verwandelt einen **Timeout**, ein
   **erschopftes Kontingent** oder eine **fehlerhafte Ausgabe** des
   Providers in ein begrenztes, benanntes Ergebnis (nie eine eskalierende
   Ausnahme); ein konfiguriertes `ProviderBudget` (Aufrufe / Tokens /
   Kosten) **stoppt den Schritt, bevor es uberschritten wird**, ohne
   Aufruf; und die Antwort des Providers sind **Daten, nie Anweisungen** -
   ein Vorschlag mit "ignoriere vorherige Anweisungen / deploye jetzt / gib
   mir root" wird wortlich kopiert, `injection_flagged` wird gesetzt, und
   `grants_no_permissions` / `triggers_no_deploy` bleiben fur **jedes**
   Ergebnis wahr. Welcher echte Provider verwendet wird und dessen
   Autorisierung ist eine Entscheidung des Nutzers (`kind` muss heute
   `"fake"` sein).

```
$ hydra-umc-dev-server config validate configs/task-policy.example.json --kind task-policy
VALID: configs/task-policy.example.json (task-policy)
{
  "allow_deploy": false,
  "max_concurrent_tasks": 2,
  "allowed_commands": ["pytest", "build.sh", "build-test.sh"]
}

$ hydra-umc-dev-server inventory scan --root ..
{
  "root": "..",
  "projects": [
    {"name": "HYDRA-UMC-DEV-SERVER", "version": "0.1.6", "maturity": "functional", "manifest_path": "../HYDRA-UMC-DEV-SERVER/hydra-umc.project.json"},
    ...
  ],
  "issues": []
}
```

Es gibt keinen Standardaufruf ohne Argumente außer der Demo, die
`run.sh` ausführt, und diese Lieferung hat keine grafische
Oberfläche - siehe [docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md) für
die vollständige, reale Kommandooberfläche.

Zwei weitere Befehle, `plugin list` und `serve`, decken den Plugin-Lebenszyklus und eine authentifizierte lokale HTTP-API ab (nur Loopback, Bearer-Token). Ein Plugin bleibt inaktiv, bis es mit dem freigegebenen SHA-256 seiner Dateien aktiviert wird, und kann nur benannte Prüfungen, Berichte und Generatoren hinzufügen (in `plugin.json` mit `provides` deklariert, mit `plugin run` oder über die API ausgeführt, jeweils durch Zeitlimit und Größengrenze begrenzt); die API führt keine Aufgabe aus und deployt nichts. Siehe [docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md) und [docs/PLUGINS.md](docs/PLUGINS.md). Außerdem packt der Aufgabenläufer den Befehl in eine bubblewrap- oder systemd-run-Sandbox, wenn der Rechner eine hat (kein Home, kein Netz, sofern die Richtlinie es nicht öffnet, nur der Arbeitsbereich beschreibbar), begrenzt die Argumente jedes Befehls, holt die festgelegte Revision, begrenzt die gleichzeitigen Aufgaben und löscht den Arbeitsbereich danach; Plugins laufen standardmäßig in einem eigenen Prozess. Nichts davon lief bisher auf einem echten Rechner.

## 2. 🧱 ARCHITEKTUR UND DESIGN-ENTSCHEIDUNGEN

- **Freigaben sind asymmetrisch und an den Patch gebunden.** Ein Reparaturzyklus prüft Kandidaten und Freigaben nur mit öffentlichen Ed25519-Schlüsseln (ein gemeinsames HMAC-Geheimnis muss auch auf der prüfenden Seite liegen, wer prüfen könnte, könnte also auch fälschen; `allow_symmetric_keys` behält es als Opt-in). Eine Freigabe nennt den Patch, den sie freigibt (`approved_patch_ref`), und trägt ein Ablaufdatum (`expires_at`, UTC); beides ist signiert, und ein Zyklus lehnt eine Freigabe für einen anderen Patch, ohne diese Angaben oder abgelaufen ab.
- **Die Sandbox wurde auf einem echten Kernel ausgeführt.** Die `systemd-run`-Sandbox wurde auf einem Linux-Host mit systemd ausgeführt (tests/test_sandbox_real_host.py): Eine Aufgabe schreibt in ihren Arbeitsbereich und sonst nirgends, kann das Home des Dienstbenutzers nicht lesen, hat kein Netzwerk und wird vom Kernel beendet, wenn sie das Fünffache ihres `MemoryMax` braucht. Das Ausführen deckte zwei Fehler auf, die die Befehlszeilen-Tests nicht sehen konnten: Ein Arbeitsbereich unter `/tmp` oder `/var/tmp` ließ die Einheit scheitern (Status 226), bis er per `BindPaths` eingebunden wird, und einer unter `/home`, `/root` oder `/run/user` ist gar nicht erreichbar und wird nun mit Begründung abgelehnt, bevor etwas läuft. Auf einem Host ohne brauchbare Sandbox werden die Tests mit Begründung übersprungen; bubblewrap wurde nicht ausgeführt. Ist das optionale Paket `cryptography` installiert, laufen Ableitung des öffentlichen Schlüssels und Signieren darüber (zeitkonstant) statt über den reinen RFC-8032-Code; `signing_backend()` sagt, welcher.
- **Keine Aufgabe hat standardmäßig eine Deployment-Berechtigung.** Das
  ist das wörtliche Abnahmekriterium von DS01, erzwungen durch den
  eigenen Standardwert der `TaskPolicy`-Dataclass - nicht nur in Prosa
  behauptet - und durch einen eigenen Test für jede Art abgedeckt, wie
  ein Dokument versuchen könnte, es einzuschleusen (ein fehlendes,
  falsch geschriebenes oder nicht-boolesches Feld).
- **Ein Collector meldet ein reales, ehrliches Scheitern - er rät
  niemals.** Dass `scan_project_manifests()` für ein vorhandenes, aber
  defektes Manifest ein `ManifestScanIssue` zurückgibt, statt es
  stillschweigend zu verwerfen, ist das in diesem Ökosystem bereits
  etablierte Muster (siehe das eigene `inventory.py` von
  HYDRA-UMC-OPS-AGENT) - hier wiederverwendet, nicht neu erfunden.
- **Zustandseigentum und Beziehungen zwischen Projekten sind nicht von
  diesem Repository neu zu entscheiden.**
  [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) und
  [docs/OPS_INTEGRATION.md](docs/OPS_INTEGRATION.md) dokumentieren die
  eigene Zustandseigentümer-Tabelle dieses Repositorys und dessen
  Gruppierung der 17 Projektbeziehungen in
  notwendig/optional/nur-Entwicklung.
- **Nur stdlib für diese Lieferung.** `config validate` und `inventory
  scan` benötigen keine externe Abhängigkeit - eine spätere Lieferung
  fügt eine erst hinzu, wenn deren eigener Code sie wirklich braucht
  (ein Treiber für die dauerhafte Warteschlange bei DS05, ein
  KI-Provider-SDK bei DS06), nie spekulativ.
- **Hier wird nichts ausgerollt.** Der Läufer führt einen einzigen erlaubten Befehl in einem Arbeitsbereich je Aufgabe aus (in einer Sandbox, wenn der Rechner eine hat),
  die Warteschlange ist eine lokale SQLite-Datei, und die einzigen Netzwerkaufrufe sind der optionale git-Abruf einer festgelegten Revision und die lokale API auf Loopback.
  Keine Aufgabe darf ausrollen, und auf dem Ziel-Raspberry-Pi 5/CM5 lief noch nichts.

## 📂 VERZEICHNISSTRUKTUR

```
HYDRA-UMC-DEV-SERVER/
├── src/hydra_umc_dev_server/
│   ├── __init__.py        # Paketversion
│   ├── config.py          # Schema und Validierung von HostProfile/ToolchainPolicy/TaskPolicy (DS01)
│   ├── inventory.py       # Reale, schreibgeschützte Erkennung von hydra-umc.project.json (DS01)
│   ├── remote_station.py  # RemoteStationProfile: Identität + Remote-Zugriff + Werkzeuge (DS02)
│   ├── preflight.py       # Schreibgeschützte Host-Prüfung über einen injizierbaren Inspektor (DS02)
│   ├── provision.py       # Trockenlauf-Provisionierungsplan + Unit-Text, nie ausgeführt (DS02)
│   ├── migration.py       # Konservatives Migrations-Inventar + Plan zu getrennten Zielen, kopiert nichts (DS03)
│   ├── workspace.py       # Pro-Task isolierter Workspace; lehnt ../, absolut, Symlink aus dem Workspace ab (DS04)
│   ├── recipe.py          # TaskRecipe: fixierte Revision + Befehl aus der Allow-Liste (DS04)
│   ├── runner.py          # Begrenzter Runner: bereinigte Umgebung, Timeout, killt die ganze Prozessgruppe (DS04)
│   ├── durable_queue.py   # Dauerhafte SQLite-Warteschlange + Leases + Append-only-Ausführungsjournal, übersteht einen Neustart (DS05)
│   ├── ai_provider.py     # Austauschbarer KI-Provider-Seam + Sicherheitsvertrag; nur deterministischer Fake (DS06)
│   ├── incident_transport.py  # HMAC-signierte Incident-Nachrichten + verify + vollständige Round-Trip-Session (DS07)
│   ├── repair_cycle.py    # Gated repro->...->verify-Zyklus mit Rollback + das Kandidaten-Gate (DS08)
│   ├── operations.py      # Verifiziertes Zustands-Backup/Restore + operativer Health-Check (DS09)
│   ├── delivery.py        # Liefermanifest (sha256 pro Datei) + ehrliche Reifegradbewertung, überschätzt nie (DS10)
│   ├── cli.py             # Einstiegspunkt der Unterbefehle config / inventory / station / migrate / task / queue / provider / incident / repair / ops / deliver
│   ├── api.py             # Eine kleine authentifizierte HTTP-API, nur Loopback (jede Route außer Health braucht ein Bearer-Token)
│   ├── identifiers.py     # Die eine Stelle, die festlegt, wie ein Name (Konto, Pfad, Task- oder Worker-ID) aussehen darf
│   ├── plugins.py         # Lebenszyklus der Plugins: finden, prüfen, aktivieren, ausführen, deaktivieren
│   ├── sandbox.py         # Isolation des Task-Runners auf Betriebssystemebene
│   ├── signing.py         # Ed25519-Signaturen für Reparaturkandidaten, Freigaben und Backup-Manifeste
│   ├── taskflow.py        # Was eine Task-Ausführung umgibt: das Repository in der festgelegten Revision bereitstellen, die Nebenläufigkeitsgrenze und die Lebensdauer des Arbeitsbereichs
│   └── worker.py          # Die Worker-Schleife, die einen Task von der Lease bis zum Ergebnis führt
├── configs/
│   ├── host-profile.example.json
│   ├── toolchains.example.json
│   ├── task-policy.example.json      # allow_deploy: false, so veröffentlicht und getestet
│   ├── remote-station.example.json   # bindet an 127.0.0.1, so veröffentlicht und getestet
│   ├── migration-destinations.example.json   # vier beweisbar getrennte Wurzeln
│   ├── task-recipe.example.json          # fixierte Revision + Befehl aus der Allow-Liste
│   ├── ai-provider.example.json          # kind: fake, Zeitlimit + Budget für Aufrufe/Tokens/Kosten
│   └── incident-transport.example.json   # Vertragsversion + Replay-Fenster + Ratenlimit (keine Geheimnisse)
│   # (die queue-Befehle nehmen einen --db-Pfad, keine Konfigurationsdatei)
├── tests/                # Reale Tests für jedes obige Modul, inkl. der veröffentlichten Beispiel-Configs
├── docs/
│   ├── CLI_REFERENCE.md    # Jeder Unterbefehl, seine Flags und der Exit-Code-Vertrag
│   ├── CONFIG_SCHEMA.md    # Die reale JSON-Form der drei Konfigurationsdokumente
│   ├── REMOTE_STATION.md   # Das DS02-Remote-Stationsprofil, die Vorabprüfung und der Trockenlauf-Plan
│   ├── MIGRATION_FROM_PC.md  # Das DS03-Inventar, die Klassen und der Plan der konservativen Migration
│   ├── WORKSPACE_AND_RUNNER.md  # Das DS04-Recipe, der isolierte Workspace und der begrenzte Runner
│   ├── DURABLE_QUEUE.md      # Die DS05-Warteschlange, die Leases und das Ausführungsjournal
│   ├── AI_PROVIDER.md        # Der DS06-Provider-Seam und sein Sicherheitsvertrag (nur Fake)
│   ├── INCIDENT_TRANSPORT.md # Die DS07-signierte Nachricht, die Prüfungen und die Round-Trip-Session
│   ├── REPAIR_CYCLE.md       # Der DS08-Reparaturzyklus mit Gates, seine Kontrollen und der Rollback
│   ├── OPERATIONS.md         # Das verifizierte DS09-Backup/Restore und der operative Health-Check
│   ├── DELIVERY.md           # Das DS10-Liefermanifest und die ehrliche Reifegradbewertung
│   ├── ARCHITECTURE.md     # Zweck, Arbeitsmodi, anfänglicher Umfang, Festplatte
│   ├── OPS_INTEGRATION.md  # Die 17-Beziehungs-Karte + Eigentümer-Tabelle
│   ├── PLUGINS.md  # Plugin-Manifest, die drei Arten, Lebenszyklus und Sandbox-Grenzen
│   ├── MATURITY_CRITERIA.md # Austrittskriterien der Reifestufe (was gelten muss, um eine Stufe aufzusteigen)
│   └── openapi.json # Die OpenAPI-Beschreibung der HTTP-API
├── examples/plugins/      # Beispiel-Plugins: ein Bericht, ein Generator
├── examples/              # plugins/: Beispiel-Plugins (host-report, readme-generator)
├── images/                # Medien und App-Icons
├── tools/
│   ├── build_test.py      # Nicht-versionierende Build-/Kompilierungsprüfung
│   ├── ci_validate.py     # Manifest-/CHANGELOG-/Doku-Validierung, von der CI verwendet
│   ├── _doc_policy.py     # Von der Familie geteilte Dokumentationsregeln (Kopie der von HYDRA-UMC-SDK, synchron gehalten)
│   ├── _readme_parity.py  # Prüfung, dass die acht READMEs dieselbe Struktur haben (Kopie der von HYDRA-UMC-SDK, synchron gehalten)
│   └── hydra_project_tool.py # Dieselben Befehle in jedem Repository: validate, test, ci, version, status, bump
├── build.sh / build.bat   # venv + editierbare Installation + Prüfung + Tests
├── build-test.sh / .bat   # Nur nicht-mutierende Build-Validierung
├── run.sh / run.bat       # Reale Demo inventory scan + config validate (ohne Argumente), oder leitet einen echten CLI-Befehl weiter
├── bump_version.py        # Versionserhöhung im Kilometerzähler-Stil (nur vom expliziten `bump`-Befehl ausgeführt)
└── bump_manifest_version.py # Synchronisiert die Version von hydra-umc.project.json mit der nativen (--sync)
```

## ⚙️ BUILD- UND AUSFÜHRUNGSANLEITUNG

```bash
chmod +x build.sh   # einmalig
./build.sh          # erstellt .venv, pip install -e ".[dev]", Prüfung + Tests
./run.sh                                  # reale Demo: inventory scan gegen diesen
                                           # GitHub-Workspace, dann config validate
./run.sh inventory scan --root DIR
./run.sh config validate configs/task-policy.example.json --kind task-policy
```

Unter Windows: `build.bat`, dann `run.bat` (gleiche Demo ohne
Argumente) / `run.bat inventory scan ...` / `run.bat config
validate ...`. `build-test.sh`/`.bat` führt dieselbe nicht-mutierende
Python-Syntaxprüfung durch, die auch der eigene CI-Workflow des
Projekts durchführt, ohne die Projektversion oder das CHANGELOG
anzurühren - es führt NICHT die Testsuite selbst aus; führen Sie
`./build.sh`/`build.bat` (oder direkt `python -m unittest discover -s tests`) für die
vollständige lokale Testsuite aus.

**Fehlerbehebung**

- `config validate` beendet sich mit Code `1` und `INVALID: ...`: Lesen
  Sie die Meldung - sie listet jedes fehlgeschlagene Feld auf, nicht
  nur das erste. Siehe
  [docs/CONFIG_SCHEMA.md](docs/CONFIG_SCHEMA.md) für die genaue
  erwartete Form.
- `inventory scan` meldet ein Problem in einem Verzeichnis, das Sie für
  sauber hielten: Dieses Verzeichnis hat ein vorhandenes, aber
  unlesbares, fehlerhaftes oder unvollständiges
  `hydra-umc.project.json` - ein Verzeichnis ganz ohne Manifest wird
  niemals als Problem gemeldet.

## 🚀 ROADMAP

Diese Version bringt DS01 bis DS10: der Zehn-Lieferungen-Plan ist
komplett. Jede Lieferung, in Reihenfolge:

- **DS02 - Reproduzierbare Remote-Station.** ✅ Geliefert: ein
  validiertes Remote-Stationsprofil, eine schreibgeschützte
  Host-Vorabprüfung und ein Trockenlauf-Provisionierungsplan
  (`station`-Unterbefehle). Kein Host wird verändert und kein Schritt
  ausgeführt.
- **DS03 - Konservative Migration.** ✅ Geliefert: hasht und
  klassifiziert jede Datei eines Quell-Checkouts und plant jede Klasse
  (sauber / geändert / untracked / privat) in ihr eigenes getrenntes
  Ziel, mit einem Bundle für die ungepushten Commits (`migrate`-
  Unterbefehle). Sie kopiert nichts und rührt die Quelle nie an. Einen
  genehmigten Plan auszuführen ist eine spätere Lieferung.
- **DS04 - Workspace und begrenzter Runner.** ✅ Geliefert: pro-Task
  isolierter Workspace (zwei Aufgaben kollidieren nie; `..`-, absolute
  und aus dem Workspace herausführende Symlink-Pfade abgelehnt), nur ein
  Befehl aus der Allow-Liste, eine bereinigte Umgebung, und ein Timeout,
  das die ganze Prozessgruppe killt (`task`-Unterbefehle). Es führt
  einen Subprozess aus, stellt aber nichts bereit.
- **DS05 - Dauerhafte Warteschlange und nachvollziehbare Ergebnisse.**
  ✅ Geliefert: eine SQLite-Warteschlange mit Leases und ein
  Append-only-Ausführungsjournal, die einen Neustart überstehen; ein
  doppeltes Enqueue ist nie ein zweiter Job, eine Unterbrechung nie ein
  falscher Erfolg, eine geänderte Basis blockiert die Promotion
  (`queue`-Unterbefehle).
- **DS06 - Austauschbarer KI-Provider.** ✅ Geliefert (Fake-Hälfte): ein
  deterministischer Fake-Provider hinter einem Sicherheitsvertrag -
  Timeout / fehlerhaft / Kontingent werden begrenzte Ergebnisse, ein
  Budget stoppt den Schritt, der Vorschlag ist inerte Daten, die nichts
  gewähren und nichts bereitstellen (`provider suggest`). Der echte
  Provider ist eine Nutzerentscheidung.
- **DS07 - Koordinierte Vorfälle mit HYDRA-UMC-OPS-AGENT.** ✅
  Geliefert: ein HMAC-authentifizierter Incident-Transport mit Replay-/
  Impersonation-/Überlast-/Versionsprüfungen und einem vollständigen
  Round Trip Einreichen → Diagnose → Post-Deploy-Verifikation, der sich
  nach einem Verbindungsabbruch abgleicht (`incident verify`).
- **DS08 - Erster vollständig kontrollierter Reparaturzyklus.** ✅
  Geliefert: eine Zustandsmaschine mit Gates
  repro->Vorfall->Patch->Regression->Build-Test->Genehmigung->isolierte
  Installation->Verifikation, die einen manipulierten oder
  fehlgeleiteten Kandidaten blockiert und bei fehlgeschlagener
  Nachinstallationsprüfung zurückrollt (`repair check-candidate`).
- **DS09 - Stabiler Betrieb/Wiederherstellung.** ✅ Geliefert:
  operative Health-Checks über Warteschlange und Platte, und ein
  verifiziertes Zustands-Backup/Restore, das ein Backup einer anderen
  Instanz oder ein beschädigtes ablehnt (`ops`-Unterbefehle).
- **DS10 - Lieferpaket und ehrliche Reifegradbewertung.** ✅ Geliefert:
  `deliver manifest` erfasst einen sha256 pro geliefeter Datei und liest
  die reale CLI-Oberfläche, die Version und die Testanzahl zurück;
  `deliver evaluate` meldet jede der zehn Lieferungen gegen reale
  Evidenz (DS06 ist `partial` - nur der Fake wird geliefert), listet
  sieben Grenzen klar auf und meldet ein `overall_maturity`, das im Code
  fest auf `functional` steht.

**Reifegrad.** Der Plan ist komplett; der Reifegrad ist `functional`: Die Software ist gebaut und durch Tests abgedeckt, aber nicht auf realer Hardware oder realen Diensten verifiziert - das ist ein eigener, späterer Schritt. In diesem Repository steht eine lauffähige, getestete Umsetzung von Verträgen und Grenzen. Nichts hier provisioniert einen Host, führt ein
Deployment aus, verbindet die Teile zu einer Worker-Schleife oder hat
reale Hardware berührt. `deliver evaluate` sagt genau das, und seine
`known_limitations`-Liste ist die ehrliche To-do-Liste. Siehe
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) dafür, was jede Lieferung
explizit ein- und ausschließt.

## 🔗 Verwandte Projekte

Dieses Projekt ist Teil des HYDRA-UMC-Robotik-Ökosystems desselben Autors (JuanenRac / Electro Hobby 3D). Gut zu wissen, da eine Anfrage sich eigentlich auf eines dieser Projekte statt auf dieses Repository beziehen könnte.

**Direkt Verwandt**
- **[HYDRA-UMC-OPS-AGENT](https://github.com/JuanenRac/HYDRA-UMC-OPS-AGENT)** — besitzt den Lebenszyklus von Wartungsvorfällen (Beweise, Diagnose, menschlich genehmigte Änderung, Canary-Deployment, Verifizierung); DEV-SERVER koordiniert mit ihm, statt ihn zu ersetzen, und genehmigt niemals seine eigenen Aufgaben.
- **[HYDRA-UMC-SDK](https://github.com/JuanenRac/HYDRA-UMC-SDK)** — der gemeinsame JSON-Schema-Vertrag, gegen den jeder Aufgaben-/Ergebnisaustausch zwischen DEV-SERVER und dem Rest des Ökosystems validiert wird, sobald dieser Vertrag existiert.
- **[HYDRA-UMC-UPDATER](https://github.com/JuanenRac/HYDRA-UMC-UPDATER)** — der eigentliche Konsument eines von DEV-SERVER gebauten, von OPS-AGENT genehmigten Kandidaten; die Auslieferung an einen Knoten läuft immer über UPDATERs eigenen atomaren-per-Verifizierung-Pfad, nie über eine direkte Kopie von einem Runner.
- **[HYDRA-UMC-OS-REBUILDER](https://github.com/JuanenRac/HYDRA-UMC-OS-REBUILDER)** — ein weiterer "Ecosystem Operations"-Geschwisterprojekt: baut ein frisches CM5-Image, statt Entwicklungsarbeit zu hosten.

**Ebenfalls Teil des Ökosystems**

*Kern-Hardware & Plattform*
- **[HYDRA-UMC](https://github.com/JuanenRac/HYDRA-UMC)** — der Entwurf des Motherboards des Roboterarms: CM5-Host + Dual-Core-STM32H745, gedacht zur Koordination von bis zu 8 Werkzeugarmen über CAN-OTA/SPI-OTA (Firmware in einer frühen Phase; noch keine bestückte Platine).
- **[HYDRA-UMC-OS](https://github.com/JuanenRac/HYDRA-UMC-OS)** — reproduzierbare Raspberry-Pi-OS-Produktschicht für die CM5: schreibgeschützter Agent, validierte Konfiguration/Profile, WiFi-Erstkontakt-Provisionierung.

*Kern-Backend & Clients*
- **[HYDRA-UMC-SERVER](https://github.com/JuanenRac/HYDRA-UMC-SERVER)** — das echte Headless-Backend (REST/WebSocket), mit dem jeder Steuerungsclient tatsächlich spricht.
- **[HYDRA-UMC-STUDIO](https://github.com/JuanenRac/HYDRA-UMC-STUDIO)** — Web-Steuerungs-Dashboard mit Echtzeit-3D-Visualisierung mehrerer Roboter.
- **[HYDRA-UMC-SUITE](https://github.com/JuanenRac/HYDRA-UMC-SUITE)** — Desktop-Schwarmkommandozentrale (PySide6) für mehrere Server gleichzeitig.
- **[HYDRA-UMC-ANDROID-CONTROL](https://github.com/JuanenRac/HYDRA-UMC-ANDROID-CONTROL)** — native Android-Steuerungs-App mit biometrischem Login und einem gekoppelten Wear-OS-Begleiter.
- **[HYDRA-UMC-IOS-CONTROL](https://github.com/JuanenRac/HYDRA-UMC-IOS-CONTROL)** — iOS/iPadOS-Steuerungs-App (Flutter) mit Echtzeit-WebSocket-Synchronisation.
- **[HYDRA-UMC-DSI](https://github.com/JuanenRac/HYDRA-UMC-DSI)** — native Touch-Oberfläche für den eingebauten 7"-DSI-Touchscreen, direkt auf der CM5 eingebettet.
- **[HYDRA-UMC-EDITOR-URDF](https://github.com/JuanenRac/HYDRA-UMC-EDITOR-URDF)** — grafischer Desktop-URDF-Ersteller/-Editor, der fertige Modelle in den eigenen Katalog von STUDIO überträgt.
- **[HYDRA-UMC-EDITOR-STL](https://github.com/JuanenRac/HYDRA-UMC-EDITOR-STL)** — Desktop-STL-Modelleditor, der echte Teile im selben Modellkatalog transformiert/ersetzt/entfernt/hinzufügt, den auch HYDRA-UMC-EDITOR-URDF bearbeitet.
- **[HYDRA-UMC-BRIDGE-AMR](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-AMR)** — Koordinationsschranke für AGV-/AMR-Flotten über einen VDA-5050-MQTT-Publisher (nur gegen eine emulierte Flotte getestet).
- **[HYDRA-UMC-BRIDGE-CNC](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-CNC)** — High-Level-Koordinator für CNC-Zellen mit GRBL-Status-/Steuerbyte-Zugriff (nur gegen einen Emulator getestet).
- **[HYDRA-UMC-BRIDGE-DROIDS](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-DROIDS)** — Koordinationsschranke für laufende/humanoide Droiden, mit einem Boston-Dynamics-Spot-Befehlssender (nur gegen einen Emulator getestet).
- **[HYDRA-UMC-BRIDGE-LASER](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-LASER)** — Koordinator für Laserzellen, liest 3 Schlüssel-/Gehäuse-/Verriegelungs-GPIO-Signale (nur gegen einen simulierten Chip getestet; kann keinen Laser scharfschalten oder auslösen).
- **[HYDRA-UMC-BRIDGE-OPENPNP](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-OPENPNP)** — sicherer Koordinator auf hoher Ebene des Platinenflusses für OpenPnP-Pick-and-Place.
- **[HYDRA-UMC-BRIDGE-PRINTER3D](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-PRINTER3D)** — sichere Koordinationsgrenze für Moonraker/Klipper-3D-Drucker, mit real gesteuerten Auftragsbefehlen.
- **[HYDRA-UMC-BRIDGE-ROS2](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-ROS2)** — Koordinator mit einem träge importierten rclpy-ROS-2-Transport (noch nicht gegen eine ROS-2-Installation ausgeführt).
- **[HYDRA-UMC-BRIDGE-UAV](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-UAV)** — Koordinationsschranke für kameraausgestattete UAVs, mit einem MAVLink-Befehlssender (nur gegen einen Emulator getestet).

*URTC-Werkzeugplattform*
- **[URTC](https://github.com/JuanenRac/URTC)** — Firmware für die physische Universal-Robot-Tool-Controller-Platine, 25+ Werkzeugprofile über CAN-Bus.
- **[URTC-FLASHER](https://github.com/JuanenRac/URTC-FLASHER)** — Desktop-GUI-Flashing-Tool für URTC-Platinen, CAN-OTA plus Full-Chip-SWD/JTAG.
- **[URTC-TESTER](https://github.com/JuanenRac/URTC-TESTER)** — Desktop-Live-CAN-Bus-Diagnosetool für URTC-Platinen, ein Panel pro Werkzeugprofil.
- **[URTC-WEB-STUDIO](https://github.com/JuanenRac/URTC-WEB-STUDIO)** — browserbasierte Alternative zu URTC-TESTER über die Web-Serial-API, keine lokale Installation nötig.
- **[URTC-GATEWAY](https://github.com/JuanenRac/URTC-GATEWAY)** — Gateway vor dem CAN-Bus von URTC: Liste erlaubter Kennungen, Ratenbegrenzung und Sitzungsschlüssel; Software auf dem Computer getestet, noch nicht an einem echten Bus.

*Vision-KI-Knoten (Hailo-8)*
- **[HYDRA-UMC-VISION-NODE](https://github.com/JuanenRac/HYDRA-UMC-VISION-NODE)** — Integrations-Hub für die Hailo-8-Vision-Pipeline, mit einer echten Hardware-Bereitschaftsprüfung pro Stufe.
- **[HYDRA-UMC-DETECTION-HEF](https://github.com/JuanenRac/HYDRA-UMC-DETECTION-HEF)** — echtes Register kompilierter Modelle mit Hailo-Architektur-/Prüfsummen-Sicherheitsladeverifizierung.
- **[HYDRA-UMC-VISION-STREAMER](https://github.com/JuanenRac/HYDRA-UMC-VISION-STREAMER)** — echte GStreamer-Pipeline + MediaMTX-Konfigurationsgenerator mit einer echten HailoRT-Integrationsgrenze.
- **[HYDRA-UMC-VISUAL-SERVOING-API](https://github.com/JuanenRac/HYDRA-UMC-VISUAL-SERVOING-API)** — Position-Based-Visual-Servoing-Korrekturgesetz mit Freigabe abhängig vom Zonenstatus; noch keine Posenschätzung per Kamera.
- **[HYDRA-UMC-SAFETY-ZONES](https://github.com/JuanenRac/HYDRA-UMC-SAFETY-ZONES)** — v0-Logik für Zonenverletzung, Kalibrierungsaktualität und E-STOP-Anforderung, die Objektpositionen aus einer Datei nimmt; kein Detektor speist sie, und noch kein physischer E-STOP ist angeschlossen.

*Kognitiver KI-Knoten (Hailo-10)*
- **[HYDRA-UMC-COGNITIVE-NODE](https://github.com/JuanenRac/HYDRA-UMC-COGNITIVE-NODE)** — Integrations-Hub für die Hailo-10-Kognitions-Pipeline (LLM/VLA/Sprach-Orchestrierung).
- **[HYDRA-UMC-VLA-ENGINE](https://github.com/JuanenRac/HYDRA-UMC-VLA-ENGINE)** — echte Action-Token-Kodierung/-Dekodierung und Trajektoriengenerierung für ein Vision-Language-Action-Modell.
- **[HYDRA-UMC-VOICE-UI](https://github.com/JuanenRac/HYDRA-UMC-VOICE-UI)** — echtes Sprach-Frontend (VAD + Intent-Parser) mit einem begrenzten, bestätigungspflichtigen Watch-Relay.
- **[HYDRA-UMC-SEMANTIC-PLANNER](https://github.com/JuanenRac/HYDRA-UMC-SEMANTIC-PLANNER)** — echte regelbasierte Aufgabenzerlegung und semantische Fehlerbehebung über MCU-Fehlercodes.
- **[HYDRA-UMC-DOCS-QA](https://github.com/JuanenRac/HYDRA-UMC-DOCS-QA)** — echte reine-stdlib-TF-IDF-Dokumentensuche über die eigene Markdown-Dokumentation dieses Ökosystems.
- **[HYDRA-UMC-LOCAL-TECHNICIAN](https://github.com/JuanenRac/HYDRA-UMC-LOCAL-TECHNICIAN)** — lokaler, richtlinien-gesteuerter KI-Wartungstechniker für das Ökosystem selbst - beobachtet, diagnostiziert und schlägt Korrekturen vor; die zwei höchsten Risikostufen sind absichtlich noch nicht implementiert.

*Orchestrierung & Schwarm*
- **[HYDRA-UMC-ORCHESTRATOR](https://github.com/JuanenRac/HYDRA-UMC-ORCHESTRATOR)** — Integrations-Hub mit einem echten gRPC/Protobuf-Health-Report-Vertrag und einer Missions-Zustandsmaschine.
- **[HYDRA-UMC-JOB-DISPATCHER](https://github.com/JuanenRac/HYDRA-UMC-JOB-DISPATCHER)** — echte prioritätsbasierte Job-Warteschlange mit Deduplizierung, über eine echte HTTP-API.
- **[HYDRA-UMC-NODE-HEALING](https://github.com/JuanenRac/HYDRA-UMC-NODE-HEALING)** — echter gRPC-basierter Flotten-Gesundheitswächter mit eigenem Retry/Backoff und Identitätsabweichungserkennung.
- **[HYDRA-UMC-PATH-PLANNER-3D](https://github.com/JuanenRac/HYDRA-UMC-PATH-PLANNER-3D)** — echter RRT-basierter 3D-Pfadplaner mit echter Hindernis-/Arbeitsraum-Kollisionsvalidierung.
- **[HYDRA-UMC-SWARM-SYNC](https://github.com/JuanenRac/HYDRA-UMC-SWARM-SYNC)** — echte CRDT-LWW-Element-Map-Zustandssynchronisation, eigenschaftsgetestet für Multi-Zellen-Konvergenz.

*Digitaler Zwilling & Simulation*
- **[HYDRA-UMC-TWIN](https://github.com/JuanenRac/HYDRA-UMC-TWIN)** — Integrations-Hub für die Digital-Twin-Engine, mit einem echten Versionskompatibilitäts-Synchronisationsvertrag.
- **[HYDRA-UMC-HIL-BRIDGE](https://github.com/JuanenRac/HYDRA-UMC-HIL-BRIDGE)** — Hardware-in-the-Loop-Router mit einer Software-Kollisionsverriegelung zwischen Simulation und echter Hardware (ohne echte Hardware getestet).
- **[HYDRA-UMC-PHYSICS-REPLICA](https://github.com/JuanenRac/HYDRA-UMC-PHYSICS-REPLICA)** — echte Vorwärtskinematik und Gelenkgrenzenvalidierung über eine echte URDF-Teilmenge.
- **[HYDRA-UMC-SYNTHETIC-DATA-GEN](https://github.com/JuanenRac/HYDRA-UMC-SYNTHETIC-DATA-GEN)** — echter prozeduraler 2D-Szenengenerator mit YOLO/COCO-Annotationsexport.

*Daten & Analytik*
- **[HYDRA-UMC-DATALAKE](https://github.com/JuanenRac/HYDRA-UMC-DATALAKE)** — echter sqlite3-basierter Zeitreihenspeicher mit einer echten Ingest-/Query-HTTP-API.
- **[HYDRA-UMC-ANOMALY-DETECTOR](https://github.com/JuanenRac/HYDRA-UMC-ANOMALY-DETECTOR)** — echter FFT- + statistischer Baseline-Anomaliedetektor mit Drift-Überwachung.
- **[HYDRA-UMC-PRODUCTION-REPORTS](https://github.com/JuanenRac/HYDRA-UMC-PRODUCTION-REPORTS)** — echte OEE-/Verfügbarkeitsberechnung über den DATALAKE-Verlauf, mit reproduzierbarem CSV-Export.
- **[HYDRA-UMC-TELEMETRY-COLLECTOR](https://github.com/JuanenRac/HYDRA-UMC-TELEMETRY-COLLECTOR)** — echte CAN-/WebSocket-Ingestion-Pipeline in DATALAKE, mit Sequenz-Deduplizierung.

*Industrie-Gateway*
- **[HYDRA-UMC-GATEWAY-INDUSTRIAL](https://github.com/JuanenRac/HYDRA-UMC-GATEWAY-INDUSTRIAL)** — Integrations-Hub, der zu Industrieprotokollen weiterleitet, mit einer echten Befehls-Whitelist-/Backpressure-Schicht.
- **[HYDRA-UMC-OPCUA-SERVER](https://github.com/JuanenRac/HYDRA-UMC-OPCUA-SERVER)** — echter OPC-UA-Adressraum, verifiziert mit einer echten Binärprotokoll-Client-Sitzung.
- **[HYDRA-UMC-MQTT-BROKER](https://github.com/JuanenRac/HYDRA-UMC-MQTT-BROKER)** — echter MQTT-Broker mit optionaler Client-Authentifizierung und Topic-ACLs.
- **[HYDRA-UMC-MTCONNECT-ADAPTER](https://github.com/JuanenRac/HYDRA-UMC-MTCONNECT-ADAPTER)** — echte MTConnect-`/probe`- und `/current`-XML-Endpunkte mit Ausgabe im Degraded-Modus.

*Ergänzende Werkzeuge*
- **[HYDRA-UMC-DASHBOARD-AI](https://github.com/JuanenRac/HYDRA-UMC-DASHBOARD-AI)** — Panels für intelligente Zusammenfassungen und Anomalie-Hervorhebung über DATALAKE/ANOMALY-DETECTOR, mit ehrlichem statistischem Fallback.
- **[HYDRA-UMC-TOOL-CLI](https://github.com/JuanenRac/HYDRA-UMC-TOOL-CLI)** — Flotten-CLI mit einem echten, stabilen Exit-Code-Vertrag, ein echter Live-Client der eigenen API von HYDRA-UMC-SERVER.
- **[HYDRA-UMC-WATCH](https://github.com/JuanenRac/HYDRA-UMC-WATCH)** — WearOS-Begleit-App mit haptischen Alarmmustern und einem Sprach-Relay zum gekoppelten Telefon (noch nicht auf einer physischen Uhr ausgeführt).
- **[HYDRA-UMC-CONNECTOR-HUB](https://github.com/JuanenRac/HYDRA-UMC-CONNECTOR-HUB)** — Katalog externer Adapter-Fähigkeiten, per Design nur GET.
- **[URTC-SMART-RACK](https://github.com/JuanenRac/URTC-SMART-RACK)** — Firmware für ein Platinen-Montageregal mit echter Werkzeug-ID-Dekodierung und Smart-Idle-Vorheizlogik.
- **[URTC-VISION-TOOL](https://github.com/JuanenRac/URTC-VISION-TOOL)** — Firmware plus ein echter Python-Vision-Begleiter für einen thermischen/RGB-Inspektionskopf.

---

## 📚 Dokumentation & Community

- **[docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md)** — jeder Unterbefehl, seine Flags und der Exit-Code-Vertrag.
- **[docs/CONFIG_SCHEMA.md](docs/CONFIG_SCHEMA.md)** — die reale JSON-Form von `HostProfile`/`ToolchainPolicy`/`TaskPolicy`.
- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — Zweck, die beiden Arbeitsmodi, anfänglicher Umfang und Festplattenorganisation.
- **[docs/OPS_INTEGRATION.md](docs/OPS_INTEGRATION.md)** — die vollständige 17-Beziehungs-Karte und die Zustandseigentümer-Tabelle.
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — Technologie-Stack und Coding-Richtlinien für einen Pull Request.
- **[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)** — die in dieser Community erwarteten Verhaltensstandards.
- **[SECURITY.md](SECURITY.md)** — wie man eine Schwachstelle meldet, und die echten Sicherheitsschwerpunkte dieses Projekts.
- **[SUPPORT.md](SUPPORT.md)** — wo man Fragen stellt und Fehler meldet.

## 👤 AUTOR
**JuanenRac** (Electro Hobby 3D)
📧 electrohobby3d@gmail.com
📺 [youtube.com/@electrohobby3d](https://youtube.com/@electrohobby3d)

## 📜 LIZENZ

GPL-3.0-or-later (Software) / CC BY-SA 4.0 (Dokumentation) - siehe [LICENSE.md](LICENSE.md).
