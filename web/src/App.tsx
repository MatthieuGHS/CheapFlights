import { useEffect, useState } from 'react'
import { followSearch, getSearch, type SearchEvent, type Status } from './api'
import { Health } from './Health'
import { Progress } from './Progress'
import { Results } from './Results'
import { SearchForm } from './SearchForm'

type Tab = 'search' | 'health'

export default function App() {
  const [tab, setTab] = useState<Tab>('search')
  const [runId, setRunId] = useState<string | null>(null)
  const [events, setEvents] = useState<SearchEvent[]>([])
  const [status, setStatus] = useState<Status | null>(null)

  const start = (id: string) => {
    setEvents([])
    setStatus(null)
    setRunId(id)
  }

  useEffect(() => {
    if (!runId) return
    return followSearch(runId, (e) => {
      setEvents((prev) => [...prev, e])
      if (e.type === 'finished') void getSearch(runId).then(setStatus)
    })
  }, [runId])

  return (
    <div className="mx-auto max-w-6xl px-4 py-6">
      <header className="mb-6 flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Cheap Hops</h1>
        <nav className="flex gap-1 text-sm">
          {(
            [
              ['search', 'Recherche'],
              ['health', 'Santé des sources'],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={`rounded px-3 py-1.5 ${tab === key ? 'bg-stone-900 text-white dark:bg-stone-100 dark:text-stone-900' : 'hover:bg-stone-200 dark:hover:bg-stone-800'}`}
            >
              {label}
            </button>
          ))}
        </nav>
      </header>
      {tab === 'search' ? (
        <main className="space-y-6">
          <SearchForm running={runId !== null && status === null} onStarted={start} />
          {runId && <Progress events={events} />}
          {status && <Results status={status} />}
        </main>
      ) : (
        <Health />
      )}
    </div>
  )
}
