import { useState } from 'react'
import type { Bus, Calendar, Fare, Result, RoundTrip } from './api'

const when = (f: Fare) => {
  const d = new Date(f.departure)
  const day = d.toLocaleDateString('fr-FR', { weekday: 'short', day: '2-digit', month: '2-digit' })
  // les sources « au jour » (Wizz, Kayak) n'ont pas d'heure : minuit, on ne l'affiche pas
  return d.getHours() === 0 && d.getMinutes() === 0
    ? day
    : `${day} ${d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}`
}

const Badge = ({ indicative }: { indicative: boolean }) => (
  <span
    className={`ml-1 rounded px-1.5 py-0.5 text-xs ${indicative ? 'bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-100' : 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-100'}`}
    title={indicative ? "Prix d'un agrégateur, non vérifié chez la compagnie" : 'Prix lu chez la compagnie'}
  >
    {indicative ? 'prix indicatif' : 'vérifié'}
  </span>
)

const Leg = ({ f }: { f: Fare }) => (
  <span>
    {f.origin}→{f.destination} · {when(f)} · {f.airline}{' '}
    <span className="text-stone-500">[{f.source}]</span>
    <Badge indicative={f.indicative} />
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

const total = (t: RoundTrip) => t.out.price + t.back.price // vols seulement
const hours = (b: Bus) => `${Math.floor(b.minutes / 60)} h ${String(b.minutes % 60).padStart(2, '0')}`
const BusInfo = ({ b }: { b: Bus }) =>
  b.cost > 0 ? (
    <span className="text-stone-500">
      bus : {b.cost.toFixed(0)} € · {hours(b)} (hors total)
    </span>
  ) : null
const nights = (t: RoundTrip) =>
  Math.round((Date.parse(t.back.departure.slice(0, 10)) - Date.parse(t.out.departure.slice(0, 10))) / 864e5)

/** Prix par jour, aller (ligne du haut) et retour : le moins cher en vert. */
function MiniCalendar({ cal }: { cal: Calendar }) {
  const cells = [...cal.out, ...cal.back]
  if (cells.length === 0) return null
  const days: string[] = []
  const sorted = cells.map((c) => c.day).sort()
  const start = new Date(sorted[0]!)
  const end = new Date(sorted.at(-1)!)
  for (let d = start; d <= end; d = new Date(d.getTime() + 864e5)) days.push(d.toISOString().slice(0, 10))
  const cheapest = Math.min(...cells.map((c) => c.price))
  const row = (label: string, list: Calendar['out']) => (
    <tr>
      <th className="pr-2 text-left font-normal text-stone-500">{label}</th>
      {days.map((d) => {
        const c = list.find((x) => x.day === d)
        const cheap = c !== undefined && c.price <= cheapest * 1.25
        return (
          <td
            key={d}
            title={c ? `${c.origin} · ${c.indicative ? 'indicatif' : 'vérifié'}` : 'aucun vol'}
            className={`px-1 text-center ${c ? (cheap ? 'bg-emerald-100 dark:bg-emerald-900' : '') : 'text-stone-300'} ${c?.indicative ? 'italic' : ''}`}
          >
            {c ? c.price.toFixed(0) : '·'}
          </td>
        )
      })}
    </tr>
  )
  return (
    <div className="mt-2 overflow-x-auto text-xs">
      <table>
        <thead>
          <tr>
            <th />
            {days.map((d) => (
              <th key={d} className="px-1 font-normal text-stone-500">
                {d.slice(8)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {row('aller', cal.out)}
          {row('retour', cal.back)}
        </tbody>
      </table>
    </div>
  )
}

function Trip({ t }: { t: RoundTrip }) {
  return (
    <>
      <strong>{total(t).toFixed(2)} €</strong> vols · {nights(t)} nuit{nights(t) > 1 ? 's' : ''}
      <Badge indicative={t.out.indicative || t.back.indicative} />
      {t.check_return && (
        <span className="ml-1 rounded bg-sky-100 px-1.5 py-0.5 text-xs text-sky-800 dark:bg-sky-900 dark:text-sky-100">
          heure de retour à vérifier
        </span>
      )}
      <span className="ml-3 text-sm">
        <BusInfo b={t.bus} />
      </span>
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
      <nav role="tablist" className="flex gap-1 text-sm">
        {(
          [
            ['roundtrips', `Aller-retours (${result.roundtrips.length})`],
            ['oneways', `Allers simples (${result.oneways.length})`],
            ['deals', `Bons plans (${result.deals.length})`],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            role="tab"
            aria-selected={view === key}
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
                {result.calendars[t.out.destination] && (
                  <MiniCalendar cal={result.calendars[t.out.destination]!} />
                )}
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
              className="input ml-1 w-24"
            />{' '}
            <span className="text-stone-500">{oneways.length} vols</span>
          </label>
          <ul className="space-y-1 text-sm">
            {oneways.map((f) => (
              <li key={f.source + f.origin + f.destination + f.departure + f.price}>
                <strong>{f.price.toFixed(2)} €</strong> · <Leg f={f} />
                {result.bus[f.origin] && (
                  <span className="ml-3">
                    <BusInfo b={result.bus[f.origin]!} />
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {view === 'deals' && (
        <ul className="space-y-1 text-sm">
          {result.deals.map((d, i) => (
            <li key={i}>
              <strong>{d.price.toFixed(0)} €</strong> <Badge indicative={d.indicative} /> · {d.origin}→
              {d.destination} ·{' '}
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
