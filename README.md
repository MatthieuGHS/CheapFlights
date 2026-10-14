# Cheap Hops

Moteur local qui cherche les voyages en avion les moins chers au départ de Vilnius, Kaunas et Riga,
toutes destinations confondues. Spécification complète : [`docs/SPEC.md`](docs/SPEC.md).

État : **phases 0 à 2** livrées (moteur, API, interface). Phases 3 à 5 en pause (voir `docs/SPEC.md` §14).

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
uv run cheaphops search --weeks 4          # recherche en ligne de commande (top-K dans le terminal)
uv run cheaphops search --budget 0         # rejoue sur le cache seul, aucune requête réseau
uv run cheaphops serve                     # API + interface sur http://127.0.0.1:8000

cd web && npm install && npm run build     # interface servie ensuite par `cheaphops serve`
cd web && npm run dev                      # interface en dev (proxy /api vers le port 8000)

uv run pytest                              # tests (fixtures, jamais de réseau)
uv run ruff check . && uv run ruff format --check .
uv run mypy cheaphops scripts tests
cd web && npx oxlint src                   # lint de l'interface
uv run python scripts/smoke.py ryanair VNO BGY 2026-11   # smoke test live d'une recette
uv run python -m cheaphops.recon <url> --goal calendar --headed --stealth --wait 600
uv run python scripts/bedrock_check.py     # modèles Bedrock disponibles
```

Navigateurs : `uv run playwright install chromium chromium-headless-shell` et
`uv run patchright install chromium` (sans `--with-deps`, qui ne gère pas Arch). Wizz ouvre une
fenêtre Chromium visible pendant une recherche (Kasada refuse le headless).

## Architecture

```
cheaphops/core/models.py   modèles pydantic : SearchParams, DayFare, Flight, GroundEdge, Manifest…
cheaphops/core/config.py   chargement et validation de config.yaml (+ config.local.yaml) et ground.yaml
cheaphops/core/db.py       SQLite + migrations SQL numérotées (PRAGMA user_version)
cheaphops/core/ctx.py      Ctx : ce qu'une recette reçoit
cheaphops/core/log.py      logs JSON sur stderr
cheaphops/fetch/http.py    ctx.http : allowlist du manifeste, rate limit par domaine, cache, stats
cheaphops/fetch/ladder.py  classification des réponses, choix du rung
cheaphops/fetch/transports.py  rungs 1-4 : httpx, curl_cffi, Scrapling furtif + curl_cffi, navigateur
cheaphops/recipes/         interfaces, registre, recettes ryanair/v1 et wizzair/v1 (+ fixtures)
cheaphops/recon/           outil recon : capture du trafic, candidates IATA + prix
cheaphops/search/          grille Explore, candidats (borne), composition horaire, Verify, budget
cheaphops/api/app.py       FastAPI : recherches, progression SSE, résultats, santé des sources
web/                       interface Vite + React + Tailwind
scripts/                   bedrock_check, smoke
```

Recherche (§9) : l'Explore remplit une grille de prix minimaux par jour (Wizz `farechart`,
Ryanair disponibilité par fenêtres de 7 jours), sous un budget de requêtes ; les candidats
aller/retour sont produits par borne croissante ; le Verify charge les vrais horaires et s'arrête
quand plus aucun candidat ne peut battre le K-ième voyage vérifié. Wizz ne fournit pas d'horaires :
ses voyages sont des allers-retours directs badgés « horaires et aéroport de départ à vérifier ».

Une recette n'accède au réseau que par `ctx.http` :

- seules les URL `https` dont l'hôte est un domaine du manifeste, ou un de ses sous-domaines, passent ;
  les redirections sont vérifiées aussi ;
- les requêtes vers un même domaine sont espacées de `min_interval_s` + un jitter aléatoire ;
- les réponses 2xx sont mises en cache dans SQLite. La clé couvre la méthode, l'URL, les paramètres,
  le corps et les headers de `http.vary_headers` (devise, langue).
