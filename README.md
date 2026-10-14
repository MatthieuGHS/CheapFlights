# Cheap Hops

Moteur local qui cherche les voyages en avion les moins chers au départ de Vilnius, Kaunas et Riga,
toutes destinations confondues. Spécification complète : [`docs/SPEC.md`](docs/SPEC.md).

État : **phase 0** (fondations). Pas encore de recherche.

## Installation (Arch Linux)

```bash
sudo pacman -S --needed uv aws-cli bubblewrap   # bubblewrap : sandbox de la phase 3
uv python install 3.12                          # Python 3.12 géré par uv, indépendant du système
uv sync
```

Lance toujours les commandes via `uv run`, pour ne pas tomber sur un autre Python du PATH (anaconda…).

## AWS Bedrock

1. Crée un profil `bedrock` dans `~/.aws/config` avec `region = eu-north-1` et ses clés dans
   `~/.aws/credentials` (`aws configure --profile bedrock`).
2. Liste les modèles et inference profiles disponibles :
   `uv run python scripts/bedrock_check.py`
3. Un modèle listé n'est pas forcément ouvert à ton compte. Vérifie avec un appel d'un token :
   `uv run python scripts/bedrock_check.py --ping eu.anthropic.claude-haiku-4-5-20251001-v1:0`
4. Reporte les IDs qui répondent `OK` dans `config.yaml` (`llm.fast.model_id`, `llm.strong.model_id`).

## Configuration

- `config.yaml` : paramètres de recherche (§4.2), presets, HTTP, LLM, plafonds de coût. Versionné.
- `config.local.yaml` : surcharges (celles de l'UI à partir de la phase 2), fusionnées par-dessus.
  Non versionné. On n'écrit jamais dans `config.yaml` depuis l'app.
- `ground.yaml` : trajets sol entre villes d'origine et regroupement des aéroports de destination.

Les valeurs estimées sont marquées `# à ajuster`.

## Commandes

```bash
uv run pytest                              # tests
uv run ruff check . && uv run ruff format --check .
uv run mypy cheaphops scripts tests
uv run python scripts/bedrock_check.py     # modèles Bedrock disponibles
```

## Architecture (phase 0)

```
cheaphops/core/models.py   modèles pydantic : SearchParams, DayFare, Flight, GroundEdge, Manifest…
cheaphops/core/config.py   chargement et validation de config.yaml (+ config.local.yaml) et ground.yaml
cheaphops/core/db.py       SQLite + migrations SQL numérotées (PRAGMA user_version)
cheaphops/core/ctx.py      Ctx : ce qu'une recette reçoit
cheaphops/core/log.py      logs JSON sur stderr
cheaphops/fetch/http.py    ctx.http : allowlist du manifeste, rate limit par domaine, cache, stats
cheaphops/recipes/base.py  interface Recipe
scripts/bedrock_check.py   inventaire et test d'accès Bedrock
```

Une recette n'accède au réseau que par `ctx.http` :

- seules les URL `https` dont l'hôte est un domaine du manifeste, ou un de ses sous-domaines, passent ;
  les redirections sont vérifiées aussi ;
- les requêtes vers un même domaine sont espacées de `min_interval_s` + un jitter aléatoire ;
- les réponses 2xx sont mises en cache dans SQLite. La clé couvre la méthode, l'URL, les paramètres,
  le corps et les headers de `http.vary_headers` (devise, langue).
