// Petits éléments du formulaire de recherche, mis en forme une fois.

/** Une ligne du formulaire : le titre à gauche, les réglages à droite (empilés sur mobile). */
export const Row = ({ title, children }: { title: string; children: React.ReactNode }) => (
  <section className="grid gap-x-6 gap-y-2 py-5 sm:grid-cols-[7rem_1fr]">
    <h2 className="pt-1.5 text-sm font-medium">{title}</h2>
    <div className="min-w-0">{children}</div>
  </section>
)

type Choice<T> = { name: string; value: T; onChange: (v: T) => void; options: readonly (readonly [T, string])[] }

export function Segmented<T extends string | boolean>({ name, value, onChange, options }: Choice<T>) {
  return (
    <span className="inline-flex rounded-md border border-line bg-surface p-0.5 text-sm">
      {options.map(([key, label]) => (
        <label key={label} className={`cursor-pointer rounded px-3 py-1 whitespace-nowrap has-focus-visible:outline-2 has-focus-visible:outline-accent ${value === key ? 'bg-ink text-paper' : 'text-muted hover:text-ink'}`}>
          <input type="radio" name={name} checked={value === key} onChange={() => onChange(key)} className="sr-only" />
          {label}
        </label>
      ))}
    </span>
  )
}

type NumberProps = { label: string; value: number; onChange: (v: number) => void; min: number; max: number }

export function Stepper({ label, value, onChange, min, max }: NumberProps) {
  const btn = 'grid size-8 place-items-center text-muted hover:text-ink disabled:opacity-30'
  return (
    <span className="inline-flex items-center gap-3 text-sm">
      <span className="text-muted">{label}</span>
      <span className="inline-flex items-center rounded-md border border-line bg-surface">
        <button type="button" className={btn} onClick={() => onChange(value - 1)} disabled={value <= min} aria-label={`${label} : moins`}>
          −
        </button>
        <output className="w-6 text-center" aria-live="polite">
          {value}
        </output>
        <button type="button" className={btn} onClick={() => onChange(value + 1)} disabled={value >= max} aria-label={`${label} : plus`}>
          +
        </button>
      </span>
    </span>
  )
}

type Toggle = { checked: boolean; onChange: (v: boolean) => void; label: string; hint: string }

export const Switch = ({ checked, onChange, label, hint }: Toggle) => (
  <label className="flex cursor-pointer items-start gap-3 text-sm">
    <input type="checkbox" role="switch" checked={checked} onChange={(e) => onChange(e.target.checked)} className="peer sr-only" />
    <span className="relative mt-0.5 h-5 w-9 shrink-0 rounded-full bg-line transition-colors peer-checked:bg-accent peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-accent peer-checked:*:translate-x-4">
      <span className="absolute top-0.5 left-0.5 size-4 rounded-full bg-paper shadow-sm transition-transform motion-reduce:transition-none" />
    </span>
    <span>
      {label}
      <span className="block text-xs text-muted">{hint}</span>
    </span>
  </label>
)

export const SourceToggle = ({ checked, onChange, label, hint }: Toggle) => (
  <label className="flex cursor-pointer items-center gap-2.5 rounded-md border border-line bg-surface px-3 py-2 text-sm has-checked:border-accent has-checked:bg-accent-soft has-focus-visible:outline-2 has-focus-visible:outline-accent">
    <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="sr-only" />
    <span className={`grid size-4 shrink-0 place-items-center rounded-sm border ${checked ? 'border-accent bg-accent text-paper' : 'border-muted'}`} aria-hidden="true">
      {checked && (
        <svg viewBox="0 0 12 12" className="size-3">
          <path d="M2.5 6.5l2.2 2.2 4.8-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      )}
    </span>
    <span>
      {label}
      <span className="block text-xs text-muted">{hint}</span>
    </span>
  </label>
)
