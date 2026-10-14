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
- **Google Flights** : `fast-flights`. Pas de « n'importe où » (une requête = une origine, une
  destination, une date) : échantillon de hubs configuré, hors Ryanair/Wizz.

Étape 2 : les retours sont cherchés depuis les `return_candidates` destinations les moins chères
(Ryanair, plus Wizz pour celles qu'il dessert). Les aller-retours sont donc limités à ces
destinations. Tests : `uv run pytest` (fixtures, sans réseau).
