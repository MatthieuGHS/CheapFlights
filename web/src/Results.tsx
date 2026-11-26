import { createContext, useContext, useState } from 'react'
import type { Bus, Calendar, Fare, Result, RoundTrip } from './api'
import { periodLabel } from './dates'

const Cities = createContext<Record<string, string>>({})

/** Ville, code IATA en retrait ; le code seul si la ville est inconnue (codes ville Kayak). */
function Place({ code }: { code: string }) {
  const city = useContext(Cities)[code]
  return city ? (
    <span title={code}>
      {city} <span className="text-xs text-muted">{code}</span>
    </span>
  ) : (
    <span>{code}</span>
  )
}

const eur = new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR' })
const eur0 = new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 })

const when = (f: Fare) => {
  const d = new Date(f.departure)
  const day = d.toLocaleDateString('fr-FR', { weekday: 'short', day: 'numeric', month: 'short' })
  // les sources « au jour » (Wizz, Kayak) n'ont pas d'heure : minuit, on ne l'affiche pas
  return d.getHours() === 0 && d.getMinutes() === 0
    ? day
    : `${day}, ${d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}`
}

/** Seul le prix d'agrégateur est signalé : le prix lu chez la compagnie est la norme. */
const Indicative = ({ source }: { source: string }) => (
  <span
    className="rounded bg-warn-soft px-1.5 py-0.5 text-xs whitespace-nowrap text-warn"
    title="Prix vu sur un agrégateur, pas encore vérifié chez la compagnie"
  >
    prix indicatif, {source}
  </span>
)

const Book = ({ url, label = 'Réserver' }: { url: string | null; label?: string }) =>
  url ? (
    <a href={url} target="_blank" rel="noreferrer" className="text-accent underline-offset-2 hover:underline">
      {label}
    </a>
  ) : null

/** Une réservation par billet : une correspondance en a deux. */
const Links = ({ f }: { f: Fare }) =>
  f.legs.length ? (
    <span className="flex gap-2 whitespace-nowrap">
      <Book url={f.legs[0]!.url} label="Vol 1" />
      <Book url={f.legs[1]!.url} label="Vol 2" />
    </span>
  ) : (
    <Book url={f.url} />
  )

const minutes = (m: number) => `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')}`

/** Escale d'une correspondance, et le risque : deux billets, aucune garantie si le premier vol a du retard. */
function Via({ f }: { f: Fare }) {
  const [a, b] = f.legs
  if (!a || !b || !a.arrival) return null
  const wait = Math.round((Date.parse(b.departure) - Date.parse(a.arrival)) / 6e4)
  return (
    <span className="block text-xs text-muted">
      via <Place code={a.destination} />, escale {minutes(wait)}{' '}
      <span
        className="rounded bg-warn-soft px-1.5 py-0.5 whitespace-nowrap text-warn"
        title="Deux billets séparés : si le premier vol a du retard, la compagnie ne garantit pas le second"
      >
        correspondance non protégée
      </span>
    </span>
  )
}

/** Une jambe alignée en colonnes : date, trajet, puis compagnie et lien (en dessous sur mobile). */
const Leg = ({ f, note }: { f: Fare; note?: string }) => (
  <div className="grid grid-cols-[1fr_auto] items-baseline gap-x-3 text-sm sm:grid-cols-[9.5rem_12rem_1fr]">
    <span className="text-muted">{when(f)}</span>
    <span>
      <Place code={f.origin} /> → <Place code={f.destination} />
      <Via f={f} />
    </span>
    <span className="col-span-2 flex flex-wrap items-center gap-x-2 gap-y-1 sm:col-span-1">
      {note ?? f.airline}
      {f.indicative && !note && <Indicative source={f.source} />}
      {!note && (
        <span className="ml-auto">
          <Links f={f} />
        </span>
      )}
    </span>
  </div>
)

const total = (t: RoundTrip) => t.out.price + t.back.price // vols seulement
const busText = (b: Bus) => `Bus en plus : ${eur0.format(b.cost)}, ${minutes(b.minutes)}`
const nights = (t: RoundTrip) =>
  Math.round((Date.parse(t.back.departure.slice(0, 10)) - Date.parse(t.out.departure.slice(0, 10))) / 864e5)

