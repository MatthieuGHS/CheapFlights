// Jours en ISO local (AAAA-MM-JJ) : jamais toISOString, qui décale d'un jour selon le fuseau.

export const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

export const parse = (day: string) => {
  const [y, m, d] = day.split('-').map(Number)
  return new Date(y!, m! - 1, d!)
}

export const addDays = (day: string, n: number) => {
  const d = parse(day)
  d.setDate(d.getDate() + n)
  return iso(d)
}

/** Jours de `a` à `b` inclus, dans l'ordre, quel que soit l'ordre des bornes. */
export function between(a: string, b: string): string[] {
  const [lo, hi] = a <= b ? [a, b] : [b, a]
  const out: string[] = []
  for (let d = lo; d <= hi; d = addDays(d, 1)) out.push(d)
  return out
}

/** Jours sélectionnés -> plages : chaque suite de jours consécutifs en est une. */
export function toPeriods(days: Iterable<string>): { start: string; end: string }[] {
  const out: { start: string; end: string }[] = []
  for (const d of [...days].sort()) {
    const last = out.at(-1)
    if (last && addDays(last.end, 1) === d) last.end = d
    else out.push({ start: d, end: d })
  }
  return out
}

const fmt = (day: string, opts: Intl.DateTimeFormatOptions) => parse(day).toLocaleDateString('fr-FR', opts)

/** « 20 – 26 nov. », « 30 déc. – 2 janv. », « 25 déc. » */
export function periodLabel(p: { start: string; end: string }): string {
  if (p.start === p.end) return fmt(p.start, { day: 'numeric', month: 'short' })
  const sameMonth = p.start.slice(0, 7) === p.end.slice(0, 7)
  return `${fmt(p.start, sameMonth ? { day: 'numeric' } : { day: 'numeric', month: 'short' })} – ${fmt(p.end, { day: 'numeric', month: 'short' })}`
}
