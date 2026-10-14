import { useState } from 'react'
import type { Segment, Status, Trip } from './api'

const euro = (v: number) => `${v.toFixed(2)} €`
const dayLabel = (iso: string) =>
  new Date(`${iso}T12:00`).toLocaleDateString('fr-FR', { weekday: 'short', day: '2-digit', month: '2-digit' })
// L'heure locale de l'aéroport est dans la chaîne ISO : on l'affiche telle quelle.
const clock = (iso: string) => iso.slice(11, 16)

export function Results({ status }: { status: Status }) {
  const [open, setOpen] = useState<number | null>(null)
  if (status.error || !status.result) return <p className="text-red-600">La recherche a échoué : {status.error}</p>
  const { trips } = status.result
  if (trips.length === 0) return <p className="text-stone-500">Aucun voyage ne respecte les contraintes.</p>
  return (
    <section className="overflow-x-auto rounded-lg border border-stone-200 bg-white shadow-sm dark:border-stone-800 dark:bg-stone-900">
      <table className="w-full text-left text-sm">
        <thead className="text-xs uppercase text-stone-500">
          <tr className="[&>th]:px-3 [&>th]:py-2">
            <th>#</th>
            <th>destination</th>
            <th className="text-right">prix total</th>
            <th>dates</th>
            <th className="text-right">nuits</th>
            <th className="text-right">sur place</th>
            <th className="text-right">segments</th>
            <th>badges</th>
          </tr>
        </thead>
        <tbody>
          {trips.map((t, i) => (
            <TripRows key={i} rank={i + 1} trip={t} open={open === i} onToggle={() => setOpen(open === i ? null : i)} />
          ))}
        </tbody>
      </table>
    </section>
  )
}

function TripRows({ rank, trip, open, onToggle }: { rank: number; trip: Trip; open: boolean; onToggle: () => void }) {
  const first = trip.outbound[0]
  const last = trip.inbound[trip.inbound.length - 1]
  return (
    <>
      <tr onClick={onToggle} className="cursor-pointer border-t border-stone-100 hover:bg-stone-50 dark:border-stone-800 dark:hover:bg-stone-800 [&>td]:px-3 [&>td]:py-2">
        <td>{rank}</td>
        <td className="font-medium">{trip.outbound[trip.outbound.length - 1].destination}</td>
        <td className="text-right font-semibold">
          {euro(trip.total_eur)}
          {trip.score !== trip.total_eur && <span className="block text-xs font-normal text-stone-500">score {euro(trip.score)}</span>}
        </td>
        <td>
          {first && dayLabel(first.day)} → {last && dayLabel(last.day)}
        </td>
        <td className="text-right">{trip.nights}</td>
        <td className="text-right">{trip.on_site_hours === null ? '?' : `${Math.round(trip.on_site_hours)} h`}</td>
        <td className="text-right">{trip.outbound.length + trip.inbound.length}</td>
        <td className="space-x-1">
          {trip.badges.map((b) => (
            <span key={b} className="rounded bg-amber-100 px-1.5 py-0.5 text-xs text-amber-900 dark:bg-amber-900 dark:text-amber-100">
              {b}
            </span>
          ))}
        </td>
      </tr>
      {open && (
        <tr className="bg-stone-50 dark:bg-stone-950">
          <td colSpan={8} className="px-6 py-3">
            <ul className="space-y-1 text-sm">
              {trip.ground.map((g, i) => (
                  <li key={`g${i}`} className="text-stone-600 dark:text-stone-400">
                    trajet sol {g.origin} → {g.destination} · {g.duration_min} min · {euro(g.cost_eur)}
                  </li>
                ))}
              {[...trip.outbound, ...trip.inbound].map((s, i) => (
                <SegmentLine key={i} s={s} />
              ))}
            </ul>
          </td>
        </tr>
      )}
    </>
  )
}

function SegmentLine({ s }: { s: Segment }) {
  const when = s.departure && s.arrival ? `${dayLabel(s.day)} ${clock(s.departure)} → ${clock(s.arrival)}` : `${dayLabel(s.day)}, horaire inconnu`
  const age = s.fetched_at ? `vérifié à ${new Date(s.fetched_at).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}` : 'prix du calendrier'
  return (
    <li className="flex flex-wrap items-baseline gap-x-3">
      <span className="w-16 text-xs uppercase text-stone-500">{s.source}</span>
      <span className="w-14 font-mono text-xs">{s.flight_no ?? ''}</span>
      <span className="font-medium">
        {s.origin} → {s.destination}
      </span>
      <span>{when}</span>
      <span className="font-semibold">{euro(s.price_eur)}</span>
      <span className="text-xs text-stone-500">{age}</span>
      {s.booking_url && (
        <a href={s.booking_url} target="_blank" rel="noreferrer" className="text-sky-700 underline dark:text-sky-400">
          réserver
        </a>
      )}
    </li>
  )
}
