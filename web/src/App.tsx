import { lazy, Suspense, useEffect, useMemo, useState } from 'react'
import { followSearch, getAirports, getConfig, getHistory, getSaved, getSearch, startSearch, type Config, type Saved, type SearchEvent, type Status } from './api'
import { AirportPicker } from './AirportPicker'
import { buildIndex, type AirportIndex } from './airports'
import { Row, Segmented, SourceToggle, Stepper, Switch } from './Form'
import { History, SavedView } from './History'
import { Calendar } from './Calendar'
import { addDays, between, iso, toPeriods } from './dates'
import { Results } from './Results'

const RouteMap = lazy(() => import('./RouteMap')) // Leaflet : chargé seulement si on ouvre la carte

const HORIZON_DAYS = 60 // comme HORIZON_DAYS côté serveur (run.py)
const MAX_TARGETS = 10 // comme LastMinute.destinations côté serveur (config.py)

/** « Vilnius, Kaunas et Riga » */
const listFr = (names: string[]) => (names.length < 2 ? names.join('') : `${names.slice(0, -1).join(', ')} et ${names[names.length - 1]}`)

/** Navigation par l'ancre : « #historique » et « #historique/<id> », sans routeur. */
function useHash() {
  const [hash, setHash] = useState(location.hash)
  useEffect(() => {
    const on = () => setHash(location.hash)
    addEventListener('hashchange', on)
    return () => removeEventListener('hashchange', on)
  }, [])
  return hash
}

