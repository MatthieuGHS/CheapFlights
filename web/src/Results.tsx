import type { Fare, Result } from './api'

const when = (iso: string) =>
  new Date(iso).toLocaleString('fr-FR', { weekday: 'short', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })

const Leg = ({ f }: { f: Fare }) => (
  <span>
    {f.origin}→{f.destination} · {when(f.departure)} · {f.airline}
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

export function Results({ result }: { result: Result }) {
  const trips = result.roundtrips.map((t) => ({
    ...t,
    total: t.out.price + t.back.price,
    nights: Math.round((Date.parse(t.back.departure.slice(0, 10)) - Date.parse(t.out.departure.slice(0, 10))) / 864e5),
  }))
  return (
    <section className="space-y-6">
      <p className="text-sm text-stone-500">
        {result.seconds.toFixed(0)} s · {result.requests} requêtes ·{' '}
        {Object.entries(result.sources)
          .map(([name, s]) => `${name}: ${s.error ? 'erreur' : `${s.fares} tarifs`}`)
          .join(' · ')}
      </p>
      <div>
        <h2 className="mb-2 text-lg font-semibold">Aller-retours</h2>
        <ul className="space-y-2">
          {trips.map((t) => (
            <li key={t.out.url! + t.back.url!} className="rounded border border-stone-300 p-3 dark:border-stone-700">
              <strong>{t.total.toFixed(2)} €</strong> · {t.nights} nuit{t.nights > 1 ? 's' : ''}
              <div className="text-sm">
                <Leg f={t.out} />
              </div>
              <div className="text-sm">
                <Leg f={t.back} />
              </div>
            </li>
          ))}
          {trips.length === 0 && <li className="text-sm text-stone-500">Aucun aller-retour trouvé.</li>}
        </ul>
      </div>
      <div>
        <h2 className="mb-2 text-lg font-semibold">Allers simples</h2>
        <ul className="space-y-1 text-sm">
          {result.oneways.map((f) => (
            <li key={f.url! + f.departure}>
              <strong>{f.price.toFixed(2)} €</strong> · <Leg f={f} />
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}
