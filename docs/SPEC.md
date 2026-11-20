> Brief de départ du projet, pas l'état actuel : recettes, cache HTTP, branch-and-bound et
> self-transfer n'existent pas. Le fonctionnement réel est décrit dans le README.

# Prompt Claude Code — « Cheap Hops » : moteur local de recherche de vols pas chers

> Tu es un AI engineer / system designer senior. Tu construis avec moi une app **locale** (pas de prod, pas de cloud hormis AWS Bedrock) qui trouve les voyages en avion les moins chers au départ de Vilnius, Kaunas et Riga, sans destination fixée. Lis tout ce document avant d'écrire du code, puis travaille **phase par phase** (section 14) en t'arrêtant à la fin de chaque phase pour que je valide.

---

## 1. Contexte & objectif

- Je suis étudiant en Erasmus à Vilnius. Je voyage léger : **un sac à dos qui passe sous le siège** → on compare uniquement les tarifs de base (aucun bagage, aucune option).
- Je ne vise **aucune destination** : l'app doit me sortir une liste classée des voyages les moins chers, toutes destinations confondues.
- L'esprit est « be a traveler, not a tourist » : **escales en self-transfer, open-jaw, bus entre villes d'origine** sont acceptés si ça fait baisser le prix.
- Mode **à la demande** : je lance une recherche, l'app scrape, combine, classe. Pas de crawler permanent.
- Budget LLM très serré : **~50 € de crédit Bedrock** au total. L'archi doit être pensée pour que le LLM soit rarement appelé.

## 2. Contraintes non négociables

1. **Le LLM n'est jamais dans la boucle chaude.** Le scraping et la combinaison sont déterministes. Le LLM sert uniquement à créer, réparer et valider des recettes, à consolider la mémoire et (optionnellement) à parser une requête en langage naturel.
2. **Ne jamais coder un endpoint « de mémoire ».** Les endpoints des compagnies changent. Ils doivent être découverts par reconnaissance réseau (outil `recon`, section 8) et capturés en fixtures.
3. **Scraping respectueux** : usage perso, faible volume, rate limit par domaine, jitter, cache. Pas de connexion à un compte. Pas de service de résolution de CAPTCHA : si un CAPTCHA apparaît, la source est marquée `blocked` avec backoff, point.
4. **Plafond de coût LLM dur** (section 11) : quand il est atteint, l'app continue en mode dégradé sans LLM.
5. Tout code généré par un LLM passe par la sandbox + les gardes + le juge (section 10) avant d'être utilisé.
6. Tout est **paramétrable** via un fichier de config + l'UI. Aucune valeur métier en dur dans le code. Les réglages faits dans l'UI vont dans un fichier d'overrides séparé (`config.local.yaml`, non versionné), **jamais** dans `config.yaml`, pour préserver ses commentaires `# à ajuster`.

## 3. Stack

- **Backend** : Python 3.12, gestion de projet avec `uv`. FastAPI + asyncio. SQLite (avec FTS5) via SQLAlchemy 2 ou `sqlite3` + migrations simples. Pydantic v2 pour tous les schémas.
- **Fetch** : `httpx`, `curl_cffi` (TLS impersonation), **Scrapling** (`Fetcher`, `StealthyFetcher`, `DynamicFetcher` / sélecteurs adaptatifs — lis sa doc actuelle avant de l'utiliser, n'invente pas son API), Playwright.
- **LLM** : AWS Bedrock via `boto3`, **Converse API** avec tool use, région **`eu-north-1`**. Ne code pas les model IDs en dur : écris un script `scripts/bedrock_check.py` qui liste les modèles / inference profiles disponibles sur mon compte dans cette région (probablement des profils `eu.*`), et mets les IDs choisis dans la config. Rôles : un modèle « rapide » (Claude Haiku) et un modèle « fort » (Claude Sonnet). Utilise le prompt caching (`cachePoint`) si supporté pour le modèle/la région, sinon dégrade proprement. Attention : un préfixe trop court (~1024–2048 tokens selon le modèle) n'est pas mis en cache.
- **Frontend** : Vite + React + TypeScript (Tailwind ok). Progression live via SSE.
- **Qualité** : `pytest`, `ruff`, typage strict raisonnable. Commits conventionnels, un commit par étape cohérente.
- **Environnement** : Arch Linux. Attention, `playwright install --with-deps` ne gère pas Arch : installe les navigateurs sans `--with-deps` et documente les dépendances système éventuelles dans le README. Même vigilance pour le navigateur utilisé par `StealthyFetcher`.

