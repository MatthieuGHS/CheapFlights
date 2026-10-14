import { useEffect, useState } from 'react'
import { getConfig, saveDefaults, startSearch, type Config, type Defaults } from './api'

const WEEKDAYS = ['lun', 'mar', 'mer', 'jeu', 'ven', 'sam', 'dim']

/** Date locale (pas UTC : à Vilnius, toISOString() donne la veille entre minuit et 3 h). */
function isoDay(offsetDays: number): string {
  const d = new Date()
  d.setDate(d.getDate() + offsetDays)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

type Props = { running: boolean; onStarted: (id: string) => void }

export function SearchForm({ running, onStarted }: Props) {
  const [config, setConfig] = useState<Config | null>(null)
  const [preset, setPreset] = useState<string | null>(null)
  const [form, setForm] = useState<Defaults | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    getConfig()
      .then((c) => {
        setConfig(c)
        setForm(c.defaults)
      })
      .catch((e: unknown) => setError(String(e)))
  }, [])

  if (!config || !form) return <p className="text-sm text-stone-500">{error ?? 'Chargement…'}</p>

  const choosePreset = (name: string | null) => {
    setPreset(name)
    setForm(name ? config.presets[name] : config.defaults)
  }
  const set = <K extends keyof Defaults>(key: K, value: Defaults[K]) => {
    setForm({ ...form, [key]: value })
    setSaved(false)
  }
  const toggle = (list: number[] | null, value: number) => {
    const next = list?.includes(value) ? list.filter((v) => v !== value) : [...(list ?? []), value]
    return next.length ? next.sort() : null
  }

  const launch = async () => {
    setError(null)
    const { start_offset_days, window_days, ...options } = form
    const overrides = {
      ...options,
      date_from: isoDay(start_offset_days),
      date_to: isoDay(start_offset_days + window_days),
    }
    try {
      onStarted((await startSearch({ preset, overrides })).id)
    } catch (e) {
      setError(String(e))
    }
  }

  // Seuls les écarts aux défauts sont écrits : config.yaml reste la référence pour le reste.
  const keep = async () => {
    const base = new Map(Object.entries(config.defaults))
    const changed = Object.fromEntries(
      Object.entries(form).filter(([key, value]) => JSON.stringify(value) !== JSON.stringify(base.get(key))),
    )
    try {
      setConfig(await saveDefaults(changed))
      setSaved(true)
    } catch (e) {
      setError(String(e))
    }
  }

  return (
    <section className="rounded-lg border border-stone-200 bg-white p-4 shadow-sm dark:border-stone-800 dark:bg-stone-900">
      <div className="mb-4 flex flex-wrap gap-2">
        {[null, ...Object.keys(config.presets)].map((name) => (
          <button
            key={name ?? 'default'}
            onClick={() => choosePreset(name)}
            className={`rounded-full border px-3 py-1 text-sm ${preset === name ? 'border-sky-600 bg-sky-600 text-white' : 'border-stone-300 dark:border-stone-700'}`}
          >
            {name ?? "N'importe quand"}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-4 text-sm md:grid-cols-4">
        <Field label="Origines">
          <div className="flex gap-2">
            {config.origins.map((o) => (
              <label key={o} className="flex items-center gap-1">
                <input
                  type="checkbox"
                  checked={form.origins.includes(o)}
                  onChange={() =>
                    set('origins', form.origins.includes(o) ? form.origins.filter((x) => x !== o) : [...form.origins, o])
                  }
                />
                {o}
              </label>
            ))}
          </div>
        </Field>
        <NumberField label="Départ dans (jours)" value={form.start_offset_days} onChange={(v) => set('start_offset_days', v)} />
        <NumberField label="Fenêtre (jours)" value={form.window_days} onChange={(v) => set('window_days', v)} />
        <NumberField label="Nuits max" value={form.max_nights} onChange={(v) => set('max_nights', v)} />
        <NumberField label="Sur place min (h)" value={form.min_on_site_hours} onChange={(v) => set('min_on_site_hours', v)} />
        <NumberField label="Correspondance min (h)" value={form.min_connection_hours} onChange={(v) => set('min_connection_hours', v)} />
        <NumberField label="Escale max (h)" value={form.max_layover_hours} onChange={(v) => set('max_layover_hours', v)} />
        <NumberField label="Résultats" value={form.top_k} onChange={(v) => set('top_k', v)} />
        <Field label="Prix max (€)">
          <input
            type="number"
            className="input"
            value={form.max_total_price ?? ''}
            onChange={(e) => set('max_total_price', e.target.value === '' ? null : Number(e.target.value))}
          />
        </Field>
        <Field label="Options">
          <label className="flex items-center gap-1">
            <input type="checkbox" checked={form.allow_self_transfer} onChange={(e) => set('allow_self_transfer', e.target.checked)} />
            self-transfer
          </label>
          <label className="flex items-center gap-1">
            <input type="checkbox" checked={form.allow_open_jaw} onChange={(e) => set('allow_open_jaw', e.target.checked)} />
            open-jaw
          </label>
        </Field>
        <Field label="Départ le">
          <Weekdays value={form.depart_weekdays} onToggle={(d) => set('depart_weekdays', toggle(form.depart_weekdays, d))} />
        </Field>
        <Field label="Retour le">
          <Weekdays value={form.return_weekdays} onToggle={(d) => set('return_weekdays', toggle(form.return_weekdays, d))} />
        </Field>
        <Field label="Rentré avant">
          <div className="flex gap-1">
            <select
              className="input"
              value={form.return_deadline?.weekday ?? ''}
              onChange={(e) =>
                set('return_deadline', {
                  at: form.return_deadline?.at ?? '12:00:00',
                  weekday: e.target.value === '' ? null : Number(e.target.value),
                })
              }
            >
              <option value="">le jour même</option>
              {WEEKDAYS.map((d, i) => (
                <option key={d} value={i}>
                  {d}
                </option>
              ))}
            </select>
            <input
              type="time"
              className="input"
              value={form.return_deadline?.at.slice(0, 5) ?? ''}
              onChange={(e) =>
                set(
                  'return_deadline',
                  e.target.value ? { at: `${e.target.value}:00`, weekday: form.return_deadline?.weekday ?? null } : null,
                )
              }
            />
          </div>
        </Field>
        <Field label="Indisponible (cours, exams)" wide>
          <Blackouts value={form.blackout} onChange={(b) => set('blackout', b)} />
        </Field>
      </div>

      <div className="mt-4 flex items-center gap-3">
        <button
          onClick={() => void launch()}
          disabled={running || form.origins.length === 0}
          className="rounded bg-sky-600 px-4 py-2 font-medium text-white disabled:opacity-50"
        >
          {running ? 'Recherche en cours…' : 'Lancer'}
        </button>
        <button
          onClick={() => void keep()}
          disabled={preset !== null}
          title={preset !== null ? 'Un preset est actif : ses valeurs ne remplacent pas les défauts' : undefined}
          className="text-sm text-stone-600 underline disabled:opacity-40 dark:text-stone-400"
        >
          {saved ? 'Enregistré comme défauts' : 'Enregistrer comme défauts'}
        </button>
        <span className="text-xs text-stone-500">budget : {config.request_budget} requêtes</span>
        {error && <span className="text-sm text-red-600">{error}</span>}
      </div>
    </section>
  )
}

function Field({ label, children, wide }: { label: string; children: React.ReactNode; wide?: boolean }) {
  return (
    <label className={`flex flex-col gap-1 ${wide ? 'col-span-2' : ''}`}>
      <span className="text-xs font-medium uppercase tracking-wide text-stone-500">{label}</span>
      {children}
    </label>
  )
}

function NumberField({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  return (
    <Field label={label}>
      <input type="number" className="input" value={value} onChange={(e) => onChange(Number(e.target.value))} />
    </Field>
  )
}

function Weekdays({ value, onToggle }: { value: number[] | null; onToggle: (d: number) => void }) {
  return (
    <div className="flex flex-wrap gap-1">
      {WEEKDAYS.map((d, i) => (
        <button
          type="button"
          key={d}
          onClick={() => onToggle(i)}
          className={`rounded px-1.5 py-0.5 text-xs ${value?.includes(i) ? 'bg-sky-600 text-white' : 'bg-stone-100 dark:bg-stone-800'}`}
        >
          {d}
        </button>
      ))}
    </div>
  )
}

type Blackout = Defaults['blackout'][number]

function Blackouts({ value, onChange }: { value: Blackout[]; onChange: (b: Blackout[]) => void }) {
  return (
    <div className="space-y-1">
      {value.map((b, i) => (
        <div key={i} className="flex items-center gap-1">
          <input type="datetime-local" className="input" value={b.start.slice(0, 16)} onChange={(e) => onChange(value.map((x, j) => (j === i ? { ...x, start: e.target.value } : x)))} />
          <span>→</span>
          <input type="datetime-local" className="input" value={b.end.slice(0, 16)} onChange={(e) => onChange(value.map((x, j) => (j === i ? { ...x, end: e.target.value } : x)))} />
          <button type="button" onClick={() => onChange(value.filter((_, j) => j !== i))} className="px-1 text-stone-500" aria-label="retirer">
            ×
          </button>
        </div>
      ))}
      <button
        type="button"
        className="text-xs text-sky-700 underline dark:text-sky-400"
        onClick={() => onChange([...value, { start: `${isoDay(7)}T08:00`, end: `${isoDay(7)}T18:00` }])}
      >
        + créneau
      </button>
    </div>
  )
}
