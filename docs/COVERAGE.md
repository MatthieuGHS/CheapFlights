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
| teztour.lt (TEZ Tour LT) | charter, vol seul | **source** (`teztour.yaml`) | fetcher | page « Skrydžiai » : 49 vols aller simple VNO→… avec date, heure, compagnie (GetJet, Airhub…), prix ; entrent dans l'assemblage des aller-retours |
| paskutineminute.teztour.lt | voyagiste | accessible | fetcher | forfaits hôtel+vol, pas de vol seul |
| tez-tour.com | voyagiste | accessible | fetcher | accueil de recherche (formulaire) |
| joinup.lt / .lv / .ee (Join UP!) | voyagiste | accessible | fetcher (SPA Nuxt), dynamic pour l'API | forfaits uniquement ; `/api/main/tour/regions` ne donne que les villes de départ (VNO, RIX, TLL) sans prix |
| novaturas.lt | voyagiste | accessible | fetcher + dynamic (GraphQL) | forfaits ; `flights.novatours.eu` (billets) est un formulaire de recherche, non exploré |
| coraltravel.lt / .lv | voyagiste | accessible | stealthy | fetcher bloqué, stealthy passe ; forfaits seulement |
| anextour.com / anextour.lt | voyagiste | bloqué (.com) / accessible (.lt) | 3 modes | .com : CAPTCHA ; .lt : formulaire de forfaits |
| itaka.pl, r.pl (Rainbow), tui.pl | voyagiste PL | accessible | fetcher | last minute en forfaits, départs Pologne, pas de vol seul public |
| tui.lt / .lv / .ee | voyagiste | bloqué | 3 modes | erreur TLS (nom de certificat invalide) |
| enterair.pl, getjet.aero, smartlynx | charter (compagnie) | accessible / sans tarifs | fetcher | pas de vente publique de sièges ; SmartLynx : erreur HTTP |
| corendon.com / corendonairlines.com | charter (compagnie) | accessible, sans tarifs lisibles | fetcher | desserte Baltique limitée à TLL |
| fly4free.com (flux RSS par ville) | bons plans | **source** (`fly4free-com.yaml`) | fetcher | 87 bons plans VNO/RIX/TLL/WAW/GDN, aller-retour long-courrier, sans date |
| fly4free.pl | bons plans | accessible, écarté | fetcher | flux et tags lisibles mais titres en forfaits « loty + hôtel » : aucun vol seul extrait |
| secretflying.com `/feed/` | bons plans | accessible via la recherche | fetcher (flux : page HTML) | le flux renvoie une page ; la recherche (YAML existant) suffit |
| travelpirates.com, urlaubspiraten.de, wakacyjnipiraci.pl | bons plans DE/PL | accessible, écarté | fetcher | flux lisibles, offres surtout hôtels/forfaits depuis DE/PL ; pas de départ VNO/RIX/TLL |
| holidaypirates.com | bons plans | accessible, sans prix | fetcher | page rendue côté client, aucun prix dans le HTML |
| pepper.pl `/grupa/podroze` | bons plans PL | accessible | fetcher | page lisible (55 prix) ; flux RSS : 404 + CAPTCHA ; extraction non écrite |
| jacksflightclub.com | bons plans | bloqué | fetcher | `/deals` : 404 (offres réservées aux abonnés) |
| theflightdeal.com | bons plans US | accessible, écarté | fetcher | départs États-Unis uniquement |
| sites LT/LV/EE de bons plans | bons plans | non trouvé | — | recherche web sans résultat exploitable ; `skrydziai.lt` (certificat invalide) et `lowcost.lt` (DNS) inaccessibles |
| azair.eu | agrégateur « n'importe où » | **source** (`azair.yaml`) | fetcher | recherche flexible par URL, 1 requête par origine, ~25 résultats chacune : vols aller et retour datés, compagnie et lien de réservation, combinaisons multi-compagnies |
| kayak.com/explore | agrégateur « n'importe où » | **source** (`kayak-explore.yaml`) | dynamic (XHR `explorePageDestinations`) | 161 destinations par origine en 1 chargement ; aller-retour avec dates, compagnie, prix USD converti ; fenêtre filtrée côté recherche |
| momondo.com/explore | agrégateur | accessible, doublon | fetcher + dynamic | même moteur et même API que Kayak, non ajouté |
| kiwi.com | agrégateur | **bloqué (automatique)** | dynamic, stealthy (5 chargements) | URL `/search/results/vilnius-lithuania/anywhere/…` reconnue (formulaire « From Vilnius · To Anywhere ») mais les dates de l'URL (`2026-10-23_2026-10-30/no-return`, date seule, `anytime`) ne sont jamais prises : « Departure : Nothing here yet… », aucune recherche GraphQL (seul `RecentSearchesQuery` part). Pas de CAPTCHA. Reprise : capture recon visible (`python -m cheaphops.lastminute.recon kiwi https://www.kiwi.com/en/`) pour lire le vrai format d'URL / la requête de recherche. |
| skyscanner.net | agrégateur | **bloqué** | stealthy (headless, délais et scroll) | `/transport/flights-from/vno/?oym=2611` redirige vers `/sttc/px/captcha-v2/` : écran PerimeterX « Are you a person or a robot ? ». Non contourné, par choix. Les pages d'« everywhere » devinées donnent 404 ou aucun retour. |
| aviasales.com | agrégateur | non trouvé | fetcher | URL `/routes/vno` : 404 ; pas de recherche « partout » localisée |
| trip.com | agrégateur | non trouvé | dynamic | accueil seul accessible ; URL « vers n'importe où » : 404 |
| edreams.com, opodo.com | agrégateur | non trouvé | fetcher | `/flights/vilnius/` : 404 ; pas d'URL de découverte trouvée |
| airbaltic.com | compagnie | bloqué (page de route) | fetcher | page « flights-from-vilnius » : 404 avec marqueur CAPTCHA |
| norwegian.com | compagnie | non trouvé | fetcher, stealthy | URL de route : 404 |
| lot.com, flysas.com, lufthansa.com, swiss.com, austrian.com, brusselsairlines.com, klm.com, airfrance.lt, eurowings.com, turkishairlines.com | compagnie | non trouvé | fetcher | URLs « flights-from-vilnius » devinées : 404 ; réservation par moteur privé |
| finnair.com | compagnie | accessible, sans prix | fetcher | page `/flights/from/vno` 200 mais prix rendus côté client (textes de traduction seulement) |
| flypgs.com (Pegasus), smartwings.com | compagnie | bloqué | 3 modes | 403 (Pegasus) ; Cloudflare « Un instant… » (Smartwings) |
| flydubai.com, aegeanair.com, elal.com, buzzair.com | compagnie | accessible, sans prix | fetcher/stealthy | accueils sans tarif exploitable (moteur de réservation JS) |