## 3b. Outillage de l'agent (plugins & skills installés)

Trois outils sont installés dans cette session. Vérifie au démarrage qu'ils sont bien chargés (`/plugin`, `/context`). S'il en manque un, dis-le-moi au lieu de continuer sans.

- **pstack** (plugin, port Claude Code du skill stack de poteto) : c'est lui qui **route le workflow** (planification, implémentation, vérification, debug). Pour chaque phase, laisse son mode de routage choisir le workflow adapté plutôt que d'improviser.
- **ponytail** (plugin minimaliste) : applique sa logique « le meilleur code est celui qu'on n'écrit pas » à **l'implémentation**, niveau `full` par défaut. Chaque raccourci reste marqué d'un commentaire `shortcut: <limite>, <quand upgrader>` (format actuel du plugin ; `/ponytail-debt` lit aussi l'ancien `ponytail:`).
- **thermo-nuclear-code-quality-review** (skill fourni par pstack : `pstack:thermo-nuclear-code-quality-review`) : c'est la **porte de qualité de fin de phase** (maintenabilité, règle des 1000 lignes, spaghetti de conditions, wrappers inutiles).

**Règles de cohabitation :**
1. **Ponytail réduit le code, pas le périmètre.** L'architecture de ce document est le scope voulu. Ponytail peut simplifier *comment* on implémente un composant, mais ne supprime pas :
   - la séparation des plans de données / de contrôle,
   - la fetch ladder,
   - les gardes de sécurité de la section 10.3 (AST, allowlist réseau, sandbox),
   - le plafond de coût LLM,
   - les tests de contrat.

   Si ponytail juge un composant superflu, signale-le-moi avec un argument au lieu de le couper en silence.
2. En cas de conflit entre une consigne de pstack et une consigne de ponytail sur la façon d'écrire du code, ponytail l'emporte. Sur le déroulé du travail (plan, vérification, ordre des étapes), pstack l'emporte.
3. La review thermo-nuclear est **bloquante** : une phase n'est pas terminée tant que ses findings bloquants ne sont pas corrigés ou explicitement acceptés par moi.

## 4. Modèle métier

### 4.1 Voyage
Un voyage = un **aller** (origine → destination, 0 ou 1 escale) + un **retour** (destination → origine, 0 ou 1 escale), éventuellement complété par des **trajets sol**.

### 4.2 Paramètres de recherche (défauts entre parenthèses)
| Paramètre | Défaut | Notes |
|---|---|---|
| `origins` | `VNO, KUN, RIX` | Multi-sélection, éditable dans l'UI |
| `date_from` / `date_to` | aujourd'hui+1 → +8 semaines | Fenêtre des dates de départ |
| `max_nights` | **3** | Nuits hors de chez moi = nb de minuits locaux franchis entre le départ de l'aller et l'arrivée du retour |
| `min_on_site_hours` | **24** | Entre l'arrivée à destination et le départ du retour |
| `return_deadline` | désactivé | Optionnel, ex. « retour avant 12:00 » ; actif dans le preset week-end |
| `blackout` | vide | Liste de dates/créneaux où je ne suis pas dispo (cours, exams) |
| `max_total_price` | aucun | Filtre |
| `allow_self_transfer` | oui | |
| `max_stops_per_direction` | **1** | |
| `min_connection_hours` | **3** | Self-transfer = aucune protection, donc marge large |
| `max_layover_hours` | 18 | Nuit en aéroport acceptée |
| `allow_open_jaw` | oui | Partir d'une origine, rentrer à une autre ; arriver/repartir d'aéroports différents d'une même ville |
| `top_k` | 30 | Nombre de résultats affichés |

**Presets UI** : « Week-end » (départ ven/sam, retour dim/lun, `return_deadline` lundi 12:00), « N'importe quand » (défauts ci-dessus).

### 4.3 Trajets sol
Fichier de config `ground.yaml` éditable : arêtes entre villes d'origine (VNO↔KUN, VNO↔RIX, KUN↔RIX) avec durée, coût estimé et marge (temps pour rejoindre l'aéroport). Valeurs initiales = estimations grossières marquées `# à ajuster`. Côté destination : regroupement d'aéroports par ville/métropole (ex. BGY/MXP/LIN). OurAirports ne fournit pas de métropoles (le champ `municipality` de BGY vaut « Orio al Serio ») : on regroupe donc **par rayon** autour des grands aéroports, avec des **overrides manuels** dans `ground.yaml`, et un coût/temps de transfert forfaitaire paramétrable.

