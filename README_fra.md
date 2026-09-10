<p align="center">
  <img src="images/HYDRA_UMC_BANNER.svg" alt="Bannière HYDRA-UMC-DEV-SERVER" width="100%">
</p>

# 🖥️ HYDRA-UMC-DEV-SERVER

<p align="center"><a href="README.md">🇺🇸 English</a> | <a href="README_spa.md">🇪🇸 Español</a> | 🇫🇷 <b>Français</b> | <a href="README_ita.md">🇮🇹 Italiano</a> | <a href="README_deu.md">🇩🇪 Deutsch</a> | <a href="README_zho.md">🇨🇳 简体中文</a> | <a href="README_jpn.md">🇯🇵 日本語</a></p>

### 🏗️ Serveur de Développement Reproductible pour Tout l'Écosystème

<p align="center">
  <img src="https://img.shields.io/badge/Licence-GPL%203.0-blue.svg" alt="GPL 3.0">
  <img src="https://img.shields.io/badge/Langage-Python%203.11%2B-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/Noyau-stdlib%20uniquement-brightgreen.svg" alt="Noyau stdlib uniquement">
  <img src="https://img.shields.io/badge/Livraison-DS06%20sur%2010-367BF5.svg" alt="DS06 sur 10">
</p>

> **Statut : v0.0.6, scaffolding - DS06 sur 10 (contrats, limites et un
> squelette vérifiable).** Un schéma de configuration réel et testé
> (`config validate`) dont la politique par défaut **n'accorde aucune
> permission de déploiement à aucune tâche**, et une découverte de
> manifestes en lecture seule (`inventory scan`) qui trouve les propres
> fichiers `hydra-umc.project.json` de cet écosystème - y compris celui
> de ce dépôt lui-même. DS02 ajoute un profil de station distante validé
> (`station validate`), une vérification préalable de l'hôte en
> **lecture seule** qui se contente d'indiquer si un hôte est prêt
> (`station preflight`, ne change rien), et un plan de provisionnement
> **à blanc** (`station plan`, n'exécute jamais une étape), et une **migration conservatrice** qui ne copie rien. DS04 ajoute l'**exécuteur borné** (`task validate` / `task run`) : il lance **une** commande d'une liste blanche dans un **espace de travail isolé par tâche** (un `..`, un chemin absolu ou un symlink hors de l'espace de travail est refusé ; deux tâches n'en partagent jamais un), avec un **environnement expurgé** (aucun `*_TOKEN` / `*_KEY` / `*_SECRET` hérité), sous un délai borné qui **tue tout le groupe de processus**. **DS05 ajoute une file durable SQLite + un journal d'exécution** (`queue …`) qui survivent à un redémarrage : un `enqueue` en double n'est jamais un second travail ; le bail d'un worker planté expire et `reconcile` renvoie la tâche à `queued` ; un résultat d'un worker qui ne détient plus le bail est **refusé, pas marqué fait** ; une base qui a bougé depuis l'enqueue **bloque la promotion même sur un code de sortie 0**. Il ne déploie toujours rien. DS03 ajoute la **migration conservatrice** (`migrate inventory` / `migrate plan`) : elle hache et classe chaque fichier d'un checkout source et planifie chaque classe - propre, modifié localement, non suivi, privé - vers sa **propre destination distincte**, en refusant qu'un fichier privé atterrisse où que ce soit de partageable. Elle ne copie rien et ne touche jamais la source. Il n'existe
> pas encore d'espace de travail, d'exécuteur de tâches, de file
> d'attente durable ni d'intégration avec un fournisseur d'IA - ce sera
> DS04, DS05 et DS06, livraisons futures. Voir
> [docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md) pour la surface de
> commandes exacte qui existe aujourd'hui.

---

## 1. 🛠️ VUE D'ENSEMBLE TECHNIQUE

HYDRA-UMC-DEV-SERVER est une infrastructure de développement pour
l'écosystème HYDRA-UMC/URTC : un hôte reproductible (cible : un
Raspberry Pi 5 ou Compute Module 5, 8 Go, démarré depuis NVMe) qui
hébergera le code source de cet écosystème et exécutera des tâches de
programmation/build/test bornées et soumises à une politique explicite -
aussi bien pour des personnes que pour des assistants IA. Ce n'est
**pas** une nouvelle IA à entraîner, **pas** un système d'exploitation de
remplacement, et il ne décide jamais lui-même qu'une machine est sûre à
modifier.

DS01 a apporté deux éléments réels et utiles indépendamment :

