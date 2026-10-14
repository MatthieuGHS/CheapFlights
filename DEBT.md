# Dette (raccourcis assumés)

Généré par `/ponytail-debt` : un raccourci = un commentaire `shortcut:` dans le code.
À régénérer en fin de phase.

## Marqueurs `shortcut:` (ledger `/ponytail-debt`, fin de 1a)

- `cheaphops/fetch/http.py:233`. SQLite synchrone dans l'event loop. Plafond : un utilisateur.
  Déclencheur : la latence SSE de la phase 2 en souffre, alors `asyncio.to_thread`.
- `cheaphops/core/models.py:17`. Le regex `Domain` accepte un suffixe public (`co.uk`).
  Déclencheur : phase 4 (Pathfinder), Public Suffix List via `tldextract`, pas de liste maison.
- `cheaphops/recipes/ryanair/v1/manifest.yaml:6`. `home_url` à date fixe (2026-11-13).
  Déclencheur : avant cette date, vérifier en live que la page pose encore les cookies, sinon
  générer l'URL avec une date future.
- `cheaphops/fetch/ladder.py:39`. Heuristique déterministe de choix du rung.
  Déclencheur : phase 5, Thompson sampling (Beta).

4 marqueurs, 0 sans déclencheur. Le marqueur « httpx seul (rung 1) » de la phase 0 est soldé.

## Phase 1a, soldé

Rate limit par domaine enregistrable (fait avant toute requête réelle), fraîcheur
`explore|verify|none`, headers en paires.

## Phase 1a, review thermo-nuclear (non bloquants reportés)

- N5 `cheaphops/fetch/http.py` `_request` : la politique (monter, attendre, bloquer, échouer) est
  mêlée aux écritures SQLite. Extraire `ladder.next_step(outcome, rung)` pure, testée par table,
  avant que Thompson sampling (phase 5) ou Retry-After n'ajoutent des branches.
- N6 `FetchFailed.outcome` transporte un `Outcome` ou les chaînes `transport` / `too many
  redirects`. Ajouter ces cas à `Outcome` quand le moteur de recherche les distinguera.
- N7 `LoadedRecipe.recipe: Any` efface les Protocols de `recipes/base.py`. Typer par capacité
  quand le moteur appelle les recettes.
- Ryanair : aucun endpoint calendrier découvert en headless ; `calendar()` agrège la
  disponibilité (≈ 6 appels par route et par mois). Retenter un recon headed du fare finder.
- Ryanair : `FlexDays` = 3 n'a été testé que sans `client-version` (409). Le retester pourrait
  passer à 7 jours par appel.

## Phase 1b

- Wizz : piste « timetable » à explorer plus tard (recon headed de la page horaires de Wizz)
  pour trouver un endpoint d'horaires moins protégé que `search` (défi Kasada en automatique).
- Wizz : le test du rung 4 sous Xvfb n'a pas été fait (paquet absent, pas de sudo) ; le rung 4
  avait déjà échoué en fenêtre visible sur l'écran réel, cas le plus favorable.

## Reporté à la phase 2

- F10 : un preset remplace `return_deadline` en entier (fusion superficielle), alors que
  `config.local.yaml` fusionne en profondeur. À fixer par un test en phase 2.
