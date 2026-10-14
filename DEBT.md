# Dette (raccourcis assumés)

Généré par `/ponytail-debt` : un raccourci = un commentaire `shortcut:` dans le code.
À régénérer en fin de phase.

## Phase 0

- `cheaphops/fetch/http.py:17`. Seul httpx (rung 1) est branché. Plafond : aucun contournement
  anti-bot. Déclencheur : phase 1 (fetch ladder, rungs 2-4). Garder `CtxHttp` comme coquille
  unique (allowlist, cache, throttle, stats) et faire des rungs de simples transports.
- `cheaphops/fetch/http.py:140`. Lectures et écritures SQLite synchrones dans l'event loop.
  Plafond : un utilisateur, petites requêtes. Déclencheur : la latence SSE de la phase 2 en
  souffre, alors passer par `asyncio.to_thread`.
- `cheaphops/core/models.py:17`. Le regex `Domain` refuse un TLD nu (`com`) mais accepte
  un suffixe public (`co.uk`, `github.io`). Plafond : manifestes écrits à la main. Déclencheur :
  phase 4, quand le Pathfinder écrit des manifestes.

3 marqueurs, 0 sans déclencheur.

## Reportés à la phase 1 (review indépendante, même surface que la séparation coquille/transport)

- `ttl_s` brut à chaque appel alors que `explore_ttl_s`/`verify_ttl_s` ne sont pas consommés ;
  remplacer par une fraîcheur `explore|verify|none` résolue depuis `HttpConfig`.
- Throttle indexé par entrée d'allowlist : deux manifestes `ryanair.com` / `www.ryanair.com`
  ne se freinent pas mutuellement. Indexer par domaine enregistrable.
- `dict(resp.headers)` perd l'insensibilité à la casse et fusionne les `Set-Cookie` ; garder les
  paires de headers avant le skill de bootstrap de cookies.
