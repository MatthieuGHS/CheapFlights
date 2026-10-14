---
name: add-source
description: Ajoute une nouvelle source de vols à Cheap Hops (procédure du Pathfinder, §10.1) : recon, choix des endpoints, recette v1 avec manifeste, fixtures et tests de contrat, smoke test, validation par l'utilisateur. À utiliser pour « ajoute airBaltic », « nouvelle compagnie », « nouvelle source ».
---

# Ajouter une source

Claude joue le Pathfinder. L'utilisateur est le juge : la recette naît `draft` et ne passe
`active` qu'avec son accord. Trois itérations au plus (capture -> recette -> tests) ; au-delà,
arrêt avec un rapport clair de ce qui bloque.

Règles fixes :
- Jamais d'endpoint ni de paramètre écrit de mémoire : tout vient d'une capture `recon`.
- Aucune résolution de CAPTCHA ; un mur anti-bot en headless se tente en `--stealth`, puis en
  headed avec l'utilisateur.
- Requêtes réelles : 30 au plus (recon et smoke compris), annoncées à la fin.
- Tarif de base seulement (pas de bagage, pas d'option, pas de tarif abonné).

## 1. Cadrer

Note le site, les capacités visées (`routes`, `calendar`, `day_flights`, `booking_url`) et si la
compagnie dessert VNO, KUN ou RIX.

## 2. Reconnaissance

```bash
uv run python -m cheaphops.recon "<page de résultats du site>" --goal <capacité> --out data/recon/<source>
# bandeau cookies : --click "<texte exact du bouton de refus>"
# anti-bot (document 403/405, page vide) : --stealth, puis --headed --stealth --wait 600 avec
# l'utilisateur, qui ferme tous les onglets pour terminer
```

Vérifie `meta.json` (`document`, `json_urls`, `visible_prices`). Les résultats s'ouvrent parfois
dans un nouvel onglet : recon les suit.

## 3. Choisir les endpoints

Pour chaque capacité, lis `candidates.json` (signaux IATA et prix, squelette) et les `resp_*.json`.
Relève : méthode, URL (et sa part variable, ex. version d'API), paramètres, en-têtes nécessaires,
cookies recopiés en en-tête (CSRF), statut du tarif de base, devise, fuseau des horaires,
regroupement d'aéroports. Si une capacité n'a pas d'endpoint, dis-le et ne la déclare pas.

## 4. Écrire la recette v1

Arborescence `cheaphops/recipes/<source>/v1/` (avec `__init__.py` aux deux niveaux) :

- `manifest.yaml` : `status: draft`, `capabilities`, `allowed_domains` (domaine enregistrable,
  vérifié par la Public Suffix List : `tldextract`), `home_url`, `preferred_rung`, `headed`,
  `cookie_headers`, `block_markers`, `rate_limit` prudent (`# à ajuster`), et en commentaire les
  endpoints découverts avec la date du recon.
- `recipe.py` : classe `Recipe` qui n'implémente que les capacités déclarées (Protocols de
  `cheaphops/recipes/base.py`). Réseau uniquement via `ctx.http`, fraîcheur `explore` pour les
  calendriers et routes, `verify` pour les vols du jour. Erreurs de format -> `SchemaMismatch`.
  Jamais de date passée (`ctx.today`). Modèle à suivre : `ryanair/v1` (horaires) ou `wizzair/v1`
  (prix seuls, version d'API découverte).
- `fixtures/` : réponses capturées allégées, `ground_truth.json` (prix visibles de `meta.json`).
- `test_recipe.py` : tests de contrat sur fixtures avec `cheaphops.recipes.testing` :
  routes, calendrier comparé aux prix visibles, vols du jour avec fuseaux, `SchemaMismatch` sur
  une réponse altérée, `booking_url`.

## 5. Vérifier

```bash
PYTHONDONTWRITEBYTECODE=1 uv run pytest -q cheaphops/recipes/<source>
uv run ruff check . && uv run mypy cheaphops tests scripts
```

## 6. Smoke test live

Passe temporairement le manifeste en `active`, puis :

```bash
uv run python scripts/smoke.py <source> <origine> <destination> <AAAA-MM>
```

Si un rung plus haut a été nécessaire, mets-le dans `preferred_rung`.

## 7. Jugement par l'utilisateur

Présente : endpoints retenus, capacités non couvertes et pourquoi, sortie du smoke comparée aux
prix visibles, requêtes dépensées. Demande : activer ou mettre en quarantaine.

- Activée : `status: active` et ajout du nom dans `search.sources` de `config.yaml`.
- Refusée : `status: quarantined`, avec la raison en commentaire du manifeste.

## 8. Journal et commit

Ajoute une entrée en tête de `docs/repairs.md` (`## AAAA-MM-JJ · <source> v1 · ajout · activée |
refusée`, avec les endpoints et les requêtes dépensées), puis commit
`feat(recipes): <source> v1 (<capacités>)`.