/** Prix par jour, aller puis retour ; les jours proches du moins cher sont teintés. */
function MiniCalendar({ cal }: { cal: Calendar }) {
  const cells = [...cal.out, ...cal.back]
  if (cells.length === 0) return null
  const days: string[] = []
  const sorted = cells.map((c) => c.day).sort()
  const start = new Date(sorted[0]!)
  const end = new Date(sorted.at(-1)!)
  for (let d = start; d <= end; d = new Date(d.getTime() + 864e5)) days.push(d.toISOString().slice(0, 10))
  const row = (label: string, list: Calendar['out'], cheapest = Math.min(...list.map((c) => c.price))) => (
    <tr>
      <th scope="row" className="pr-3 text-left font-normal text-muted">
        {label}
      </th>
      {days.map((d) => {
        const c = list.find((x) => x.day === d)
        const cheap = c !== undefined && c.price <= cheapest * 1.25
        return (
          <td
            key={d}
            title={c ? `${c.origin}${c.indicative ? ', prix indicatif' : ''}` : 'Aucun vol'}
            className={`min-w-9 px-1 py-0.5 text-center ${c ? (cheap ? 'bg-accent-soft font-medium text-accent' : '') : 'text-line'} ${c?.indicative ? 'italic' : ''}`}
          >
            {c ? Math.round(c.price) : '–'}
          </td>
        )
      })}
    </tr>
  )
  return (
    <div className="mt-3 overflow-x-auto text-xs">
      <table className="border-separate border-spacing-0.5">
        <caption className="sr-only">Prix par jour en euros</caption>
        <thead>
          <tr>
            <th />
            {days.map((d) => (
              <th key={d} scope="col" className="px-1 font-normal text-muted">
                {new Date(d).toLocaleDateString('fr-FR', { day: 'numeric' })}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {row('Aller', cal.out)}
          {row('Retour', cal.back)}
        </tbody>
      </table>
    </div>
  )
}

function TripLegs({ t }: { t: RoundTrip }) {
  return (
    <div className="space-y-2 sm:space-y-1">
      <Leg f={t.out} />
      {t.bundled ? <Leg f={t.back} note="Inclus dans le tarif aller-retour" /> : <Leg f={t.back} />}
      <p className="flex flex-wrap gap-x-4 text-xs text-muted">
        <span>
          {nights(t)} nuit{nights(t) > 1 ? 's' : ''}
        </span>
        {t.check_return && <span className="text-warn">Vérifiez l'heure d'arrivée du retour</span>}
        {t.bus.cost > 0 && <span>{busText(t.bus)}</span>}
      </p>
    </div>
  )
}

function Destination({ code }: { code: string }) {
  const city = useContext(Cities)[code]
  return (
    <div className="sm:row-span-2">
      <div className="text-xl leading-tight font-semibold text-accent">{city ?? code}</div>
      {city && <div className="text-xs tracking-wide text-muted">{code}</div>}
    </div>
  )
}

function Trip({ t, others, cal }: { t: RoundTrip; others: RoundTrip[]; cal?: Calendar }) {
  return (
    <li className="grid grid-cols-[5.5rem_1fr] gap-x-4 py-5 sm:grid-cols-[7rem_8rem_1fr]">
      <div className="text-xl font-semibold">{eur.format(total(t))}</div>
      <Destination code={t.out.destination} />
      <div className="col-span-2 mt-2 sm:col-span-1 sm:col-start-3 sm:row-start-1 sm:mt-0">
        <TripLegs t={t} />
        {cal && <MiniCalendar cal={cal} />}
        {others.length > 0 && (
          <details className="mt-3 text-sm">
            <summary className="cursor-pointer text-accent">
              {others.length} autre{others.length > 1 ? 's' : ''} date{others.length > 1 ? 's' : ''}
            </summary>
            <ul className="mt-2 divide-y divide-line">
              {others.map((a) => (
                <li key={a.out.departure + a.back.departure + a.out.origin + a.out.source} className="flex gap-4 py-3">
                  <span className="w-20 shrink-0 font-medium">{eur.format(total(a))}</span>
                  <div className="min-w-0 flex-1">
                    <TripLegs t={a} />
                  </div>
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </li>
  )
}

const VIEWS = [
  ['roundtrips', 'Aller-retours'],
  ['oneways', 'Allers simples'],
  ['deals', 'Bons plans'],
] as const
type View = (typeof VIEWS)[number][0]

export function Results({ result }: { result: Result }) {
  const [view, setView] = useState<View>('roundtrips')
  const [shown, setShown] = useState(0) // plage affichée
  const period = result.periods[Math.min(shown, result.periods.length - 1)]!
  const [maxPrice, setMaxPrice] = useState('')
  const limit = maxPrice === '' ? Infinity : Number(maxPrice)
  const oneways = result.oneways.filter((f) => f.price <= limit).sort((a, b) => a.price - b.price)
  const counts: Record<View, number> = {
    roundtrips: result.periods.reduce((n, p) => n + p.roundtrips.length, 0),
    oneways: result.oneways.length,
    deals: result.deals.length,
  }
  const failed = Object.entries(result.sources).filter(([, s]) => s.error)

  return (
    <Cities.Provider value={result.cities}>
    <section className="mt-10">
      <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm text-muted">
        <p>
          Recherche faite en {result.seconds.toFixed(0)} s, {result.requests} requêtes.
        </p>
        <details className="text-right">
          <summary className={`cursor-pointer ${failed.length ? 'text-warn' : ''}`}>
            {failed.length ? `${failed.length} source${failed.length > 1 ? 's' : ''} en échec` : 'Détail des sources'}
          </summary>
          <ul className="mt-2 space-y-0.5 text-left">
            {Object.entries(result.sources).map(([name, s]) => (
              <li key={name} className="flex gap-3">
                <span className="w-32 text-ink">{name}</span>
                {s.error ? <span className="text-warn">{s.error}</span> : <span>{s.fares} tarifs</span>}
              </li>
            ))}
          </ul>
        </details>
      </div>

      <nav role="tablist" className="mt-4 flex gap-6 border-b border-line text-sm">
        {VIEWS.map(([key, label]) => (
          <button
            key={key}
            role="tab"
            aria-selected={view === key}
            onClick={() => setView(key)}
            className={`-mb-px border-b-2 pb-2.5 ${view === key ? 'border-accent font-medium text-ink' : 'border-transparent text-muted hover:text-ink'}`}
          >
            {label} <span className="text-muted">{counts[key]}</span>
          </button>
        ))}
      </nav>

      {view === 'roundtrips' && (
        <div role="tabpanel">
          {result.periods.length > 1 && (
            <div className="flex flex-wrap gap-2 pt-4" role="group" aria-label="Plage affichée">
              {result.periods.map((p, i) => (
                <button
                  key={p.start}
                  type="button"
                  aria-pressed={p === period}
                  onClick={() => setShown(i)}
                  className={`rounded-full border px-3 py-1 text-sm ${p === period ? 'border-accent bg-accent-soft text-accent' : 'border-line text-muted hover:text-ink'}`}
                >
                  {periodLabel(p)} <span className="opacity-70">{p.roundtrips.length}</span>
                </button>
              ))}
            </div>
          )}
          <ul className="divide-y divide-line">
            {period.roundtrips.map((t) => (
              <Trip
                key={t.out.destination}
                t={t}
                others={(period.alternatives[t.out.destination] ?? []).slice(1)}
                cal={period.calendars[t.out.destination]}
              />
            ))}
            {period.roundtrips.length === 0 && (
              <li className="py-8 text-muted">
                Aucun aller-retour sur {result.periods.length > 1 ? 'cette plage' : 'ces dates'}. Essayez plus de jours ou
                plus de nuits.
              </li>
            )}
          </ul>
        </div>
      )}

      {view === 'oneways' && (
        <div role="tabpanel" className="pt-4">
          <label className="flex items-center gap-2 text-sm">
            <span className="text-muted">Prix max</span>
            <input
              type="number"
              min={0}
              value={maxPrice}
              onChange={(e) => setMaxPrice(e.target.value)}
              className="input w-24"
              placeholder="€"
            />
            <span className="text-muted">{oneways.length} vols</span>
          </label>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-muted">
                <tr className="border-b border-line">
                  <th className="py-2 pr-4 font-normal">Prix</th>
                  <th className="py-2 pr-4 font-normal">Trajet</th>
                  <th className="py-2 pr-4 font-normal">Départ</th>
                  <th className="py-2 pr-4 font-normal">Compagnie</th>
                  <th className="py-2 font-normal">
                    <span className="sr-only">Lien</span>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {oneways.map((f) => (
                  <tr key={f.source + f.origin + f.destination + f.departure + f.price}>
                    <td className="py-2 pr-4 font-medium whitespace-nowrap">{eur.format(f.price)}</td>
                    <td className="py-2 pr-4 whitespace-nowrap">
                      <Place code={f.origin} /> → <Place code={f.destination} />
                      <Via f={f} />
                    </td>
                    <td className="py-2 pr-4 whitespace-nowrap text-muted">{when(f)}</td>
                    <td className="py-2 pr-4">
                      <span className="flex flex-wrap items-center gap-2">
                        {f.airline}
                        {f.indicative && <Indicative source={f.source} />}
                        {result.bus[f.origin] && <span className="text-xs text-muted">{busText(result.bus[f.origin]!)}</span>}
                      </span>
                    </td>
                    <td className="py-2 text-right">
                      <Links f={f} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {view === 'deals' && (
        <ul role="tabpanel" className="divide-y divide-line text-sm">
          {result.deals.map((d, i) => (
            <li key={i} className="flex flex-wrap items-baseline gap-x-4 gap-y-1 py-3">
              <span className="w-20 font-medium">{eur0.format(d.price)}</span>
              <span className="w-56">
                <Place code={d.origin} /> → <Place code={d.destination} />
              </span>
              <span className="flex-1 text-muted">{d.when ?? 'Dates libres'}</span>
              <a href={d.url} target="_blank" rel="noreferrer" className="text-accent underline-offset-2 hover:underline">
                Voir sur {d.source}
              </a>
            </li>
          ))}
          {result.deals.length === 0 && <li className="py-8 text-muted">Aucun bon plan sans date pour l'instant.</li>}
        </ul>
      )}
    </section>
    </Cities.Provider>
  )
}
