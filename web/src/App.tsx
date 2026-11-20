import { useEffect, useState } from 'react'
import { followSearch, getConfig, getSearch, startSearch, type Config, type SearchEvent, type Status } from './api'
import { Results } from './Results'

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
        setOrigins(c.origins.join(','))
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

  return (
    <div className="mx-auto max-w-4xl space-y-6 px-4 py-6">
      <h1 className="text-2xl font-semibold tracking-tight">Cheap Hops · dernière minute</h1>
      <form
        className="flex flex-wrap items-end gap-3 text-sm"
        onSubmit={(e) => {
          e.preventDefault()
          go()
        }}
      >
        <label>
          Départs de J+0 à J+
          <input type="number" min={0} max={60} value={days} onChange={(e) => setDays(+e.target.value)} className="input ml-1 w-16" />
        </label>
        <label>
          Nuits max
          <input type="number" min={0} value={nights} onChange={(e) => setNights(+e.target.value)} className="input ml-1 w-16" />
        </label>
        <label>
          Origines
          <input value={origins} onChange={(e) => setOrigins(e.target.value)} className="input ml-1 w-40" />
          {config && <span className="ml-1 text-stone-500">optionnels : {config.optional_origins.join(', ')}</span>}
        </label>
        <label>
          <input type="checkbox" checked={weekend} onChange={(e) => setWeekend(e.target.checked)} /> Week-end
          uniquement
        </label>
        <label>
          <input type="checkbox" checked={google} onChange={(e) => setGoogle(e.target.checked)} /> Google Flights
        </label>
        <button disabled={running || !config} className="rounded bg-stone-900 px-4 py-1.5 text-white disabled:opacity-50 dark:bg-stone-100 dark:text-stone-900">
          {running ? 'Recherche…' : 'Chercher'}
        </button>
      </form>
      {error && <p role="alert" className="text-red-600">{error}</p>}
      {running && (
        <ul className="text-sm text-stone-500">
          {events.map((e, i) =>
            e.type === 'source' ? <li key={i}>{`${e.source} : ${e.error ?? `${e.fares} tarifs`} (${e.requests} req)`}</li> : null,
          )}
        </ul>
      )}
      {status?.error && <p role="alert" className="text-red-600">{status.error}</p>}
      {status?.result && <Results result={status.result} />}
    </div>
  )
}
