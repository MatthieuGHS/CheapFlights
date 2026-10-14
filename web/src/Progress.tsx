import type { SearchEvent } from './api'

type Progress = Extract<SearchEvent, { type: 'progress' }>
type Problem = Extract<SearchEvent, { type: 'error' | 'budget' }>

/** Vue condensée du flux SSE : le dernier état par source et par phase, plus les erreurs. */
export function Progress({ events }: { events: SearchEvent[] }) {
  const latest = new Map<string, Progress>()
  const problems: Problem[] = []
  let candidates: number | null = null
  let done: Extract<SearchEvent, { type: 'done' }> | null = null
  let finished: Extract<SearchEvent, { type: 'finished' }> | null = null
  for (const e of events) {
    switch (e.type) {
      case 'progress':
        latest.set(`${e.phase}·${e.level ?? ''}·${e.source ?? 'toutes'}`, e)
        break
      case 'error':
      case 'budget':
        problems.push(e)
        break
      case 'candidates':
        candidates = e.count
        break
      case 'done':
        done = e
        break
      case 'finished':
        finished = e
        break
      case 'explore':
        break
      default: {
        const unexpected: never = e
        return unexpected
      }
    }
  }

  return (
    <section className="rounded-lg border border-stone-200 bg-white p-4 text-sm shadow-sm dark:border-stone-800 dark:bg-stone-900">
      <h2 className="mb-2 font-semibold">Progression</h2>
      <table className="w-full text-left">
        <thead className="text-xs uppercase text-stone-500">
          <tr>
            <th>phase</th>
            <th>source</th>
            <th>avancement</th>
            <th>requêtes</th>
            <th>cache</th>
            <th>rung</th>
          </tr>
        </thead>
        <tbody>
          {[...latest.values()].map((p) => (
            <tr key={`${p.phase}${p.level}${p.source}`} className="border-t border-stone-100 dark:border-stone-800">
              <td>
                {p.phase === 'explore' ? `Explore${p.level === 2 ? ' (hubs)' : ''}` : 'Verify'}
              </td>
              <td>{p.source ?? '—'}</td>
              <td>
                <progress className="mr-2 align-middle" value={p.done} max={p.of} /> {p.done}/{p.of}
              </td>
              <td>{p.requests}</td>
              <td>{p.cache_hits ?? '—'}</td>
              <td>{p.rung ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {candidates !== null && <p className="mt-2 text-stone-600 dark:text-stone-400">{candidates} paires candidates</p>}
      {done && (
        <p className="text-stone-600 dark:text-stone-400">
          {done.trips} voyages · {done.requests} requêtes · {done.pruned} paires écartées par la borne
          {done.fx_skipped > 0 && ` · ${done.fx_skipped} tarifs hors euro ignorés (taux BCE indisponible)`}
        </p>
      )}
      {finished?.error && <p className="mt-2 text-red-600">Échec : {finished.error}</p>}
      {problems.length > 0 && (
        <details className="mt-2">
          <summary className="cursor-pointer text-amber-700 dark:text-amber-400">{problems.length} incidents</summary>
          <ul className="mt-1 max-h-40 overflow-auto text-xs">
            {problems.map((p, i) => (
              <li key={i}>
                {p.source} · {p.what}
                {p.type === 'error' ? ` · ${p.error}${p.blocked ? ' (source bloquée)' : ''}` : ' · budget atteint'}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  )
}
