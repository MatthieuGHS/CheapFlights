# Cheap Hops — dernière minute partout

Départs de J+0 à J+N (défaut 10) depuis VNO, KUN, RIX : les allers simples les moins chers vers
n'importe où, et les aller-retours formés de deux allers simples (compagnies et aéroports de
retour libres, 3 nuits max), triés par prix total.

```
uv run cheaphops search [--days 10] [--origins VNO,KUN,RIX]   # récap en console
uv run cheaphops serve                                          # UI sur http://127.0.0.1:8000
(cd web && npm run build)                                       # une fois, pour l'UI
```

Sources (`cheaphops/lastminute/sources.py`), réglages dans `config.yaml` (`lastminute:`) :

- **Ryanair** : `ryanair-py`, endpoint `oneWayFares` (1 requête par aéroport, toutes destinations).
- **Wizz** : `SmartSearchCheapFlightsV2` via Scrapling `StealthyFetcher` headless (1 page + 1 POST
  par aéroport). Renvoie le moins cher par destination sur une période flexible : peu de tarifs
  tombent dans la fenêtre.
- **Google Flights** (désactivé par défaut, `--google`) : `fast-flights`. Pas de « n'importe où » (une requête = une origine, une
  destination, une date) : échantillon de hubs configuré, hors Ryanair/Wizz.
- **airBaltic** : API du site (`/api/orig-dest`, `/api/fsf/outbound`), GET publics sans
  navigateur. Une requête = un an de prix au jour (sans heure) pour une route et un sens : allers
  de chaque route directe, puis retours des moins chères, plafonné par `airbaltic.requests`.
- **Kiwi.com** : GraphQL du site (`api.skypicker.com/umbrella/v2/graphql`), sans jeton. Le moins
  cher par ville « n'importe où », puis le retour des `kiwi.returns` meilleures destinations ;
  prix indicatifs, Ryanair et Wizz exclus (lus en direct).

Sources YAML (`cheaphops/lastminute/web/*.yaml`, Scrapling : fetcher → stealthy → dynamic,
sélecteurs adaptatifs, flux RSS ou interception de réponses JSON) : azair, kayak-explore, teztour,
fly4free-com, secretflying. Voir `docs/COVERAGE.md` pour tous les sites explorés. Sonde d'un site :
`uv run python -m cheaphops.lastminute.probe URL`.

Étape 2 : les routes Ryanair/Wizz vues par un agrégateur sont revérifiées chez la compagnie
(`verify_routes`), puis les retours manquants sont cherchés chez Ryanair pour les destinations
les moins chères, dans la limite de `request_budget`. Tests : `uv run pytest` (fixtures, sans
réseau).
