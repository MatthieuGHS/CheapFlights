import { z } from 'zod'

// Frontière avec l'API : tout ce qui arrive est validé ici, puis typé dans le reste de l'UI.

export const Config = z.object({
  origins: z.array(z.string()),
  optional_origins: z.array(z.string()),
  days: z.number(),
  google: z.object({ enabled: z.boolean() }),
  max_nights: z.number(),
  top: z.number(),
  request_budget: z.number(),
})
export type Config = z.infer<typeof Config>

const Fare = z.object({
  source: z.string(),
  airline: z.string(),
  origin: z.string(),
  destination: z.string(),
  departure: z.string(),
  price: z.number(),
  flight_no: z.string().nullable(),
  url: z.string().nullable(),
  indicative: z.boolean(),
})
export type Fare = z.infer<typeof Fare>

const Bus = z.object({ cost: z.number(), minutes: z.number() })
export type Bus = z.infer<typeof Bus>

export const RoundTrip = z.object({
  out: Fare,
  back: Fare,
  bus: Bus,
  bundled: z.boolean(),
})
export type RoundTrip = z.infer<typeof RoundTrip>

const Cell = z.object({ day: z.string(), price: z.number(), origin: z.string(), indicative: z.boolean() })
const Calendar = z.object({ out: z.array(Cell), back: z.array(Cell) })
export type Calendar = z.infer<typeof Calendar>

const Result = z.object({
  oneways: z.array(Fare),
  deals: z.array(
    z.object({
      source: z.string(),
      title: z.string(),
      origin: z.string(),
      destination: z.string(),
      price: z.number(),
      url: z.string(),
      when: z.string().nullable(),
      airline: z.string().nullable(),
      indicative: z.boolean(),
    }),
  ),
  roundtrips: z.array(RoundTrip),
  alternatives: z.record(z.string(), z.array(RoundTrip)),
  bus: z.record(z.string(), Bus),
  calendars: z.record(z.string(), Calendar),
  requests: z.number(),
  seconds: z.number(),
  sources: z.record(
    z.string(),
    z.object({ requests: z.number(), fares: z.number(), seconds: z.number(), error: z.string().nullable() }),
  ),
})
export type Result = z.infer<typeof Result>

const Status = z.object({
  id: z.string(),
  done: z.boolean(),
  error: z.string().nullable(),
  result: Result.nullable(),
})
export type Status = z.infer<typeof Status>

// Événements de cheaphops/lastminute/run.py. Un événement hors contrat est signalé en console.
export const SearchEvent = z.discriminatedUnion('type', [
  z.object({
    type: z.literal('source'),
    source: z.string(),
    fares: z.number(),
    requests: z.number(),
    error: z.string().nullable(),
  }),
  z.object({ type: z.literal('finished'), requests: z.number(), seconds: z.number() }),
  z.object({ type: z.literal('done'), error: z.string().nullable() }),
])
export type SearchEvent = z.infer<typeof SearchEvent>

async function call<T>(schema: z.ZodType<T>, url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, { headers: { 'content-type': 'application/json' }, ...init })
  const body: unknown = await r.json()
  if (!r.ok) throw new Error(`${r.status} ${JSON.stringify(body)}`)
  return schema.parse(body)
}

export const getConfig = () => call(Config, '/api/config')
export const startSearch = (request: { days: number; origins: string[]; max_nights: number; google: boolean }) =>
  call(z.object({ id: z.string() }), '/api/searches', { method: 'POST', body: JSON.stringify(request) })
export const getSearch = (id: string) => call(Status, `/api/searches/${id}`)

/** Abonnement SSE ; renvoie la fonction de désabonnement. Une coupure devient un événement
 * `done` en erreur : l'UI ne reste jamais bloquée. */
export function followSearch(id: string, onEvent: (e: SearchEvent) => void): () => void {
  const source = new EventSource(`/api/searches/${id}/events`)
  source.onmessage = (msg: MessageEvent<string>) => {
    const parsed = SearchEvent.safeParse(JSON.parse(msg.data))
    if (!parsed.success) {
      console.error('événement hors contrat', msg.data, parsed.error)
      return
    }
    onEvent(parsed.data)
    if (parsed.data.type === 'done') source.close()
  }
  source.onerror = () => {
    source.close()
    onEvent({ type: 'done', error: 'connexion au serveur perdue' })
  }
  return () => source.close()
}
