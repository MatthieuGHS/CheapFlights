import { useEffect, useState } from 'react'
import { followSearch, getConfig, getSearch, startSearch, type Config, type SearchEvent, type Status } from './api'
import { Results } from './Results'

const Field = ({ label, children }: { label: string; children: React.ReactNode }) => (
  <label className="flex flex-col gap-1 text-sm">
    <span className="text-muted">{label}</span>
    {children}
  </label>
)

export default function App() {
  const [config, setConfig] = useState<Config | null>(null)
  const [days, setDays] = useState(10)
  const [nights, setNights] = useState(3)
  const [origins, setOrigins] = useState('')
  const [google, setGoogle] = useState(false)
  const [weekend, setWeekend] = useState(false)
  const [runId, setRunId] = useState<string | null>(null)
  const [events, setEvents] = useState<SearchEvent[]>([])
  const [status, setStatus] = useState<Status | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getConfig()
      .then((c) => {
        setConfig(c)
        setDays(c.days)
        setNights(c.max_nights)
        setOrigins(c.origins.join(', '))
        setGoogle(c.google.enabled)
        setWeekend(c.weekend)
      })
      .catch((e: unknown) => setError(String(e)))
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
    startSearch({ days, max_nights: nights, google, weekend, origins: origins.split(',').map((s) => s.trim().toUpperCase()).filter(Boolean) })
      .then((r) => setRunId(r.id))
      .catch((e: unknown) => setError(String(e)))
  }
  const sources = events.filter((e) => e.type === 'source')

  return (
    <div className="mx-auto max-w-4xl px-4 py-8 sm:py-12">
      <header className="mb-8">
        <h1 className="text-xl font-semibold tracking-tight">Cheap Hops</h1>
        <p className="mt-1 text-muted">
          Les vols les moins chers des prochains jours, vers n'importe où
          {config && ` depuis ${config.origins.join(', ')}`}.
        </p>
      </header>

      <form
        className="flex flex-wrap items-end gap-x-5 gap-y-4 border-y border-line py-5"
        onSubmit={(e) => {
          e.preventDefault()
          go()
        }}
      >
        <Field label="Départ dans les (jours)">
          <input type="number" min={0} max={60} value={days} onChange={(e) => setDays(+e.target.value)} className="input w-24" />
        </Field>
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
        <fieldset className="flex flex-col gap-1.5 text-sm">
          <legend className="sr-only">Options</legend>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={weekend} onChange={(e) => setWeekend(e.target.checked)} className="accent-accent" />
            Week-end seulement
          </label>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={google} onChange={(e) => setGoogle(e.target.checked)} className="accent-accent" />
            Inclure Google Flights
          </label>
        </fieldset>
        <button
          disabled={running || !config}
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
      {status?.result && <Results result={status.result} />}
    </div>
  )
}
