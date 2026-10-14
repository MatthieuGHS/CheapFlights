---
name: repair-recipe
description: Répare une recette Cheap Hops cassée (procédure du Medic, §10.2) : diagnostic déterministe, recon, comparaison des squelettes avec la dernière fixture valide, patch en nouvelle version draft, tests de contrat, smoke test, validation par l'utilisateur, entrée dans docs/repairs.md. À utiliser quand une source renvoie schema_mismatch, des résultats vides, des prix aberrants, ou des refus nouveaux (409, 404, version d'API).
---

# Réparer une recette

Claude joue le Medic. L'utilisateur est le juge : rien ne passe `active` sans son accord.

Règles fixes :
- Jamais d'endpoint ni de paramètre écrit de mémoire : tout vient d'une capture `recon`.
- Aucune résolution de CAPTCHA. Un CAPTCHA arrête la procédure et passe la main à l'utilisateur.
- Requêtes réelles : 20 au plus par réparation (recon et smoke compris). Compte-les et annonce
  le total. Les tests tournent sur fixtures, jamais en live.
- La version en place reste `active` jusqu'à la promotion : c'est le rollback.

## 1. Constater le symptôme

1. Lis l'erreur exacte : événement `error` de la recherche, sortie de `scripts/smoke.py`, ou
   `GET /api/sources` (dernier échec par rung, `blocked_until`).
2. Rejoue sans réseau : `uv run cheaphops search --budget 0` doit reproduire le symptôme sur le
   cache, sinon note que le cache a expiré.

## 2. Diagnostic déterministe (§7), avant toute capture

| Symptôme | Cause probable | Action |
|---|---|---|
| 403, page anti-bot | rung trop bas | laisser la ladder monter ; si le rung 4 échoue, étape 3 en headed |
| 429 | rate limit | augmenter `rate_limit.min_interval_s` du manifeste, pas de patch |
| CAPTCHA | mur interactif | **stop** : demander à l'utilisateur une navigation headed |
| 404 sur l'API | version ou chemin changé | étape 3 |
| `SchemaMismatch`, résultat vide, prix aberrant | format de réponse changé | étape 3 |
| 4xx avec un message métier (ex. `409 Availability declined`) | requête différente de celle du site | étape 3, comparer requête et en-têtes |

Si le diagnostic suffit (rate limit), corrige le manifeste et passe à l'étape 6.

## 3. Capturer l'état actuel du site

```bash
uv run python -m cheaphops.recon "<page de recherche du site>" --goal <capacité> --out data/recon/<source>-repair
# site anti-bot : ajouter --headed --stealth --wait 600 et laisser l'utilisateur naviguer,
# puis fermer tous les onglets pour terminer la capture
```

Lis `meta.json` (statut du document, URL JSON capturées) et `candidates.json`.

## 4. Comparer les squelettes

Compare la réponse capturée à la dernière fixture valide de la version active :

```bash
uv run python - <<'PY'
import difflib, json, pprint, sys
from cheaphops.context.compress import json_skeleton
old = json_skeleton(json.load(open("cheaphops/recipes/<source>/v<N>/fixtures/<fixture>.json")))
new = json_skeleton(json.load(open("data/recon/<source>-repair/<resp_XX>.json")))
sys.stdout.writelines(difflib.unified_diff(
    pprint.pformat(old, width=100).splitlines(True),
    pprint.pformat(new, width=100).splitlines(True), "fixture", "capture"))
PY
```

Compare aussi la requête : URL, paramètres, en-têtes significatifs (`candidates.json`) contre ce
qu'envoie `recipe.py`. Écris la cause en une phrase avant de patcher.

## 5. Patcher en nouvelle version

1. `cp -r cheaphops/recipes/<source>/v<N> cheaphops/recipes/<source>/v<N+1>`, puis dans le
   manifeste de v<N+1> : `version: <N+1>`, `status: draft`.
2. Remplace les fixtures concernées par les nouvelles captures (allégées) et mets à jour
   `ground_truth.json` avec les prix visibles de `meta.json`.
3. Patch minimal dans `recipe.py` : la cause, rien d'autre. Réutilise `cheaphops/skills/`.
4. Imports autorisés : stdlib, `pydantic`, `cheaphops.*`. Réseau uniquement via `ctx.http`.

## 6. Tests de contrat

```bash
PYTHONDONTWRITEBYTECODE=1 uv run pytest -q cheaphops/recipes/<source>/v<N+1>
uv run ruff check . && uv run mypy cheaphops tests scripts
```

Un test doit reproduire le symptôme sur l'ancienne fixture (il échoue sur v<N>) et passer sur
v<N+1>. Le registre ne charge que la version `active` la plus haute : pour le smoke, passe
temporairement v<N+1> en `active`.

## 7. Smoke test live

```bash
uv run python scripts/smoke.py <source> <origine> <destination> <AAAA-MM>
```

Note le nombre de requêtes de scraping et de ressources navigateur affichées.

## 8. Jugement par l'utilisateur

Présente en quelques lignes : symptôme, cause, diff des squelettes, patch, résultat des tests,
sortie du smoke comparée aux prix visibles de `ground_truth.json`, requêtes dépensées. Demande :
promouvoir ou rejeter.

- Promu : v<N+1> `status: active`, v<N> `status: deprecated`.
- Rejeté : v<N+1> `status: quarantined`, v<N> reste `active`.

## 9. Journal et commit

Ajoute une entrée en tête de `docs/repairs.md` :

```markdown
## AAAA-MM-JJ · <source> v<N> -> v<N+1> · promue | rejetée
- Symptôme : <message exact>
- Cause : <une phrase>
- Correctif : <ce qui a changé>
- Requêtes réelles : <n>
```

Commit : `fix(recipes): <source> v<N+1>, <cause en quelques mots>`.