1. **Schéma de configuration** (`config validate`) - trois documents
   JSON (`HostProfile`, `ToolchainPolicy`, `TaskPolicy`), chacun avec une
   validation réelle et un test négatif réel pour chaque forme rejetée.
   L'invariant le plus important dès le premier jour :
   `TaskPolicy.allow_deploy` vaut `False` par défaut, et seul un
   document fixant le booléen JSON littéral `true` peut produire une
   politique où ce droit est accordé.
2. **Découverte de manifestes** (`inventory scan`) - le même schéma réel
   et testé déjà utilisé par le rôle edge de HYDRA-UMC-OPS-AGENT pour
   trouver et valider un `hydra-umc.project.json`, réutilisé ici plutôt
   que réécrit.

DS02 en ajoute trois autres, toutes sous la sous-commande `station` et
toutes toujours « valider et décrire, jamais agir » :

3. **Profil de station distante** (`station validate`) - un document JSON
   (`RemoteIdentity` + `RemoteAccess` + chaînes d'outils requises) avec
   la même validation qui cumule les erreurs. Son invariant du premier
   jour : le point d'accès d'édition distante écoute en loopback/privé,
   et une adresse routable est refusée sauf si le document fixe le
   booléen littéral `allow_public_bind: true` ; l'identité est un compte
   système dédié, jamais `root` ni un utilisateur de connexion.
4. **Vérification préalable de l'hôte** (`station preflight`) - lit un
   profil et indique, via une interface d'inspection injectable, si
   *cet* hôte est réellement prêt à devenir cette station (version de
   Python, espace disque libre, espace de travail inscriptible, outils
   dans le `PATH`, port libre, identité étant un vrai compte système).
   Ne change jamais l'hôte.
5. **Plan de provisionnement à blanc** (`station plan`) - représente ce
   qu'un installateur réel *ferait* (l'argv de chaque étape capturé
   comme donnée) plus le texte complet de l'unité systemd, et refuse de
   construire un plan par-dessus une vérification préalable en échec.
   Rien n'est exécuté.

DS03 ajoute la migration conservatrice, même règle « lire et décrire,
jamais agir » - elle ne copie rien et ne touche jamais la source :

6. **Inventaire + plan de migration** (`migrate inventory` / `migrate
   plan`) - parcourt un checkout source (seulement les fichiers que git
   considère comme faisant partie du projet - un `.venv` local ou une
   sortie de build est git-ignoré et jamais vu), calcule le SHA-256 de
   chaque fichier et classe chacun : `tracked-clean`, `tracked-modified`,
   `untracked`, `private` (une `PrivacyPolicy` élargissable : le dossier de docs privés,
   `.env*`, `*.pem`, `id_ed25519*`, ...). Les commits faits mais jamais
   poussés sont enregistrés à part. `migrate plan` mappe chaque classe
   vers sa **propre** destination parmi quatre racines prouvablement
   distinctes (`MigrationDestinations.from_dict` refuse des racines
   égales ou imbriquées), regroupe les commits non poussés, émet un
   manifeste de hachages complet, et imprime `REFUSED` si un fichier
   privé se résolvait sous une racine partageable.

DS04 est la première livraison qui exécute un sous-processus - et elle
reste très encadrée :

7. **Recette de tâche + exécuteur d'espace de travail** (`task validate`
   / `task run`) - une `TaskRecipe` fixe une `revision` (un nom de
   branche est refusé) et une `command` d'une liste blanche (`argv[0]`
   doit être dans `allowed_commands` de la politique, sinon le run est
   `rejected` et rien n'est lancé). `task run` crée `<base>/<task_id>/`
   - en refusant un qui existe déjà, donc **deux tâches ne partagent
   jamais un espace de travail** - y lance la commande avec un
   **environnement expurgé** (seulement `PATH` / `HOME` / `LANG` / `TZ`
   ; jamais un `GITHUB_TOKEN`, `AWS_SECRET_ACCESS_KEY`,
   `ANTHROPIC_API_KEY`, `SSH_AUTH_SOCK` hérité), borné par
   `timeout_seconds`, et à l'expiration ou à l'annulation **tue tout le
   groupe de processus** - prouvé par un test réel qui lance un
   petit-enfant et confirme que les deux meurent. Un `..`, un chemin
   absolu ou un symlink hors de l'espace de travail dans `input_paths`
   est refusé. Il ne déploie rien.

DS05 ajoute la durabilité - une file de tâches et son journal
d'exécution qui survivent à un redémarrage du processus. Il enregistre,
il n'exécute pas :

