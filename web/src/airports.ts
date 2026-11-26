import type { Airport } from './api'

// Recherche d'aéroports dans la table servie par /api/airports (≈ 4 000 lignes) : un index
// normalisé construit une fois, puis un score simple par requête. Pas de dépendance.

const FR = new Intl.DisplayNames(['fr'], { type: 'region' })
const EN = new Intl.DisplayNames(['en'], { type: 'region' })

export const countryName = (code: string) => FR.of(code) ?? code

/** Minuscules sans accents ni ponctuation : « Málaga » et « malaga » se valent. */
export const normalize = (s: string) =>
  s
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()

type Entry = {
  airport: Airport
  code: string
  city: string
  words: string[] // mots du nom, de la ville et des autres noms
  countries: string[] // le pays en français et en anglais
}

export type AirportIndex = { entries: Entry[]; byCode: Map<string, Airport> }

export function buildIndex(airports: Airport[]): AirportIndex {
  const entries = airports.map((a) => ({
    airport: a,
    code: a.iata.toLowerCase(),
    city: normalize(a.city),
    words: normalize([a.city, a.name, ...a.alt].join(' ')).split(' '),
    countries: [FR.of(a.country), EN.of(a.country)].filter((n) => n !== undefined).map(normalize),
  }))
  return { entries, byCode: new Map(airports.map((a) => [a.iata, a])) }
}

const SIZE = { L: 0, M: 1, S: 2 } as const

/** Rang d'un aéroport pour la requête `q` (normalisée), plus petit = meilleur ; null : écarté. */
function rank(e: Entry, q: string): number | null {
  if (e.code === q) return 0
  if (e.city.startsWith(q)) return 1
  if (e.words.some((w) => w.startsWith(q)) || (q.includes(' ') && e.city.includes(q))) return 2
  if (e.countries.some((c) => c.startsWith(q))) return 3 // tout le pays : on choisit ensuite
  return null
}

/** Les aéroports qui répondent à la saisie : code, ville, nom ou pays ; grands aéroports d'abord
 *  à rang égal, puis par ville. */
export function search(index: AirportIndex, text: string, exclude: ReadonlySet<string>, limit = 60): Airport[] {
  const q = normalize(text)
  if (!q) return []
  const hits: { e: Entry; r: number }[] = []
  for (const e of index.entries) {
    const r = exclude.has(e.airport.iata) ? null : rank(e, q)
    if (r !== null) hits.push({ e, r })
  }
  hits.sort((a, b) => a.r - b.r || SIZE[a.e.airport.size] - SIZE[b.e.airport.size] || a.e.city.localeCompare(b.e.city))
  return hits.slice(0, limit).map((h) => h.e.airport)
}
