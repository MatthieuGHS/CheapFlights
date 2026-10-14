import { useEffect, useState } from 'react'
import { getSources, type Source } from './api'

export function Health() {
  const [sources, setSources] = useState<Source[] | null>(null)
  const [loadedAt, setLoadedAt] = useState(0)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    getSources()
      .then((s) => {
        setSources(s)
        setLoadedAt(Date.now())
      })
      .catch((e: unknown) => setError(String(e)))
  }, [])
  if (!sources) return <p className="text-sm text-stone-500">{error ?? 'Chargement…'}</p>
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {sources.map((s) => {
        const tries = s.rungs.reduce((n, r) => n + r.successes + r.failures, 0)
        const ok = s.rungs.reduce((n, r) => n + r.successes, 0)
        const blocked = s.blocked_until !== null && s.blocked_until * 1000 > loadedAt
        return (
          <section key={s.source} className="rounded-lg border border-stone-200 bg-white p-4 text-sm shadow-sm dark:border-stone-800 dark:bg-stone-900">
            <h2 className="flex items-baseline justify-between font-semibold">
              {s.source} <span className="text-xs font-normal text-stone-500">v{s.version} · {s.status}</span>
            </h2>
            <p className={blocked ? 'text-red-600' : 'text-emerald-700 dark:text-emerald-400'}>
              {blocked ? `bloquée jusqu'à ${new Date((s.blocked_until ?? 0) * 1000).toLocaleTimeString('fr-FR')} (${s.blocked_reason})` : 'disponible'}
            </p>
            <p className="text-stone-600 dark:text-stone-400">
              rung préféré {s.preferred_rung} · {s.capabilities.join(', ')} · succès {tries ? Math.round((100 * ok) / tries) : 0} % sur {tries}
            </p>
            <table className="mt-2 w-full text-left text-xs">
              <thead className="uppercase text-stone-500">
                <tr>
                  <th>rung</th>
                  <th>succès</th>
                  <th>échecs</th>
                  <th>ressources navigateur</th>
                  <th>dernier échec</th>
                </tr>
              </thead>
              <tbody>
                {s.rungs.map((r) => (
                  <tr key={r.rung} className="border-t border-stone-100 dark:border-stone-800">
                    <td>{r.rung}</td>
                    <td>{r.successes}</td>
                    <td>{r.failures}</td>
                    <td>{r.browser_requests}</td>
                    <td className="max-w-48 truncate" title={r.last_failure ?? ''}>
                      {r.last_failure ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )
      })}
    </div>
  )
}