8. **File durable + journal d'exécution** (`queue enqueue` / `status` /
   `reconcile` / `journal`) - un stockage SQLite (WAL, transactions
   immédiates pour le bail). `enqueue` est idempotent - un second appel
   avec le même `task_id` renvoie `created=False`, **jamais un second
   travail**. `lease(worker, ttl)` réclame l'entrée `queued` la plus
   ancienne ; `reconcile()` renvoie un bail expiré à `queued` (sûr à
   chaque démarrage). Un `record_result` d'un worker qui ne détient
   plus le bail est **refusé, pas accepté comme fait** - une
   interruption ne devient jamais un faux succès. Si l'empreinte de la
   base observée au moment du résultat diffère de celle de l'`enqueue`,
   le résultat est stocké `failed` / non promouvable **même sur un code
   de sortie 0**. L'événement `completed` du journal porte toujours
   `revision` + `recipe_fingerprint` ; le journal ne garde que des
   queues tronquées et `prune_journal` borne les lignes, donc le disque
   reste borné.

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
    {"name": "HYDRA-UMC-DEV-SERVER", "version": "0.0.6", "maturity": "scaffolding", "manifest_path": "../HYDRA-UMC-DEV-SERVER/hydra-umc.project.json"},
    ...
  ],
  "issues": []
}
```

Il n'y a pas d'invocation par défaut au-delà de la démo exécutée par
`run.sh`, et cette livraison n'a pas d'interface graphique - voir
[docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md) pour la surface de
commandes réelle et complète.

## 2. 🧱 ARCHITECTURE ET DÉCISIONS DE CONCEPTION

- **Aucune tâche n'a de permission de déploiement par défaut.** C'est le
  critère d'acceptation littéral de DS01, imposé par la valeur par
  défaut de la dataclass `TaskPolicy` elle-même - pas seulement énoncé
  en prose - et couvert par un test dédié pour chaque façon dont un
  document pourrait tenter de le glisser (un champ absent, mal
  orthographié, ou une valeur non booléenne).
- **Un collecteur signale un échec réel et honnête - il ne devine
  jamais.** Le fait que `scan_project_manifests()` renvoie un
  `ManifestScanIssue` pour un manifeste présent mais cassé, plutôt que
  de le laisser tomber silencieusement, est le schéma déjà établi dans
  cet écosystème (voir le propre `inventory.py` de HYDRA-UMC-OPS-AGENT) -
  réutilisé ici, pas réinventé.
- **La propriété de l'état et les relations entre projets ne sont pas à
  redéfinir par ce dépôt.** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
  et [docs/OPS_INTEGRATION.md](docs/OPS_INTEGRATION.md) documentent la
  propre table des propriétaires d'état de ce dépôt et son regroupement
  des 17 relations entre projets en
  nécessaires/optionnelles/développement uniquement.
- **stdlib uniquement pour cette livraison.** `config validate` et
  `inventory scan` n'ont besoin d'aucune dépendance tierce - une
  livraison future n'en ajoute une que lorsque son propre code en a
  véritablement besoin (un pilote de file durable pour DS05, un SDK de
  fournisseur d'IA pour DS06), jamais de manière spéculative.
- **Cette livraison ne fait que valider et découvrir - elle n'exécute
  encore rien.** Il n'existe encore aucun espace de travail, exécution
  de tâche, file d'attente, ni aucun appel réseau dans ce dépôt.

## 📂 STRUCTURE DES RÉPERTOIRES

```
HYDRA-UMC-DEV-SERVER/
├── src/hydra_umc_dev_server/
│   ├── config.py          # Schéma et validation de HostProfile/ToolchainPolicy/TaskPolicy (DS01)
│   ├── inventory.py       # Découverte réelle en lecture seule de hydra-umc.project.json (DS01)
│   ├── remote_station.py  # RemoteStationProfile : identité + accès distant + outils (DS02)
│   ├── preflight.py       # Vérification de l'hôte en lecture seule via un inspecteur injectable (DS02)
│   ├── provision.py       # Plan de provisionnement à blanc + texte de l'unité, jamais exécuté (DS02)
│   ├── migration.py       # Inventaire de migration conservatrice + plan vers des destinations distinctes, ne copie rien (DS03)
│   ├── workspace.py       # Espace de travail isolé par tâche ; refuse ../, absolu, symlink hors de l'espace (DS04)
│   ├── recipe.py          # TaskRecipe : révision fixée + commande de liste blanche (DS04)
│   ├── runner.py          # Exécuteur borné : environnement expurgé, délai, tue tout le groupe de processus (DS04)
│   ├── durable_queue.py   # File durable SQLite + baux + journal d'exécution append-only, survit à un redémarrage (DS05)
│   ├── ai_provider.py     # Seam de fournisseur d'IA interchangeable + contrat de sécurité ; fake déterministe seulement (DS06)
│   └── cli.py             # Point d'entrée des sous-commandes config / inventory / station / migrate / task / queue / provider
├── configs/
│   ├── host-profile.example.json
│   ├── toolchains.example.json
│   ├── task-policy.example.json      # allow_deploy : false, publié et testé ainsi
│   ├── remote-station.example.json   # écoute sur 127.0.0.1, publié et testé ainsi
│   ├── migration-destinations.example.json   # quatre racines prouvablement distinctes
│   └── task-recipe.example.json          # révision fixée + commande de liste blanche
├── tests/                # Tests réels de chaque module ci-dessus, incl. les configs d'exemple publiées
├── docs/
│   ├── CLI_REFERENCE.md    # Chaque sous-commande, ses options et le contrat des codes de sortie
│   ├── CONFIG_SCHEMA.md    # La forme JSON réelle des trois documents de configuration
│   ├── REMOTE_STATION.md   # Le profil de station distante DS02, la vérification préalable et le plan à blanc
│   ├── MIGRATION_FROM_PC.md  # L'inventaire, les classes et le plan de migration conservatrice DS03
│   ├── WORKSPACE_AND_RUNNER.md  # La recette DS04, l'espace de travail isolé et l'exécuteur borné
│   ├── DURABLE_QUEUE.md      # La file durable DS05, les baux et le journal d'exécution
│   ├── AI_PROVIDER.md        # Le seam de fournisseur DS06 et son contrat de sécurité (fake seulement)
│   ├── ARCHITECTURE.md     # Objectif, modes de travail, périmètre initial, disque
│   └── OPS_INTEGRATION.md  # La carte des 17 relations + table des propriétaires
├── images/                # Médias et icônes de l'application
├── tools/
│   ├── build_test.py      # Vérification de compilation non versionnante
│   └── ci_validate.py     # Validation du manifeste/CHANGELOG/docs utilisée par la CI
├── build.sh / build.bat   # venv + installation éditable + vérification + tests
├── build-test.sh / .bat   # Validation de build non mutante uniquement
├── run.sh / run.bat       # Démo réelle inventory scan + config validate (sans arguments), ou relaie une commande CLI réelle
├── bump_version.py        # Incrément « odomètre » propre à tout l'écosystème (pyproject.toml + __init__.py)
└── bump_manifest_version.py # Synchronise la version de hydra-umc.project.json avec la version native (--sync)
```

## ⚙️ GUIDE DE COMPILATION ET D'EXÉCUTION

```bash
chmod +x build.sh   # une seule fois
./build.sh          # crée .venv, pip install -e ".[dev]", vérification + tests
./run.sh                                  # démo réelle : inventory scan sur cet
                                           # espace de travail GitHub, puis config validate
