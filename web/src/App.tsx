import { useEffect, useState } from 'react'
import { followSearch, getConfig, getHistory, getSaved, getSearch, startSearch, type Config, type Saved, type SearchEvent, type Status } from './api'
import { History, SavedView } from './History'
import { Calendar } from './Calendar'
import { addDays, between, iso, toPeriods } from './dates'
import { Results } from './Results'

const HORIZON_DAYS = 60 // comme HORIZON_DAYS côté serveur (run.py)

const Field = ({ label, children }: { label: string; children: React.ReactNode }) => (
  <label className="flex flex-col gap-1 text-sm">
    <span className="text-muted">{label}</span>
    {children}
  </label>
)

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
  const [origins, setOrigins] = useState('')
  const [targets, setTargets] = useState('') // vide : n'importe où
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
        setOrigins(c.origins.join(', '))
        setTargets(c.destinations.join(', '))
        setAimed(c.destinations.length > 0)
        setGoogle(c.google.enabled)
        setAirbaltic(c.airbaltic.enabled)
        setKiwi(c.kiwi.enabled)
        setWeekend(c.weekend)
        setConnections(c.connections)
      })
      .catch((e: unknown) => setError(String(e)))
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
  const go = () => {
    setEvents([])
    setStatus(null)
    setError(null)
    // des plages de la config, ou une page ouverte depuis hier, peuvent contenir des jours passés
    const periods = mode === 'dates' ? toPeriods([...picked].filter((d) => d >= today)) : []
    const codes = (text: string) => text.split(',').map((s) => s.trim().toUpperCase()).filter(Boolean)
    const destinations = aimed ? codes(targets) : []
    startSearch({ days, periods, max_nights: nights, google, airbaltic, kiwi, weekend, origins: codes(origins), destinations, connections })
      .then((r) => setRunId(r.id))
      .catch((e: unknown) => setError(String(e)))
  }
  const sources = events.filter((e) => e.type === 'source')

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
          Les vols les moins chers des prochains jours, {aimed && targets.trim() ? `vers ${targets.toUpperCase()}` : "vers n'importe où"}
          {config && ` depuis ${config.origins.join(', ')}`}.
        </p>
      </header>

      {page === 'history' ? (
        <History id={hash.split('/')[1] ?? null} />
      ) : (
        <>

          <form
            className="flex flex-wrap items-end gap-x-5 gap-y-4 border-y border-line py-5"
            onSubmit={(e) => {
              e.preventDefault()
              go()
            }}
          >
            <fieldset className="flex flex-col gap-1 text-sm">
              <legend className="mb-1 text-muted">Quand partir</legend>
              <div className="flex items-center gap-3">
                <span className="inline-flex rounded-md border border-line bg-surface p-0.5">
                  {(
                    [
                      ['days', 'Dans les prochains jours'],
                      ['dates', 'Dates précises'],
                    ] as const
                  ).map(([key, label]) => (
                    <label key={key} className={`cursor-pointer rounded px-3 py-1 ${mode === key ? 'bg-ink text-paper' : 'text-muted hover:text-ink'}`}>
                      <input type="radio" name="mode" value={key} checked={mode === key} onChange={() => setMode(key)} className="sr-only" />
                      {label}
                    </label>
                  ))}
                </span>
                {mode === 'days' && (
                  <label className="flex items-center gap-2">
                    <input type="number" min={0} max={HORIZON_DAYS} value={days} onChange={(e) => setDays(+e.target.value)} className="input w-20" aria-label="Nombre de jours" />
                    <span className="text-muted">jours</span>
                  </label>
                )}
              </div>
            </fieldset>
            <Field label="Nuits max">
              <input type="number" min={0} value={nights} onChange={(e) => setNights(+e.target.value)} className="input w-20" />
            </Field>
            <Field label="Aéroports de départ">
              <input
                value={origins}
                onChange={(e) => setOrigins(e.target.value)}
                className="input w-48 uppercase"
                aria-describedby="optional-origins"
              />
            </Field>
            <fieldset className="flex flex-col gap-1 text-sm">
              <legend className="mb-1 text-muted">Où aller</legend>
              <div className="flex items-center gap-3">
                <span className="inline-flex rounded-md border border-line bg-surface p-0.5">
                  {(
                    [
                      [false, "N'importe où"],
                      [true, 'Aéroports précis'],
                    ] as const
                  ).map(([key, label]) => (
                    <label key={label} className={`cursor-pointer rounded px-3 py-1 ${aimed === key ? 'bg-ink text-paper' : 'text-muted hover:text-ink'}`}>
                      <input
                        type="radio"
                        name="aim"
                        checked={aimed === key}
                        onChange={() => {
                          setAimed(key)
                          if (key) setGoogle(true) // vers des cibles, Google couvre airBaltic, LOT… : coché par défaut
                        }}
                        className="sr-only"
                      />
                      {label}
                    </label>
                  ))}
                </span>
                {aimed && (
                  <input
                    value={targets}
                    onChange={(e) => setTargets(e.target.value)}
                    placeholder="BGY, BCN"
                    aria-label="Aéroports visés"
                    className="input w-40 uppercase"
                  />
                )}
              </div>
            </fieldset>
            <fieldset className="flex flex-col gap-1.5 text-sm">
              <legend className="sr-only">Options</legend>
              <label className="flex items-center gap-2">
                <input type="checkbox" checked={weekend} onChange={(e) => setWeekend(e.target.checked)} className="accent-accent" />
                Week-end seulement
              </label>
              <label className="flex items-center gap-2">
                <input type="checkbox" checked={connections} onChange={(e) => setConnections(e.target.checked)} className="accent-accent" />
                Avec correspondances
              </label>
              <label className="flex items-center gap-2">
                <input type="checkbox" checked={google} onChange={(e) => setGoogle(e.target.checked)} className="accent-accent" />
                Inclure Google Flights
              </label>
              <label className="flex items-center gap-2">
                <input type="checkbox" checked={airbaltic} onChange={(e) => setAirbaltic(e.target.checked)} className="accent-accent" />
                airBaltic
              </label>
              <label className="flex items-center gap-2">
                <input type="checkbox" checked={kiwi} onChange={(e) => setKiwi(e.target.checked)} className="accent-accent" />
                Kiwi.com
              </label>
            </fieldset>
            {mode === 'dates' && (
              <div className="order-last w-full rounded-md border border-line bg-surface p-4">
                <Calendar selected={picked} onChange={setPicked} today={today} last={addDays(today, HORIZON_DAYS)} />
              </div>
            )}
            <button
              disabled={running || !config || (mode === 'dates' && picked.size === 0) || (aimed && !targets.trim())}
              className="ml-auto rounded-md bg-ink px-5 py-2 text-sm font-medium text-paper hover:opacity-90 disabled:opacity-40"
            >
              {running ? 'Recherche en cours' : 'Chercher des vols'}
            </button>
            {config && (
              <p id="optional-origins" className="w-full text-xs text-muted">
                Aéroports voisins possibles, avec bus depuis chez vous : {config.optional_origins.join(', ')}.
              </p>
            )}
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
