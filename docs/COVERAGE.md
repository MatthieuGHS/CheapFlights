# Couverture des sources

Mis à jour au fil de l'eau. Outil : Scrapling uniquement (`fetcher` → `stealthy` → `dynamic`).
Statuts : **source** = YAML actif · **accessible** = page lue, extraction à écrire ·
**bloqué** = raison notée, abandonné · **découverte** = alimente la liste de ce qu'il faut scraper.

## Compagnies qui desservent VNO, KUN, RIX, TLL, WAW, GDN (E)

Sites des aéroports : Vilnius et Kaunas (`vilnius-airport.lt`, `kaunas-airport.lt`) répondent
403 « Un instant… » (Cloudflare) aux 3 modes ; non contourné. Riga (`riga-airport.com`) et
Tallinn (`airport.ee`) répondent en `fetcher` ; Gdańsk (`airport.gdansk.pl/en`) aussi, Varsovie
(`lotnisko-chopina.pl`) ne montre que LOT. Les listes ci-dessous viennent des tableaux
« Airlines and destinations » de Wikipédia (lus en `fetcher`), recoupés avec le site officiel
quand il cite la compagnie (TLL : airBaltic, Ryanair, Wizz, Norwegian, LOT, Finnair, SAS,
Lufthansa, Turkish, Eurowings, SunExpress, Swiss, Jet2 ; GDN : Ryanair, Wizz, Norwegian, LOT,
Lufthansa, Jet2, Icelandair). Saisonnières incluses, à confirmer route par route.

| Aéroport | Low-cost / charters | Réseau et autres |
|---|---|---|
| VNO | Ryanair, Wizz Air, airBaltic, Avion Express, GetJet, Heston, Norwegian, Skyline Express, SkyUp, FLYYO, Mavi Gök, Air Montenegro | Finnair, LOT, Lufthansa, SAS, Swiss, Austrian, Brussels, Turkish, Aegean, flydubai, Israir, Arkia |
| KUN | Ryanair, Wizz Air, SkyUp, FLYYO, Freebird | — |
| RIX | Ryanair, airBaltic, Norwegian, Heston, SkyUp, Freebird, FlyOne, Skyline Express, Mavi Gök, Air Montenegro | Finnair, LOT, Lufthansa, SAS, Turkish, Aegean, Uzbekistan Airways |
| TLL | Ryanair, Wizz Air, airBaltic, Norwegian, Eurowings, Jet2, Corendon, SunExpress, Heston, NyxAir, SkyUp, Freebird, Pegasus, Mavi Gök, Air Montenegro | Finnair, LOT, Lufthansa, SAS, Swiss, Turkish |
| WAW | Ryanair, Wizz Air, Enter Air, Smartwings, Neos, Sundor, SunExpress, Corendon, Pegasus, Sky Express, Sky Alps | LOT, Lufthansa, Eurowings, KLM, Air France, British Airways, Aer Lingus, Austrian, Brussels, Swiss, SAS, Finnair, Norwegian, Turkish, Emirates, Etihad, Air China, Ethiopian, TAP, Aegean, flydubai, Air Arabia |
| GDN | Ryanair, Wizz Air, Enter Air, Smartwings, Jet2, SkyUp | LOT, Lufthansa, Eurowings, KLM, Swiss, SAS, Finnair, Norwegian, Icelandair |

À retenir pour la suite : sur VNO/KUN/RIX, Ryanair + Wizz + airBaltic couvrent l'essentiel du
low-cost. Charters visibles : GetJet, Avion Express, Heston, SkyUp, Enter Air, Smartwings,
Corendon, Jet2 — leurs sièges se vendent surtout via les voyagistes (lot A).

## Tableau

| Site | Type | Statut | Mode Scrapling | Raison / remarque |
|---|---|---|---|---|
| ryanair.com (ryanair-py) | compagnie | source (code) | lib | farfnd `oneWayFares`, 1 requête par tranche de 10 j et par aéroport |
| wizzair.com | compagnie | source (code) | stealthy + page_action | SmartSearch + farechart depuis la page ; version d'API lue dans la page |
| google.com/travel/flights (fast-flights) | agrégateur | source (code), désactivée | lib primp | pas de « n'importe où » ; échantillon de hubs ; cookie de consentement |
| secretflying.com | bons plans | source (YAML) | fetcher | liste de résultats de recherche, titres « X to Y for only €N » |
| vilnius-airport.lt | découverte | bloqué | 3 modes | Cloudflare 403 « Un instant… » |
| kaunas-airport.lt | découverte | bloqué | 3 modes | idem |
| riga-airport.com | découverte | accessible | fetcher | pages /en/airlines et /en/destinations en JS : noms non extraits |
| airport.ee (Tallinn) | découverte | accessible | fetcher | liste de destinations et page des compagnies lisibles |
| lotnisko-chopina.pl (WAW) | découverte | accessible | fetcher | accueil seulement ; pages de destinations non trouvées (404) |
| airport.gdansk.pl | découverte | accessible | fetcher | accueil lisible ; `gdansk-airport.pl` ferme la connexion |
| en.wikipedia.org (6 aéroports) | découverte | accessible | fetcher | tableaux compagnies/destinations, source des listes ci-dessus |