./run.sh inventory scan --root DIR
./run.sh config validate configs/task-policy.example.json --kind task-policy
```

Sous Windows : `build.bat`, puis `run.bat` (même démo sans arguments) /
`run.bat inventory scan ...` / `run.bat config validate ...`.
`build-test.sh`/`.bat` effectue la même vérification de syntaxe Python
non mutante que le workflow CI du projet, sans toucher à la version du
projet ni au CHANGELOG - elle n'exécute PAS la suite de tests ; lancez
`./build.sh`/`build.bat` (ou `pytest tests/` directement) pour la suite
de tests locale complète.

**Dépannage**

- `config validate` sort avec le code `1` et `INVALID: ...` : lisez le
  message - il liste chaque champ en échec, pas seulement le premier.
  Consultez [docs/CONFIG_SCHEMA.md](docs/CONFIG_SCHEMA.md) pour la forme
  exacte attendue.
- `inventory scan` signale un problème sur un répertoire que vous
  pensiez propre : ce répertoire a un `hydra-umc.project.json` présent
  mais illisible, mal formé, ou auquel il manque un champ requis - un
  répertoire sans aucun manifeste n'est jamais signalé comme un
  problème.

## 🚀 FEUILLE DE ROUTE

Cette version apporte DS01 à DS06. Ce qui reste, dans l'ordre de
livraison :

- **DS02 - Station distante reproductible.** ✅ Livré : un profil de
  station distante validé, une vérification préalable de l'hôte en
  lecture seule, et un plan de provisionnement à blanc (sous-commandes
  `station`). Aucun hôte n'est modifié et aucune étape n'est exécutée.
- **DS03 - Migration conservatrice.** ✅ Livré : hache et classe chaque
  fichier d'un checkout source et planifie chaque classe (propre /
  modifié / non suivi / privé) vers sa propre destination distincte, avec
  un bundle pour les commits non poussés (sous-commandes `migrate`). Elle
  ne copie rien et ne touche jamais la source. Exécuter un plan approuvé
  est une livraison ultérieure.
- **DS04 - Espace de travail et exécuteur borné.** ✅ Livré : espace de
  travail isolé par tâche (deux tâches ne se percutent jamais ; chemins
  `..`, absolus et symlinks hors de l'espace refusés), une seule
  commande de liste blanche, un environnement expurgé, et un délai qui
  tue tout le groupe de processus (sous-commandes `task`). Il exécute un
  sous-processus mais ne déploie rien.
- **DS05 - File d'attente durable et résultats traçables.** ✅ Livré :
  une file SQLite avec des baux et un journal d'exécution append-only
  qui survivent à un redémarrage ; un enqueue en double n'est jamais un
  second travail, une interruption jamais un faux succès, une base qui a
  bougé bloque la promotion (sous-commandes `queue`).
- **DS06 - Fournisseur d'IA interchangeable.** ✅ Livré (moitié fake) :
  un fournisseur factice déterministe derrière un contrat de sécurité -
  timeout / malformé / quota deviennent des résultats bornés, un budget
  arrête l'étape, la suggestion est une donnée inerte qui n'accorde rien
  et ne déploie rien (`provider suggest`). Le fournisseur réel est une
  décision de l'utilisateur.
- **DS07-DS10** - incidents coordonnés avec HYDRA-UMC-OPS-AGENT, un
  premier cycle de réparation entièrement contrôlé, exploitation/
  restauration stable, et un paquet de livraison avec une évaluation
  honnête de la maturité.

Rien de DS07-DS10 n'existe encore dans ce dépôt - voir
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) pour ce que chaque
livraison inclut et exclut explicitement.

## 🔗 Projets Liés

Ce projet fait partie de l'écosystème robotique HYDRA-UMC du même auteur (JuanenRac / Electro Hobby 3D). À connaître, car une demande pourrait en réalité concerner l'un de ceux-ci plutôt que ce dépôt.

**Directement Liés**
- **[HYDRA-UMC-OPS-AGENT](https://github.com/JuanenRac/HYDRA-UMC-OPS-AGENT)** — détient le cycle de vie des incidents de maintenance (preuve, diagnostic, changement approuvé par un humain, déploiement canari, vérification) ; DEV-SERVER coordonne avec lui plutôt que de le remplacer, et n'approuve jamais ses propres tâches.
- **[HYDRA-UMC-SDK](https://github.com/JuanenRac/HYDRA-UMC-SDK)** — le contrat JSON Schema partagé contre lequel chaque échange tâche/résultat entre DEV-SERVER et le reste de l'écosystème sera validé, une fois ce contrat en place.
- **[HYDRA-UMC-UPDATER](https://github.com/JuanenRac/HYDRA-UMC-UPDATER)** — le véritable consommateur d'un candidat construit par DEV-SERVER et approuvé par OPS-AGENT ; la livraison à un nœud passe toujours par le propre chemin atomique-par-vérification d'UPDATER, jamais une copie directe depuis un exécuteur.
- **[HYDRA-UMC-OS-REBUILDER](https://github.com/JuanenRac/HYDRA-UMC-OS-REBUILDER)** — un autre membre de la famille « Ecosystem Operations » : construit une image CM5 fraîche plutôt que d'héberger du travail de développement.

**Fait Également Partie de l'Écosystème**

*Matériel et Plateforme Principaux*
- **[HYDRA-UMC](https://github.com/JuanenRac/HYDRA-UMC)** — la carte mère physique du bras robotique : hôte CM5 + STM32H745 double cœur, orchestrant jusqu'à 8 bras-outils via CAN-OTA/SPI-OTA.
- **[HYDRA-UMC-OS](https://github.com/JuanenRac/HYDRA-UMC-OS)** — couche produit Raspberry Pi OS reproductible pour la CM5 : agent en lecture seule, config/profils validés, provisionnement WiFi de premier contact.

*Backend Principal et Clients*
- **[HYDRA-UMC-SERVER](https://github.com/JuanenRac/HYDRA-UMC-SERVER)** — le véritable backend headless (REST/WebSocket) auquel chaque client de contrôle parle réellement.
- **[HYDRA-UMC-STUDIO](https://github.com/JuanenRac/HYDRA-UMC-STUDIO)** — tableau de bord de contrôle web avec visualisation 3D multi-robots en temps réel.
- **[HYDRA-UMC-SUITE](https://github.com/JuanenRac/HYDRA-UMC-SUITE)** — centre de commande de bureau (PySide6) pour plusieurs serveurs à la fois.
- **[HYDRA-UMC-ANDROID-CONTROL](https://github.com/JuanenRac/HYDRA-UMC-ANDROID-CONTROL)** — application de contrôle Android native avec connexion biométrique et un compagnon Wear OS apparié.
- **[HYDRA-UMC-IOS-CONTROL](https://github.com/JuanenRac/HYDRA-UMC-IOS-CONTROL)** — application de contrôle iOS/iPadOS (Flutter) avec synchronisation WebSocket en temps réel.
- **[HYDRA-UMC-DSI](https://github.com/JuanenRac/HYDRA-UMC-DSI)** — interface tactile native pour l'écran DSI 7" embarqué, intégrée directement sur la CM5.
- **[HYDRA-UMC-EDITOR-URDF](https://github.com/JuanenRac/HYDRA-UMC-EDITOR-URDF)** — créateur/éditeur graphique de bureau pour URDF qui pousse les modèles terminés vers le propre catalogue de STUDIO.
- **[HYDRA-UMC-BRIDGE-AMR](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-AMR)** — frontière de coordination pour les flottes AGV/AMR via un véritable éditeur MQTT VDA 5050.
- **[HYDRA-UMC-BRIDGE-CNC](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-CNC)** — coordinateur de cellule CNC haut niveau avec un accès réel à l'état/octet de contrôle GRBL.
- **[HYDRA-UMC-BRIDGE-DROIDS](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-DROIDS)** — frontière de coordination pour droïdes à pattes/humanoïdes, avec un envoyeur de commandes réel pour Boston Dynamics Spot.
- **[HYDRA-UMC-BRIDGE-LASER](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-LASER)** — coordinateur de sécurité de cellule laser lisant 3 protections GPIO réelles de clé/enceinte/interlock.
- **[HYDRA-UMC-BRIDGE-OPENPNP](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-OPENPNP)** — coordinateur sûr de haut niveau du flux de cartes pour le pick-and-place OpenPnP.
- **[HYDRA-UMC-BRIDGE-PRINTER3D](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-PRINTER3D)** — frontière de coordination sûre pour imprimantes 3D Moonraker/Klipper, avec des commandes de travail réellement contrôlées.
- **[HYDRA-UMC-BRIDGE-ROS2](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-ROS2)** — coordinateur de sécurité avec un transport ROS 2 rclpy réel, importé de façon paresseuse.
- **[HYDRA-UMC-BRIDGE-UAV](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-UAV)** — frontière de coordination pour drones équipés de caméra, avec un envoyeur de commandes MAVLink réel.

*Plateforme d'Outils URTC*
- **[URTC](https://github.com/JuanenRac/URTC)** — firmware pour la carte physique Universal Robot Tool Controller, 25+ profils d'outils sur bus CAN.
- **[URTC-FLASHER](https://github.com/JuanenRac/URTC-FLASHER)** — outil graphique de bureau pour flasher les cartes URTC, CAN-OTA plus SWD/JTAG puce complète.
- **[URTC-TESTER](https://github.com/JuanenRac/URTC-TESTER)** — outil de diagnostic CAN en direct de bureau pour cartes URTC, un panneau par profil d'outil.
- **[URTC-WEB-STUDIO](https://github.com/JuanenRac/URTC-WEB-STUDIO)** — alternative navigateur à URTC-TESTER via la Web Serial API, sans installation locale.

*Nœud de Vision IA (Hailo-8)*
- **[HYDRA-UMC-VISION-NODE](https://github.com/JuanenRac/HYDRA-UMC-VISION-NODE)** — hub d'intégration du pipeline de vision Hailo-8, avec une vérification réelle de préparation matérielle par étape.
- **[HYDRA-UMC-DETECTION-HEF](https://github.com/JuanenRac/HYDRA-UMC-DETECTION-HEF)** — registre réel de modèles compilés avec vérification de chargement sûr par architecture/somme de contrôle Hailo.
- **[HYDRA-UMC-VISION-STREAMER](https://github.com/JuanenRac/HYDRA-UMC-VISION-STREAMER)** — pipeline GStreamer réel + générateur de config MediaMTX avec une frontière d'intégration HailoRT réelle.
- **[HYDRA-UMC-VISUAL-SERVOING-API](https://github.com/JuanenRac/HYDRA-UMC-VISUAL-SERVOING-API)** — loi de correction réelle d'asservissement visuel basé sur la position, avec verrou de sécurité selon l'état de zone en amont.
- **[HYDRA-UMC-SAFETY-ZONES](https://github.com/JuanenRac/HYDRA-UMC-SAFETY-ZONES)** — vérification réelle de franchissement de zone et demande d'E-STOP, avec exigence de fraîcheur de calibration.

*Nœud Cognitif IA (Hailo-10)*
- **[HYDRA-UMC-COGNITIVE-NODE](https://github.com/JuanenRac/HYDRA-UMC-COGNITIVE-NODE)** — hub d'intégration du pipeline cognitif Hailo-10 (orchestration LLM/VLA/voix).
- **[HYDRA-UMC-VLA-ENGINE](https://github.com/JuanenRac/HYDRA-UMC-VLA-ENGINE)** — encodage/décodage réel d'action-tokens et génération de trajectoire pour un modèle Vision-Langage-Action.
- **[HYDRA-UMC-VOICE-UI](https://github.com/JuanenRac/HYDRA-UMC-VOICE-UI)** — front-end vocal réel (VAD + analyseur d'intention) avec un relais Watch borné et soumis à confirmation.
- **[HYDRA-UMC-SEMANTIC-PLANNER](https://github.com/JuanenRac/HYDRA-UMC-SEMANTIC-PLANNER)** — décomposition de tâches réelle à base de règles et récupération sémantique d'erreurs sur les codes d'erreur du MCU.
- **[HYDRA-UMC-DOCS-QA](https://github.com/JuanenRac/HYDRA-UMC-DOCS-QA)** — recherche documentaire réelle TF-IDF stdlib uniquement sur la propre documentation Markdown de cet écosystème.

*Orchestration et Essaim*
- **[HYDRA-UMC-ORCHESTRATOR](https://github.com/JuanenRac/HYDRA-UMC-ORCHESTRATOR)** — hub d'intégration avec un contrat réel de rapport de santé gRPC/Protobuf et une machine à états de mission.
- **[HYDRA-UMC-JOB-DISPATCHER](https://github.com/JuanenRac/HYDRA-UMC-JOB-DISPATCHER)** — file de travaux réelle basée sur la priorité avec déduplication, via une API HTTP réelle.
- **[HYDRA-UMC-NODE-HEALING](https://github.com/JuanenRac/HYDRA-UMC-NODE-HEALING)** — surveillant réel de santé de flotte basé sur gRPC, avec son propre retry/backoff et détection d'incohérence d'identité.
- **[HYDRA-UMC-PATH-PLANNER-3D](https://github.com/JuanenRac/HYDRA-UMC-PATH-PLANNER-3D)** — planificateur de trajectoire 3D réel basé sur RRT avec validation réelle de collision obstacle/espace de travail.
- **[HYDRA-UMC-SWARM-SYNC](https://github.com/JuanenRac/HYDRA-UMC-SWARM-SYNC)** — synchronisation d'état CRDT LWW-Element-Map réelle, testée par propriétés pour la convergence multi-cellules.

*Jumeau Numérique et Simulation*
- **[HYDRA-UMC-TWIN](https://github.com/JuanenRac/HYDRA-UMC-TWIN)** — hub d'intégration du moteur de jumeau numérique, avec un contrat réel de synchronisation de compatibilité de versions.
- **[HYDRA-UMC-HIL-BRIDGE](https://github.com/JuanenRac/HYDRA-UMC-HIL-BRIDGE)** — interlock de sécurité hardware-in-the-loop réel acheminant des commandes entre simulation et matériel réel.
- **[HYDRA-UMC-PHYSICS-REPLICA](https://github.com/JuanenRac/HYDRA-UMC-PHYSICS-REPLICA)** — cinématique directe réelle et validation des limites d'articulation sur un sous-ensemble URDF réel.
- **[HYDRA-UMC-SYNTHETIC-DATA-GEN](https://github.com/JuanenRac/HYDRA-UMC-SYNTHETIC-DATA-GEN)** — générateur procédural réel de scènes 2D avec export d'annotations YOLO/COCO.

*Données et Analytique*
- **[HYDRA-UMC-DATALAKE](https://github.com/JuanenRac/HYDRA-UMC-DATALAKE)** — entrepôt réel de séries temporelles avec sqlite3 doté d'une API HTTP réelle d'ingestion/requête.
- **[HYDRA-UMC-ANOMALY-DETECTOR](https://github.com/JuanenRac/HYDRA-UMC-ANOMALY-DETECTOR)** — détecteur d'anomalies réel par FFT + ligne de base statistique, avec surveillance de dérive.
- **[HYDRA-UMC-PRODUCTION-REPORTS](https://github.com/JuanenRac/HYDRA-UMC-PRODUCTION-REPORTS)** — calcul réel d'OEE/disponibilité sur l'historique de DATALAKE, avec export CSV reproductible.
- **[HYDRA-UMC-TELEMETRY-COLLECTOR](https://github.com/JuanenRac/HYDRA-UMC-TELEMETRY-COLLECTOR)** — pipeline réel d'ingestion CAN/WebSocket vers DATALAKE, avec déduplication de séquence.

*Passerelle Industrielle*
- **[HYDRA-UMC-GATEWAY-INDUSTRIAL](https://github.com/JuanenRac/HYDRA-UMC-GATEWAY-INDUSTRIAL)** — hub d'intégration relayant vers des protocoles industriels, avec une véritable couche de liste blanche de commandes/backpressure.
- **[HYDRA-UMC-OPCUA-SERVER](https://github.com/JuanenRac/HYDRA-UMC-OPCUA-SERVER)** — espace d'adresses OPC-UA réel, vérifié avec une session client de protocole binaire réelle.
- **[HYDRA-UMC-MQTT-BROKER](https://github.com/JuanenRac/HYDRA-UMC-MQTT-BROKER)** — courtier MQTT réel avec authentification optionnelle par client et ACL de topics.
- **[HYDRA-UMC-MTCONNECT-ADAPTER](https://github.com/JuanenRac/HYDRA-UMC-MTCONNECT-ADAPTER)** — points de terminaison XML réels `/probe` et `/current` de MTConnect avec sortie en mode dégradé.

*Outils Complémentaires*
- **[HYDRA-UMC-DASHBOARD-AI](https://github.com/JuanenRac/HYDRA-UMC-DASHBOARD-AI)** — panneaux de Résumés Intelligents et de Mise en Évidence d'Anomalies sur DATALAKE/ANOMALY-DETECTOR, avec un repli statistique honnête.
- **[HYDRA-UMC-TOOL-CLI](https://github.com/JuanenRac/HYDRA-UMC-TOOL-CLI)** — CLI de flotte avec un contrat réel et stable de codes de sortie, un véritable client en direct de la propre API de HYDRA-UMC-SERVER.
- **[HYDRA-UMC-WATCH](https://github.com/JuanenRac/HYDRA-UMC-WATCH)** — application compagnon WearOS avec alertes haptiques réelles et un relais vocal vers le téléphone apparié.
- **[HYDRA-UMC-CONNECTOR-HUB](https://github.com/JuanenRac/HYDRA-UMC-CONNECTOR-HUB)** — catalogue de capacités d'adaptateurs externes, GET-only par conception.
- **[URTC-SMART-RACK](https://github.com/JuanenRac/URTC-SMART-RACK)** — firmware pour un rack de montage de cartes avec décodage réel d'ID d'outil et logique de préchauffage Smart Idle.
- **[URTC-VISION-TOOL](https://github.com/JuanenRac/URTC-VISION-TOOL)** — firmware plus un compagnon de vision Python réel pour une tête d'inspection thermique/RGB.

---

## 📚 Documentation et Communauté

- **[docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md)** — chaque sous-commande, ses options, et le contrat des codes de sortie.
- **[docs/CONFIG_SCHEMA.md](docs/CONFIG_SCHEMA.md)** — la forme JSON réelle de `HostProfile`/`ToolchainPolicy`/`TaskPolicy`.
- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — objectif, les deux modes de travail, périmètre initial, et organisation du disque.
- **[docs/OPS_INTEGRATION.md](docs/OPS_INTEGRATION.md)** — la carte complète des 17 relations et la table des propriétaires d'état.
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — pile technique et lignes directrices de codage pour une pull request.
- **[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)** — les normes de comportement attendues dans cette communauté.
- **[SECURITY.md](SECURITY.md)** — comment signaler une vulnérabilité, et les axes réels de sécurité de ce projet.
- **[SUPPORT.md](SUPPORT.md)** — où poser des questions et signaler des bugs.

## 👤 AUTEUR
**JuanenRac** (Electro Hobby 3D)
📧 electrohobby3d@gmail.com
📺 [youtube.com/@electrohobby3d](https://youtube.com/@electrohobby3d)

## 📜 LICENCE

GPL-3.0 (logiciel) / CC BY-SA 4.0 (documentation) - voir [LICENSE.md](LICENSE.md).
