import { useState } from 'react'
import type { Fare, Result, RoundTrip } from './api'

const when = (f: Fare) => {
  const d = new Date(f.departure)
  const day = d.toLocaleDateString('fr-FR', { weekday: 'short', day: '2-digit', month: '2-digit' })
  // les sources « au jour » (Wizz, Kayak) n'ont pas d'heure : minuit, on ne l'affiche pas
  return d.getHours() === 0 && d.getMinutes() === 0
    ? day
    : `${day} ${d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}`
}

const Leg = ({ f }: { f: Fare }) => (
  <span>
    {f.origin}→{f.destination} · {when(f)} · {f.airline}{' '}
    <span className="text-stone-500">[{f.source}]</span>
    {f.url && (
      <>
        {' '}
        <a href={f.url} target="_blank" rel="noreferrer" className="underline">
          réserver
        </a>
      </>
    )}
  </span>
)

const total = (t: RoundTrip) => t.out.price + t.back.price + t.ground
const nights = (t: RoundTrip) =>
  Math.round((Date.parse(t.back.departure.slice(0, 10)) - Date.parse(t.out.departure.slice(0, 10))) / 864e5)

function Trip({ t }: { t: RoundTrip }) {
  return (
    <>
      <strong>{total(t).toFixed(2)} €</strong> · {nights(t)} nuit{nights(t) > 1 ? 's' : ''}
      {t.ground > 0 && <span className="text-stone-500"> (bus {t.ground.toFixed(0)} € inclus)</span>}
      <div className="text-sm">
        <Leg f={t.out} />
      </div>
      <div className="text-sm">
        {t.bundled ? (
          <span className="text-stone-500">
            retour {t.back.destination}→{t.back.origin} · {when(t.back)} (tarif aller-retour unique)
          </span>
        ) : (
          <Leg f={t.back} />
        )}
      </div>
    </>
  )
}

type View = 'roundtrips' | 'oneways' | 'deals'

export function Results({ result }: { result: Result }) {
  const [view, setView] = useState<View>('roundtrips')
  const [allDates, setAllDates] = useState(false)
  const [maxPrice, setMaxPrice] = useState('')
  const limit = maxPrice === '' ? Infinity : Number(maxPrice)
  const oneways = result.oneways.filter((f) => f.price <= limit).sort((a, b) => a.price - b.price)

  return (
    <section className="space-y-4">
      <p className="text-sm text-stone-500">
        {result.seconds.toFixed(0)} s · {result.requests} requêtes ·{' '}
        {Object.entries(result.sources)
          .map(([name, s]) => `${name}: ${s.error ? 'erreur' : `${s.fares} tarifs`}`)
          .join(' · ')}
      </p>
      <nav className="flex gap-1 text-sm">
        {(
          [
            ['roundtrips', `Aller-retours (${result.roundtrips.length})`],
            ['oneways', `Allers simples (${result.oneways.length})`],
            ['deals', `Bons plans (${result.deals.length})`],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setView(key)}
            className={`rounded px-3 py-1.5 ${view === key ? 'bg-stone-900 text-white dark:bg-stone-100 dark:text-stone-900' : 'hover:bg-stone-200 dark:hover:bg-stone-800'}`}
          >
            {label}
          </button>
        ))}
      </nav>

      {view === 'roundtrips' && (
        <div>
          <label className="mb-2 block text-sm">
            <input type="checkbox" checked={allDates} onChange={(e) => setAllDates(e.target.checked)} /> Toutes les
            dates de chaque destination
          </label>
          <ul className="space-y-2">
            {result.roundtrips.map((t) => (
              <li key={t.out.destination} className="rounded border border-stone-300 p-3 dark:border-stone-700">
                <Trip t={t} />
                {allDates && (result.alternatives[t.out.destination] ?? []).length > 1 && (
                  <ul className="mt-2 space-y-1 border-t border-stone-200 pt-2 text-sm dark:border-stone-800">
                    {result.alternatives[t.out.destination]!.slice(1).map((a) => (
                      <li key={a.out.departure + a.back.departure + a.out.origin + a.out.source}>
                        <Trip t={a} />
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
            {result.roundtrips.length === 0 && (
              <li className="text-sm text-stone-500">Aucun aller-retour trouvé.</li>
            )}
          </ul>
        </div>
      )}

      {view === 'oneways' && (
        <div>
          <label className="mb-2 block text-sm">
            Prix max (€){' '}
            <input
              type="number"
              min={0}
              value={maxPrice}
              onChange={(e) => setMaxPrice(e.target.value)}
              className="ml-1 w-24 rounded border px-2 py-1"
            />{' '}
            <span className="text-stone-500">{oneways.length} vols</span>
          </label>
          <ul className="space-y-1 text-sm">
            {oneways.map((f) => (
              <li key={f.source + f.origin + f.destination + f.departure + f.price}>
                <strong>{f.price.toFixed(2)} €</strong> · <Leg f={f} />
              </li>
            ))}
          </ul>
        </div>
      )}

      {view === 'deals' && (
        <ul className="space-y-1 text-sm">
          {result.deals.map((d) => (
            <li key={d.url}>
              <strong>{d.price.toFixed(0)} €</strong> · {d.origin}→{d.destination} ·{' '}
              <a href={d.url} target="_blank" rel="noreferrer" className="underline">
                {d.source}
              </a>
            </li>
          ))}
          {result.deals.length === 0 && <li className="text-stone-500">Aucun bon plan sans date.</li>}
        </ul>
      )}
    </section>
  )
}