### 4.4 Score
`score = prix_total_EUR + coûts_sol + pénalités` ; pénalités paramétrables (ex. nuit en aéroport, retour après deadline souple). Prix normalisés en EUR (taux BCE mis en cache).

## 5. Architecture

Deux plans séparés :

- **Plan de données (déterministe, gratuit)** : `Scheduler` (rate limit par domaine, cache, budget de requêtes) → `Recipes` (adapters versionnés) → `FetchLadder` → `Store` (SQLite) → `Combinator`.
- **Plan de contrôle (LLM, rare)** : `Pathfinder` (crée des recettes), `Medic` (répare), `Judge` (valide), `Planner` (alloue le budget de requêtes, surtout algorithmique), `Consolidator` (transforme les épisodes en leçons). Tous passent par un `ContextBuilder` commun.

Les agents ne partagent **jamais** leurs transcripts. Ils se transmettent des handoffs JSON compacts : `{goal, attempted, result, artifacts}`.

## 6. Recettes (l'unité qui évolue)

Une recette = un module Python + un manifeste YAML, dans `recipes/<source>/v<N>/` :

```
manifest.yaml     # source, version, capabilities, domaines autorisés, rung préféré, rate limit, statut
recipe.py         # implémente l'interface ci-dessous
fixtures/         # réponses réelles capturées (JSON/HTML) + résultat attendu
test_recipe.py    # tests de contrat sur fixtures
```

Interface (une source n'implémente que ce qu'elle peut). Un Protocol par capacité dans `cheaphops/recipes/base.py`. Le moteur sélectionne les sources par `manifest.capabilities`, jamais par `hasattr` à l'appel. Les signatures sont garanties par les tests de contrat, pas par le Protocol :

```python
class Recipe(Protocol):
    async def routes(self, ctx: Ctx, origin: str) -> list[str]: ...                         # destinations desservies
    async def calendar(self, ctx: Ctx, o: str, d: str, month: date) -> list[DayFare]: ...    # prix min par jour
    async def day_flights(self, ctx: Ctx, o: str, d: str, day: date) -> list[Flight]: ...    # vols détaillés avec horaires
    def booking_url(self, flight: Flight) -> str | None: ...
```

Règles :
- Une recette n'a **pas** accès au réseau directement. Elle utilise `ctx.http`, qui applique l'allowlist de domaines du manifeste, le rate limit et le rung de la fetch ladder.
- Imports limités à une allowlist (vérifiée par analyse AST).
- Les **skills** réutilisables (bootstrap de cookies, parsing de dates, retry avec jitter, extraction JSON depuis `<script>`…) vivent dans `skills/` et sont importables par les recettes. Les agents doivent les réutiliser plutôt que régénérer.
- Statuts : `draft` → `quarantined` | `active` → `deprecated`. Rollback automatique à la dernière version `active` si la nouvelle échoue en prod.

