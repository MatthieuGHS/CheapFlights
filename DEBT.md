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

2 marqueurs, 0 sans déclencheur.
