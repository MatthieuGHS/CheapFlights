import { useEffect, useState } from 'react'
import { getHistory, getSaved, type HistoryEntry, type Saved } from './api'
import { periodLabel } from './dates'
import { Results } from './Results'

const stamp = (at: string) =>
  new Date(at).toLocaleString('fr-FR', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })

/** Top 10 sauvegardé d'une recherche, avec la date des prix : ils ont pu changer depuis. */
export function SavedView({ saved, title }: { saved: Saved; title: string }) {
  return (
    <div className="mt-10">
      <p className="rounded-md bg-accent-soft px-4 py-3 text-sm text-accent">
        {title}, prix relevés le {stamp(saved.at)}. Ils ont pu changer depuis : vérifiez avant de réserver.
      </p>
      <Results key={saved.id} result={saved.result} />
    </div>
  )
}

const when = (e: HistoryEntry) =>
  e.periods.length ? e.periods.map(periodLabel).join(', ') : `${e.days} prochains jours`

export function History({ id }: { id: string | null }) {
  const [entries, setEntries] = useState<HistoryEntry[] | null>(null)
  const [saved, setSaved] = useState<Saved | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (id) getSaved(id).then(setSaved, (e: unknown) => setError(String(e)))
    else getHistory().then(setEntries, (e: unknown) => setError(String(e)))
  }, [id])

  if (error)
    return (
      <p role="alert" className="mt-6 rounded-md bg-warn-soft px-4 py-3 text-sm text-warn">
        {error}
      </p>
    )
  if (id)
    return (
      <>
        <a href="#historique" className="text-sm text-accent hover:underline">
          ‹ Toutes les recherches
        </a>
        {saved?.id === id && <SavedView saved={saved} title="Recherche sauvegardée" />}
      </>
    )
  if (!entries) return null
  if (entries.length === 0)
    return <p className="text-muted">Aucune recherche sauvegardée. Chaque recherche terminée garde ici son top 10.</p>
  return (
    <ul className="divide-y divide-line border-y border-line">
      {entries.map((e) => (
        <li key={e.id}>
          <a href={`#historique/${e.id}`} className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-0.5 py-3 hover:bg-accent-soft sm:grid-cols-[11rem_1fr_auto]">
            <span className="text-muted">{stamp(e.at)}</span>
            <span className="col-start-1 sm:col-start-auto">
              {when(e)}
              <span className="text-muted">
                {' '}
                depuis {e.origins.join(', ')}
                {e.weekend && ', week-end'}
              </span>
            </span>
            <span className="row-span-2 self-center text-right sm:row-span-1">
              {e.best !== null ? (
                <>
                  <span className="font-medium">dès {Math.round(e.best)} €</span>
                  <span className="block text-xs text-muted">{e.count} aller-retours</span>
                </>
              ) : (
                <span className="text-muted">aucun aller-retour</span>
              )}
            </span>
          </a>
        </li>
      ))}
    </ul>
  )
}