**Sources v0** : Ryanair, Wizz Air (recettes écrites à la main en phase 1). Wizz : **tarif normal** par défaut ; le prix Wizz Discount Club n'est qu'une option d'affichage, jamais utilisé pour le score. Wizz protège son endpoint d'horaires (`search`) par Kasada : la recette ne fournit que `routes` et `calendar` (prix au jour). Un segment Wizz sans horaire n'entre que dans un **aller-retour direct**, jamais dans une combinaison self-transfer, avec le badge « horaires et aéroport de départ à vérifier » (Wizz mélange VNO et KUN dans ses prix). **Phase 4** : airBaltic ajouté par le Pathfinder comme test d'acceptation. Plus tard, éventuellement un agrégateur spécialisé low-cost comme source de recoupement.

## 7. Fetch ladder

Rungs, du moins cher au plus cher :
1. `httpx`
2. `curl_cffi` avec impersonation navigateur
3. Scrapling `Fetcher` / `StealthyFetcher`
4. Navigateur complet (Playwright ou Scrapling `DynamicFetcher`)

- Chaque source démarre au rung qui a le mieux marché. Stats par `(source, rung)` dans `fetch_stats` (succès, latence, dernier échec). Choix du rung par Thompson sampling (Beta) en phase 5, heuristique simple avant.
- Classification **déterministe** des échecs : `403/anti-bot` → monter d'un rung ; `429` → backoff exponentiel ; `schema_mismatch` / `empty_result` / `price_anomaly` → déclencher le Medic.
- Pour l'HTML, utiliser les sélecteurs adaptatifs de Scrapling : c'est une réparation gratuite avant d'impliquer le LLM.
- Les rungs 2 et 3 se recouvrent (Scrapling `Fetcher` s'appuie sur curl_cffi) : à trancher en phase 1, sans supprimer de rung en silence.
- **Cache HTTP** : la clé inclut méthode, URL, paramètres, corps **et les headers qui changent la réponse** (devise, langue : liste configurable).

## 8. Outil `recon` (déterministe, construit tôt)

`python -m cheaphops.recon <url> --goal "..."` :
- ouvre la page dans un navigateur piloté, exécute un scénario minimal (ou me laisse naviguer en mode headed), capture le trafic (HAR) ;
- **filtre** : ne garde que les réponses JSON (ou HTML avec JSON embarqué) contenant à la fois des codes IATA et des montants plausibles ;
- produit pour chaque candidate : URL template, méthode, headers significatifs, paramètres, **squelette JSON** (types inférés + un exemple par tableau) ;
- capture aussi un **prix visible sur la page rendue** avec le vol associé (vérité terrain pour le juge) ;
- sauvegarde le tout en fixtures.

Je l'utilise à la main en phase 1. Le Pathfinder l'utilise en phase 4.

## 9. Algorithme de recherche

**Phase Explore (large, pas cher)**
1. `routes()` pour chaque origine → destinations directes.
2. `calendar()` par route et par mois couvrant la fenêtre, aller et retour. Cache 6 h.
3. Second niveau (si `allow_self_transfer`) : depuis les hubs atteignables, `routes()` + `calendar()` vers des destinations finales. Le `Planner` limite ce second niveau via un budget de requêtes, en priorisant les hubs à bas prix et les routes historiquement bon marché.

Résultat : une grille `(route, date) → prix min` à la granularité **jour** (pas d'horaires).

**Génération de candidats** : combinaisons aller/retour respectant les contraintes **au niveau date** (`max_nights`, `blackout`, fenêtre, open-jaw, sol). Le prix de la grille sert de **borne basse**, mais elle n'est pas garantie (les prix calendrier sont mis en cache côté compagnie, le prix live peut être inférieur). On applique donc un facteur de marge configurable : `borne = prix_grille × bound_slack` (défaut **0.8**). Branch-and-bound : on coupe une branche dès que `borne(segments) + coûts_sol > k-ième meilleur score courant`. Le nombre de branches coupées est journalisé à chaque run.

**Phase Verify (précis, ciblé)** : pour les candidats de tête, `day_flights()` sur les segments concernés → horaires réels. On recombine ensuite dans un **graphe temporel** (nœuds = `(aéroport, datetime)`, arêtes = vols + sol) avec les contraintes horaires (`min_on_site_hours`, `min_connection_hours`, `max_layover_hours`, `return_deadline`). On itère Verify tant que le top-K n'est pas stable et que le budget de requêtes le permet. Cache Verify court (15 min).

**Sortie** : top-K voyages avec, pour chacun, segments détaillés (vol, horaires, prix, source, lien de réservation), trajets sol, temps sur place, nuits, score, et un indicateur de fraîcheur des prix.

## 10. Agents

Tous les appels LLM passent par `llm/client.py` (Converse API, tool use, comptabilité des coûts) et `context/builder.py`.

### 10.1 Pathfinder (création)
Entrée : URL + objectif (ex. « `calendar` pour cette compagnie »). Il lance `recon`, reçoit les candidates **compressées**, choisit l'endpoint et génère `recipe.py` + manifeste + tests à partir des fixtures, en réutilisant les skills. Il exécute ensuite les tests en sandbox. Modèle fort. Maximum 3 itérations, puis abandon avec rapport.

### 10.2 Medic (réparation)
Déclenché par les health checks du plan de données. Le diagnostic est d'abord **déterministe** (section 7) ; le LLM n'intervient que pour `schema_mismatch` ou une dérive de paramètres. Il reçoit : leçons de la source, squelette de la dernière réponse valide, squelette de la réponse actuelle, **diff** des deux, épisodes similaires. Il produit un patch → nouvelle version `draft` → gardes → juge. Modèle rapide d'abord, modèle fort si échec.

### 10.3 Judge (LLM-as-judge, promotion des recettes)
Il passe **après** des gardes déterministes, jamais seul :
1. Analyse statique : allowlist d'imports via l'AST, aucun accès hors `ctx.http`, pas d'`eval`/`exec`, pas d'écriture disque. C'est un **filet**, pas une frontière de sécurité (l'AST se contourne) : la vraie frontière est la sandbox `bwrap` (phase 3).
2. Tests de contrat sur fixtures + validation pydantic.
3. Smoke test live (1 à 2 requêtes).
4. Juge LLM, avec un **contexte séparé de l'auteur** (il ne voit pas le raisonnement du générateur). Il compare la sortie de la recette à la **vérité terrain** capturée par `recon` (prix visible sur la page rendue pour le même vol), puis vérifie la cohérence des données (dates, devises, codes IATA, ordres de grandeur).
5. Sortie JSON stricte : `{"verdict": "pass"|"fail", "confidence": 0..1, "reasons": [...]}`.

Juge par défaut = modèle rapide ; escalade vers le modèle fort si `confidence < seuil`. `pass` → `active` ; `fail` → `quarantined`. Après 2 refus consécutifs sur une source, elle est signalée dans l'UI pour validation manuelle.

### 10.4 Planner
Surtout algorithmique : il répartit le budget de requêtes Explore/Verify entre routes et dates (heuristique en phase 1, bandit sur l'historique de prix en phase 5). Le LLM (modèle rapide) sert seulement à traduire une requête en langage naturel en paramètres de la section 4.2. Ce point est optionnel.

### 10.5 Consolidator
Tourne en fin de run, **un seul appel par lot** (modèle rapide). Il transforme les épisodes au résultat connu en leçons (section 12).

## 11. Budget LLM

- Table `llm_calls` : modèle, rôle de l'agent, tokens in/out/cache read/cache write, coût calculé (tarifs dans la config), run_id.
- Plafonds dans la config, en **USD** : `per_run_usd` (défaut 0.50), `pathfinder_run_usd` (plafond séparé et plus haut pour un run du Pathfinder, défaut 2.00 `# à ajuster`) et `total_usd` (défaut 40, pour garder une marge sur les 50 €). Au plafond, le LLM est coupé, l'app continue sans, et l'UI l'indique.
- Préfixes de prompt **stables** pour maximiser le cache.
- Panneau UI : dépense du run, cumul, reste.

## 12. Mémoire & context engineering

Principe : **le LLM ne voit jamais rien de brut**, et chaque appel reçoit un contexte frais, assemblé sous budget.

### 12.1 Compresseurs (déterministes, `context/compress.py`)
- **HAR** : filtre IATA + montants (section 8).
- **JSON** : squelette (types + 1 exemple par tableau, chaînes tronquées).
- **HTML** : réduit à l'arbre d'accessibilité / texte structuré.
- **Logs** : empreinte d'erreur (normalisation des nombres, IDs, timestamps, URLs paramétrées), dédup + compteurs. Ex. : `47 × 403 GET /api/x/{id}`.
- **Diff** : diff structurel entre deux squelettes JSON.

### 12.2 Trois mémoires
- **Épisodique** (`episodes`) : une ligne par tentative (source, version de recette, rung, empreinte d'erreur, action, résultat, coût, timestamp). Jamais injectée en bloc : on récupère top-k par empreinte proche + FTS5. Pas de base vectorielle ni d'embeddings payants.
- **Leçons** (`lessons`) : règles courtes, avec un `scope` (`global` | `source:<x>` | `rung:<n>`), `kind` (`rule` | `anti_pattern`), `evidence_count`, `confidence`, `last_verified`, `expires_at`, `recipe_version`. Export lisible et éditable à la main dans `lessons/<scope>.md`, versionné dans git.
- **Procédurale** : recettes + skills (section 6).

### 12.3 Politique d'écriture
- Seul le Consolidator écrit des leçons, et uniquement à partir d'épisodes au **résultat connu**.
- Un fix validé par le juge donne une `rule`. Un échec répété (≥2) donne un `anti_pattern`, injecté comme « déjà essayé, ne marche pas ».
- Une nouvelle leçon qui en contredit une existante baisse la confiance de l'ancienne ; sous un seuil, elle est archivée.
- Oubli : expiration (TTL) ; quand une recette change de version, ses leçons passent en « à revérifier ».

### 12.4 ContextBuilder
Budget de tokens **par section**, assemblé du plus stable au plus volatil :
1. System prompt de l'agent + définitions d'outils + leçons `global` → **préfixe caché**
2. Leçons de la source (top-k par confiance × fraîcheur)
3. Squelette de la dernière réponse valide
4. Diff / observations compressées de l'échec
5. 2-3 épisodes similaires
6. La tâche

Chaque section a un budget max ; si elle déborde, on tronque par priorité et le builder journalise ce qui a été coupé. Écris des tests unitaires sur le builder (budgets respectés, ordre stable, préfixe identique entre deux appels du même agent).

## 13. UI (Vite + React)

- **Recherche** : formulaire des paramètres 4.2 + presets, bouton « Lancer ».
- **Progression live** (SSE) : par source et par phase (Explore / Verify), requêtes faites, cache hits, erreurs, rung courant.
- **Résultats** : tableau trié par score (destination, prix total, dates, nuits, temps sur place, nb de segments, badges self-transfer / open-jaw / sol). Une ligne dépliée montre l'itinéraire détaillé avec les liens de réservation par segment et l'âge des prix.
- **Santé des sources** : statut, version active, rung préféré, taux de succès.
- **Agents** : recettes en quarantaine (diff + verdict du juge, boutons approuver/rejeter), leçons (lecture/édition), dépense LLM.

## 14. Phases de livraison

> **Périmètre (arbitrage du 2026-10-14)** : le projet s'arrête après la phase 2. Les phases 3 à 5 sont **en pause** ; leur description reste ici pour une reprise éventuelle. À la place des agents LLM, deux skills projet décrivent les procédures du Medic et du Pathfinder, exécutées par Claude Code avec l'utilisateur comme juge : `.claude/skills/repair-recipe/` et `.claude/skills/add-source/`.

**Fin de chaque phase, dans cet ordre :**
1. Tests + lint verts.
2. `/ponytail-review` sur le diff de la phase, puis application des suppressions pertinentes.
3. Review **thermo-nuclear-code-quality-review** sur le diff de la phase. Si le skill n'est pas invocable par toi (`disable-model-invocation`), demande-moi de la lancer.
4. Correction des findings bloquants.
5. `/ponytail-debt` : ledger des raccourcis à ajouter dans `DEBT.md`.
6. Arrêt avec récapitulatif, commandes pour tester et points ouverts.

**Phase 0 — Fondations**
Squelette du repo, config (`config.yaml`, `ground.yaml`), modèles pydantic, schéma SQLite + migrations, `Ctx` / `ctx.http` avec rate limit, allowlist et cache, logging structuré, `scripts/bedrock_check.py`.
*Acceptation* : `uv run pytest` passe ; `bedrock_check` liste les modèles dispo en `eu-north-1`.

**Phase 1 — Moteur sans LLM**
Outil `recon`, fetch ladder (rungs 1-4, choix heuristique), recettes Ryanair + Wizz écrites à la main à partir de captures `recon`, avec fixtures et tests. Explore, candidats, branch-and-bound, Verify, graphe temporel, scoring. CLI `cheaphops search ...` qui affiche le top-K.
*Acceptation* : une recherche « N'importe quand » sur 4 semaines depuis VNO/KUN/RIX renvoie des voyages valides (contraintes vérifiées par des tests), dont au moins un open-jaw ou self-transfer si les données le permettent ; les tests du combinateur couvrent `max_nights`, `min_on_site`, `min_connection`, `return_deadline`, `blackout`.

**Phase 2 — API + UI**
FastAPI (lancer une recherche, SSE de progression, résultats, santé des sources), front React complet hors onglet Agents.
*Acceptation* : je lance une recherche depuis l'UI et vois la progression puis les résultats.

**Phase 3 — Infra LLM + Medic** *(en pause)*
Client Bedrock + ledger + plafonds, compresseurs, tables `episodes`/`lessons`, ContextBuilder, Medic, gardes déterministes + Judge, sandbox `bwrap` (présent sur la machine) = vraie frontière : subprocess avec timeout, env sans credentials AWS, **`$HOME` masqué** (`~/.aws/credentials` est un fichier), **écriture uniquement dans un tmp**, **réseau limité à l'allowlist** du manifeste (mécanisme à décider en phase 3).
*Acceptation* : je casse volontairement une fixture/un parser Ryanair → le Medic diagnostique, patche, le juge valide, la nouvelle version passe `active`, et l'épisode est journalisé. Le coût du run est affiché.

**Phase 4 — Pathfinder** *(en pause)*
Pathfinder branché sur `recon`, génération de recette + tests, promotion via le juge.
*Acceptation* : `cheaphops pathfind https://www.airbaltic.com --goal calendar` produit une recette airBaltic `active` (ou un rapport d'échec clair), sans code écrit par moi.

**Phase 5 — Évolution** *(en pause)*
Consolidator + export `lessons/*.md`, Thompson sampling sur les rungs, Planner bandit basé sur l'historique de prix, onglet Agents de l'UI.
*Acceptation* : après plusieurs runs, les leçons apparaissent ; les stats `(source, rung)` sont **persistées et utilisées pour l'ordre d'essai** des rungs (Thompson simple). Pas de critère de convergence : en mode à la demande, le volume est trop faible pour la mesurer.

## 15. Structure de repo suggérée

```
cheaphops/
  core/        # modèles, config, db, ctx
  fetch/       # ladder, http client, cache, rate limit
  recon/
  recipes/     # <source>/v<N>/
  skills/
  search/      # explore, candidates, verify, graph, scoring, planner
  llm/         # client bedrock, ledger, prompts/
  agents/      # pathfinder, medic, judge, consolidator
  context/     # compress, builder
  memory/      # episodes, lessons, export
  api/
web/           # Vite + React
lessons/
tests/
```

## 16. Façon de travailler

- Commence chaque phase par un plan court (fichiers, interfaces, tests), puis implémente.
- Si une hypothèse de ce document se révèle fausse (ex. une compagnie n'a pas d'endpoint calendrier), **dis-le** et propose une alternative au lieu de contourner en silence.
- Pas de dépendance lourde non justifiée.
- Toute valeur estimée (coûts sol, tarifs LLM, seuils) est marquée `# à ajuster` dans la config.
- Écris un README tenu à jour : installation sur Arch, configuration AWS (profil, région `eu-north-1`), commandes, architecture en 1 page.
