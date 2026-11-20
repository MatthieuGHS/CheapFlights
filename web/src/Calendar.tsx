import { useState } from 'react'
import { between, iso, parse, periodLabel, toPeriods } from './dates'

const WEEKDAYS = ['lu', 'ma', 'me', 'je', 've', 'sa', 'di']

/** Jours affichés pour un mois, semaine commençant le lundi ; null pour les cases vides. */
function monthGrid(year: number, month: number): (string | null)[] {
  const first = new Date(year, month, 1)
  const blanks = (first.getDay() + 6) % 7
  const count = new Date(year, month + 1, 0).getDate()
  return [...Array<null>(blanks).fill(null), ...Array.from({ length: count }, (_, i) => iso(new Date(year, month, i + 1)))]
}

type Props = {
  selected: Set<string>
  onChange: (next: Set<string>) => void
  today: string
  last: string // dernier jour sélectionnable (horizon)
}

/** Sélection en deux clics : le premier jour fixe l'ancre, le second applique à toute la plage
 * l'état inverse de l'ancre (ajoute si elle était libre, retire si elle était choisie). */
export function Calendar({ selected, onChange, today, last }: Props) {
  const [offset, setOffset] = useState(0) // mois affiché à gauche, relatif au mois courant
  const [anchor, setAnchor] = useState<string | null>(null)
  const [hover, setHover] = useState<string | null>(null)
  const start = parse(today)
  const lastMonth = (parse(last).getFullYear() - start.getFullYear()) * 12 + parse(last).getMonth() - start.getMonth()
  const preview = new Set(anchor && hover ? between(anchor, hover) : [])
  const adding = anchor !== null && !selected.has(anchor)

  const click = (day: string) => {
    if (anchor === null) return setAnchor(day)
    const next = new Set(selected)
    for (const d of between(anchor, day)) {
      if (d < today || d > last) continue
      if (adding) next.add(d)
      else next.delete(d)
    }
    onChange(next)
    setAnchor(null)
  }

  const month = (k: number) => {
    const first = new Date(start.getFullYear(), start.getMonth() + offset + k, 1)
    const label = first.toLocaleDateString('fr-FR', { month: 'long', year: 'numeric' })
    return (
      <div key={k} className="min-w-0 flex-1 sm:max-w-72">
        <p className="mb-2 text-sm font-medium first-letter:uppercase">{label}</p>
        <div role="grid" aria-label={label} className="grid grid-cols-7 gap-0.5 text-center text-sm">
          {WEEKDAYS.map((w) => (
            <span key={w} className="pb-1 text-xs text-muted">
              {w}
            </span>
          ))}
          {monthGrid(first.getFullYear(), first.getMonth()).map((day, i) => {
            if (!day) return <span key={`b${i}`} />
            const off = day < today || day > last
            const on = selected.has(day)
            const pending = preview.has(day) && !off
            const tone = pending
              ? adding
                ? 'bg-accent-soft text-accent ring-1 ring-accent ring-inset'
                : 'bg-paper text-muted line-through ring-1 ring-line ring-inset'
              : on
                ? 'bg-accent text-surface'
                : 'hover:bg-accent-soft'
            return (
              <button
                key={day}
                type="button"
                disabled={off}
                aria-pressed={on}
                aria-label={parse(day).toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long' })}
                onClick={() => click(day)}
                onMouseEnter={() => setHover(day)}
                onFocus={() => setHover(day)}
                className={`h-9 rounded-md tabular-nums disabled:text-line disabled:hover:bg-transparent ${tone} ${day === anchor ? 'outline-2 outline-offset-1 outline-accent' : ''} ${day === today ? 'font-semibold' : ''}`}
              >
                {parse(day).getDate()}
              </button>
            )
          })}
        </div>
      </div>
    )
  }

  const periods = toPeriods(selected)
  return (
    <div className="w-full" onKeyDown={(e) => e.key === 'Escape' && setAnchor(null)} onMouseLeave={() => setHover(null)}>
      <div className="mb-3 flex items-center justify-between text-sm">
        <p className="text-muted">
          {anchor
            ? adding
              ? 'Cliquez le dernier jour à ajouter (Échap pour annuler).'
              : 'Cliquez le dernier jour à retirer (Échap pour annuler).'
            : 'Cliquez le premier jour d’une plage, puis le dernier. Recommencez sur des jours choisis pour les retirer.'}
        </p>
        <span className="flex shrink-0 gap-1">
          <button type="button" aria-label="Mois précédent" disabled={offset === 0} onClick={() => setOffset(offset - 1)} className="rounded-md px-2 py-1 hover:bg-accent-soft disabled:opacity-30">
            ‹
          </button>
          <button type="button" aria-label="Mois suivant" disabled={offset + 1 >= lastMonth} onClick={() => setOffset(offset + 1)} className="rounded-md px-2 py-1 hover:bg-accent-soft disabled:opacity-30">
            ›
          </button>
        </span>
      </div>
      <div className="flex flex-col gap-6 sm:flex-row sm:gap-12">{[0, 1].map(month)}</div>
      <div className="mt-4 flex flex-wrap items-baseline gap-x-4 gap-y-1 text-sm">
        {periods.length ? (
          <p>
            <span className="text-muted">{periods.length > 1 ? `${periods.length} plages : ` : 'Plage : '}</span>
            {periods.map(periodLabel).join(', ')}
          </p>
        ) : (
          <p className="text-muted">Aucun jour choisi.</p>
        )}
        {selected.size > 0 && (
          <button type="button" onClick={() => onChange(new Set())} className="text-accent hover:underline">
            Tout effacer
          </button>
        )}
      </div>
    </div>
  )
}
