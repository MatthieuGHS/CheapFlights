-- Ressources chargées par le navigateur lui-même (pages, scripts, XHR du site) aux rungs 3-4,
-- distinctes des requêtes de scraping comptées par successes / failures.
ALTER TABLE fetch_stats ADD COLUMN browser_requests INTEGER NOT NULL DEFAULT 0;