export default function App() {
  const hash = useHash()
  const page = hash.startsWith('#historique') ? 'history' : 'search'
  const [last, setLast] = useState<Saved | null>(null)
  const [config, setConfig] = useState<Config | null>(null)
  const [days, setDays] = useState(10)
  const [mode, setMode] = useState<'days' | 'dates'>('days')
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [today] = useState(() => iso(new Date()))
  const [nights, setNights] = useState(3)
  const [origins, setOrigins] = useState<string[]>([])
  const [targets, setTargets] = useState<string[]>([])
  const [index, setIndex] = useState<AirportIndex | null>(null)
  const [showMap, setShowMap] = useState(false)
  const [aimed, setAimed] = useState(false)
  const [google, setGoogle] = useState(false)
  const [airbaltic, setAirbaltic] = useState(true)
  const [kiwi, setKiwi] = useState(true)
  const [weekend, setWeekend] = useState(false)
  const [connections, setConnections] = useState(true)
  const [runId, setRunId] = useState<string | null>(null)
  const [events, setEvents] = useState<SearchEvent[]>([])
  const [status, setStatus] = useState<Status | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getConfig()
      .then((c) => {
        setConfig(c)
        setDays(c.days)
        if (c.periods.length) {
          setMode('dates')
          setPicked(new Set(c.periods.flatMap((p) => between(p.start, p.end))))
        }
        setNights(c.max_nights)
        setOrigins(c.origins)
        setTargets(c.destinations)
        setAimed(c.destinations.length > 0)
        setGoogle(c.google.enabled)
        setAirbaltic(c.airbaltic.enabled)
        setKiwi(c.kiwi.enabled)
        setWeekend(c.weekend)
        setConnections(c.connections)
      })
      .catch((e: unknown) => setError(String(e)))
    getAirports()
      .then((list) => setIndex(list.length ? buildIndex(list) : null)) // vide : table absente côté serveur
      .catch(() => {}) // sans table, le champ accepte encore les codes tapés
    // la dernière recherche sauvegardée, pour ne rien perdre en rechargeant la page
    getHistory()
      .then((list) => (list[0] ? getSaved(list[0].id) : null))
      .then(setLast)
      .catch(() => {}) // sans historique, la page reste simplement vide
  }, [])

  useEffect(() => {
    if (!runId) return
    return followSearch(runId, (e) => {
      setEvents((prev) => [...prev, e])
      if (e.type !== 'done') return
      getSearch(runId)
        .then(setStatus)
        .catch((err: unknown) => setStatus({ id: runId, done: true, error: String(err), result: null }))
    })
  }, [runId])

  const running = runId !== null && status === null
  // des plages de la config, ou une page ouverte depuis hier, peuvent contenir des jours passés
  const ranges = useMemo(() => toPeriods([...picked].filter((d) => d >= today)), [picked, today])
  const go = () => {
    setEvents([])
    setStatus(null)
    setError(null)
    const periods = mode === 'dates' ? ranges : []
    const destinations = aimed ? targets : []
    startSearch({ days, periods, max_nights: nights, google, airbaltic, kiwi, weekend, origins, destinations, connections })
      .then((r) => setRunId(r.id))
      .catch((e: unknown) => setError(String(e)))
  }
  const sources = events.filter((e) => e.type === 'source')
  const city = (code: string) => index?.byCode.get(code)?.city ?? code
  const nearby = (config?.optional_origins ?? []).filter((c) => !origins.includes(c))
  const summary = [
    `Depuis ${listFr(origins.map(city)) || '…'}`,
    `vers ${aimed ? listFr(targets.map(city)) || '…' : "n'importe où"},`,
    mode === 'days' ? `départ dans les ${days} jours,` : `${ranges.length} plage${ranges.length > 1 ? 's' : ''} de dates,`,
    `${nights} nuit${nights > 1 ? 's' : ''} au plus.`,
  ].join(' ')

  return (
    <div className="mx-auto max-w-4xl px-4 py-8 sm:py-12">
      <header className="mb-8">
        <div className="flex items-baseline justify-between gap-4">
          <h1 className="text-xl font-semibold tracking-tight">Cheap Hops</h1>
          <nav className="flex gap-4 text-sm">
            {(
              [
                ['search', '#', 'Recherche'],
                ['history', '#historique', 'Historique'],
              ] as const
            ).map(([key, href, label]) => (
              <a key={key} href={href} aria-current={page === key ? 'page' : undefined} className={page === key ? 'font-medium text-ink' : 'text-muted hover:text-ink'}>
                {label}
              </a>
            ))}
          </nav>
        </div>
        <p className="mt-1 text-muted">
          Les vols les moins chers des prochains jours, vers n'importe où ou vers les villes de votre choix.
        </p>
      </header>

      {page === 'history' ? (
        <History id={hash.split('/')[1] ?? null} />
      ) : (
        <>

          <form
            className="divide-y divide-line border-y border-line"
            onSubmit={(e) => {
              e.preventDefault()
              go()
            }}
          >
            <Row title="Quand">
              <div className="flex flex-wrap items-center gap-x-8 gap-y-3">
                <span className="flex flex-wrap items-center gap-3">
                  <Segmented
                    name="mode"
                    value={mode}
                    onChange={setMode}
                    options={[
                      ['days', 'Dans les prochains jours'],
                      ['dates', 'Dates précises'],
                    ] as const}
                  />
                  {mode === 'days' && (
                    <label className="flex items-center gap-2 text-sm">
                      <input type="number" min={0} max={HORIZON_DAYS} value={days} onChange={(e) => setDays(+e.target.value)} className="input w-16" aria-label="Nombre de jours" />
                      <span className="text-muted">jours</span>
                    </label>
                  )}
                </span>
                <Stepper label="Nuits au plus" value={nights} onChange={setNights} min={0} max={14} />
              </div>
              {mode === 'dates' && (
                <div className="mt-4 rounded-md border border-line bg-surface p-4">
                  <Calendar selected={picked} onChange={setPicked} today={today} last={addDays(today, HORIZON_DAYS)} />
                </div>
              )}
            </Row>

            <Row title="D'où">
              <AirportPicker label="Aéroports de départ" value={origins} onChange={setOrigins} index={index} placeholder="Une ville ou un code d'aéroport" />
              {nearby.length > 0 && (
                <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted">
                  Aussi possibles en bus depuis chez vous :
                  {nearby.map((c) => (
                    <button key={c} type="button" onClick={() => setOrigins([...origins, c])} className="rounded text-accent hover:underline">
                      + {city(c)} <span className="text-xs">{c}</span>
                    </button>
                  ))}
                </p>
              )}
            </Row>

            <Row title="Vers">
              <Segmented
                name="aim"
                value={aimed}
                onChange={(key) => {
                  setAimed(key)
                  if (key) setGoogle(true) // vers des cibles, Google couvre LOT, SAS… : coché par défaut
                }}
                options={[
                  [false, "N'importe où"],
                  [true, 'Aéroports précis'],
                ] as const}
              />
              {aimed && (
                <div className="mt-3">
                  <AirportPicker label="Aéroports visés" value={targets} onChange={setTargets} index={index} max={MAX_TARGETS} placeholder="Une ville, un pays, un aéroport" />
                  <div className="mt-1.5 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                    <p className="text-xs text-muted">
                      {targets.length} sur {MAX_TARGETS} : chaque aéroport visé coûte des requêtes à chaque source.
                    </p>
                    {index && (
                      <button type="button" onClick={() => setShowMap(!showMap)} aria-expanded={showMap} className="text-sm text-accent hover:underline">
                        {showMap ? 'Masquer la carte' : 'Choisir sur la carte'}
                      </button>
                    )}
                  </div>
                  {showMap && index && (
                    <Suspense fallback={<div className="mt-3 h-80 rounded-md border border-line bg-surface" />}>
                      <RouteMap
                        index={index}
                        origins={origins}
                        targets={targets}
                        full={targets.length >= MAX_TARGETS}
                        onToggle={(code) => setTargets(targets.includes(code) ? targets.filter((c) => c !== code) : [...targets, code])}
                      />
                    </Suspense>
                  )}
                </div>
              )}
            </Row>

            <Row title="Options">
              <div className="flex flex-wrap gap-x-10 gap-y-3">
                <Switch checked={weekend} onChange={setWeekend} label="Week-end seulement" hint="Départ vendredi ou samedi, retour dimanche ou lundi matin" />
                <Switch checked={connections} onChange={setConnections} label="Avec correspondances" hint="Escale de 3 h au moins, sur billets séparés" />
              </div>
            </Row>

            <Row title="Sources">
              <div className="flex flex-wrap gap-2">
                <SourceToggle checked={airbaltic} onChange={setAirbaltic} label="airBaltic" hint="Prix de la compagnie, au jour" />
                <SourceToggle checked={kiwi} onChange={setKiwi} label="Kiwi.com" hint="Autres compagnies, prix indicatifs" />
                <SourceToggle checked={google} onChange={setGoogle} label="Google Flights" hint="Quelques destinations, plus lent" />
              </div>
              <p className="mt-2 text-xs text-muted">Ryanair, Wizz Air et les sites de bons plans sont toujours interrogés.</p>
            </Row>

            <div className="flex flex-wrap items-center justify-end gap-x-6 gap-y-3 py-5">
              <p className="min-w-0 flex-1 text-sm text-muted">{summary}</p>
              <button
                disabled={running || !config || origins.length === 0 || (mode === 'dates' && ranges.length === 0) || (aimed && targets.length === 0)}
                className="rounded-md bg-ink px-5 py-2.5 text-sm font-medium text-paper hover:opacity-90 disabled:opacity-40"
              >
                {running ? 'Recherche en cours' : 'Chercher des vols'}
              </button>
            </div>
          </form>

          {error && (
            <p role="alert" className="mt-6 rounded-md bg-warn-soft px-4 py-3 text-sm text-warn">
              {error}
            </p>
          )}

          {running && (
            <div className="mt-8" aria-live="polite">
              <div className="progress relative h-0.5 overflow-hidden bg-line" />
              <ul className="mt-4 space-y-1 text-sm text-muted">
                {sources.map((e, i) => (
                  <li key={i} className="flex gap-3">
                    <span className="w-32 text-ink">{e.source}</span>
                    {e.error ? <span className="text-warn">en échec</span> : <span>{e.fares} tarifs, {e.requests} requêtes</span>}
                  </li>
                ))}
                {sources.length === 0 && <li>Interrogation des compagnies et des sites de bons plans…</li>}
              </ul>
            </div>
          )}

          {status?.error && (
            <p role="alert" className="mt-6 rounded-md bg-warn-soft px-4 py-3 text-sm text-warn">
              La recherche a échoué : {status.error}
            </p>
          )}
          {status?.result && <Results key={status.id} result={status.result} />}
          {!runId && last && <SavedView saved={last} title="Dernière recherche" />}
        </>
      )}
    </div>
  )
}
