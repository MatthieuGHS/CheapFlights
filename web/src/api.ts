import { z } from 'zod'

// Frontière avec l'API : tout ce qui arrive est validé ici, puis typé dans le reste de l'UI.

const Deadline = z.object({ at: z.string(), weekday: z.number().nullable() })
const Blackout = z.object({ start: z.string(), end: z.string() })

export const SearchOptions = z.object({
  home: z.string(),
  origins: z.array(z.string()),
  max_nights: z.number(),
  min_on_site_hours: z.number(),
  return_deadline: Deadline.nullable(),
  depart_weekdays: z.array(z.number()).nullable(),
  return_weekdays: z.array(z.number()).nullable(),
  blackout: z.array(Blackout),
  max_total_price: z.number().nullable(),
  allow_self_transfer: z.boolean(),
  max_stops_per_direction: z.number(),
  min_connection_hours: z.number(),
  max_layover_hours: z.number(),
  allow_open_jaw: z.boolean(),
  top_k: z.number(),
})
export type SearchOptions = z.infer<typeof SearchOptions>

const Defaults = SearchOptions.extend({ start_offset_days: z.number(), window_days: z.number() })
export type Defaults = z.infer<typeof Defaults>

const Config = z.object({
  defaults: Defaults,
  presets: z.record(z.string(), Defaults),
  request_budget: z.number(),
})
export type Config = z.infer<typeof Config>

const Segment = z.object({
  source: z.string(),
  origin: z.string(),
  destination: z.string(),
  day: z.string(),
  price_eur: z.number(),
  departure: z.string().nullable(),
  arrival: z.string().nullable(),
  flight_no: z.string().nullable(),
  booking_url: z.string().nullable(),
  fetched_at: z.string().nullable(),
})
export type Segment = z.infer<typeof Segment>

const Trip = z.object({
  outbound: z.array(Segment),
  inbound: z.array(Segment),
  ground: z.array(
    z.object({ origin: z.string(), destination: z.string(), duration_min: z.number(), cost_eur: z.number() }),
  ),
  score: z.number(),
  total_eur: z.number(),
  nights: z.number(),
  on_site_hours: z.number().nullable(),
  badges: z.array(z.string()),
})
export type Trip = z.infer<typeof Trip>

const Status = z.object({
  id: z.string(),
  done: z.boolean(),
  error: z.string().nullable(),
  trips: z.array(Trip),
  requests: z.number().nullable(),
  budget_exhausted: z.boolean().nullable(),
  candidates: z.number().nullable(),
  pruned: z.number().nullable(),
})
export type Status = z.infer<typeof Status>

// Événements du moteur (cheaphops/search/engine.py) ; un type inconnu est gardé tel quel.
export const SearchEvent = z.discriminatedUnion('type', [
  z.object({ type: z.literal('explore'), level: z.number(), source: z.string(), routes: z.number() }),
  z.object({
    type: z.literal('progress'),
    phase: z.enum(['explore', 'verify']),
    done: z.number(),
    of: z.number(),
    source: z.string().optional(),
    level: z.number().optional(),
    requests: z.number(),
    cache_hits: z.number().optional(),
    rung: z.number().nullable().optional(),
  }),
  z.object({ type: z.literal('budget'), source: z.string(), what: z.string() }),
  z.object({
    type: z.literal('error'),
    source: z.string(),
    what: z.string(),
    error: z.string(),
    blocked: z.boolean().optional(),
  }),
  z.object({ type: z.literal('candidates'), count: z.number(), pruned: z.number() }),
  z.object({
    type: z.literal('done'),
    trips: z.number(),
    requests: z.number(),
    pruned: z.number(),
    fx_skipped: z.number(),
  }),
  z.object({ type: z.literal('finished'), error: z.string().nullable() }),
])
export type SearchEvent = z.infer<typeof SearchEvent>

const Source = z.object({
  source: z.string(),
  version: z.number(),
  status: z.string(),
  capabilities: z.array(z.string()),
  preferred_rung: z.number(),
  blocked_until: z.number().nullable(),
  blocked_reason: z.string().nullable(),
  rungs: z.array(
    z.object({
      rung: z.number(),
      successes: z.number(),
      failures: z.number(),
      browser_requests: z.number(),
      last_failure: z.string().nullable(),
    }),
  ),
})
export type Source = z.infer<typeof Source>

async function call<T>(schema: z.ZodType<T>, url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, { headers: { 'content-type': 'application/json' }, ...init })
  const body: unknown = await r.json()
  if (!r.ok) throw new Error(`${r.status} ${JSON.stringify(body)}`)
  return schema.parse(body)
}

export const getConfig = () => call(Config, '/api/config')
export const saveDefaults = (defaults: Partial<Defaults>) =>
  call(Config, '/api/config/defaults', { method: 'PUT', body: JSON.stringify(defaults) })
export const startSearch = (request: { preset: string | null; overrides: Record<string, unknown> }) =>
  call(z.object({ id: z.string() }), '/api/searches', { method: 'POST', body: JSON.stringify(request) })
export const getSearch = (id: string) => call(Status, `/api/searches/${id}`)
export const getSources = () => call(z.array(Source), '/api/sources')

/** Abonnement SSE ; renvoie la fonction de désabonnement. */
export function followSearch(id: string, onEvent: (e: SearchEvent) => void): () => void {
  const source = new EventSource(`/api/searches/${id}/events`)
  source.onmessage = (msg: MessageEvent<string>) => {
    const parsed = SearchEvent.safeParse(JSON.parse(msg.data))
    if (!parsed.success) return // événement d'une version plus récente du moteur : ignoré
    onEvent(parsed.data)
    if (parsed.data.type === 'finished') source.close()
  }
  return () => source.close()
}
