import { useId, useMemo, useRef, useState } from 'react'
import { countryName, search, type AirportIndex } from './airports'

type Props = {
  label: string
  value: string[]
  onChange: (codes: string[]) => void
  index: AirportIndex | null // null : table pas (encore) chargée, on accepte les codes tapés
  max?: number
  placeholder: string
}

/** Champ multi-aéroports : on tape une ville, un pays, un nom ou un code, on choisit dans la
 *  liste ; chaque choix devient une étiquette. Combobox ARIA, utilisable au clavier. */
export function AirportPicker({ label, value, onChange, index, max = Infinity, placeholder }: Props) {
  const id = useId()
  const input = useRef<HTMLInputElement>(null)
  const [text, setText] = useState('')
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const chosen = useMemo(() => new Set(value), [value])
  const options = useMemo(() => (index ? search(index, text, chosen) : []), [index, text, chosen])
  const full = value.length >= max
  const shown = open && !full && text.trim() !== ''

  const add = (code: string) => {
    if (!chosen.has(code) && !full) onChange([...value, code])
    setText('')
    setActive(0)
    input.current?.focus()
  }
  const remove = (code: string) => onChange(value.filter((c) => c !== code))

  const onKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      setOpen(true)
      const step = e.key === 'ArrowDown' ? 1 : -1
      setActive((i) => (options.length ? (i + step + options.length) % options.length : 0))
    } else if (e.key === 'Enter' && shown) {
      e.preventDefault() // sinon le formulaire part
      const pick = options[active]
      if (pick) add(pick.iata)
      else if (!index && /^[a-z]{3}$/i.test(text.trim())) add(text.trim().toUpperCase())
    } else if (e.key === 'Escape') {
      setOpen(false)
    } else if (e.key === 'Backspace' && text === '' && value.length) {
      remove(value[value.length - 1])
    }
  }

  return (
    <div className="relative">
      <div
        className="flex min-h-10 flex-wrap items-center gap-1.5 rounded-md border border-line bg-surface px-1.5 py-1 focus-within:border-accent"
        onClick={() => input.current?.focus()}
      >
        {value.map((code) => {
          const a = index?.byCode.get(code)
          return (
            <span key={code} className="inline-flex items-center gap-1 rounded bg-accent-soft py-0.5 pr-0.5 pl-2 text-sm" title={a ? `${a.name}, ${countryName(a.country)}` : undefined}>
              {a?.city ?? code}
              <span className="text-xs text-muted">{code}</span>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation()
                  remove(code)
                }}
                aria-label={`Retirer ${a?.city ?? code} (${code})`}
                className="grid size-5 place-items-center rounded text-muted hover:bg-line hover:text-ink"
              >
                <svg viewBox="0 0 12 12" className="size-2.5" aria-hidden="true">
                  <path d="M2 2l8 8M10 2l-8 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                </svg>
              </button>
            </span>
          )
        })}
        <input
          ref={input}
          role="combobox"
          aria-label={label}
          aria-expanded={shown}
          aria-controls={`${id}-list`}
          aria-activedescendant={shown && options[active] ? `${id}-${options[active].iata}` : undefined}
          aria-autocomplete="list"
          value={text}
          disabled={full}
          placeholder={full ? `${max} au maximum` : value.length ? 'Ajouter…' : placeholder}
          onChange={(e) => {
            setText(e.target.value)
            setActive(0)
            setOpen(true)
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setOpen(false)}
          onKeyDown={onKey}
          className="min-w-32 flex-1 bg-transparent px-1 py-0.5 text-sm outline-none placeholder:text-muted disabled:cursor-not-allowed"
        />
      </div>
      {shown && (
        <ul id={`${id}-list`} role="listbox" aria-label={label} className="absolute z-20 mt-1 max-h-80 w-full min-w-72 overflow-y-auto rounded-md border border-line bg-surface py-1 shadow-lg shadow-black/20">
          {options.length === 0 && <li className="px-3 py-2 text-sm text-muted">{index ? 'Aucun aéroport ne correspond.' : 'Tapez un code à 3 lettres puis Entrée.'}</li>}
          {options.map((a, i) => (
            <li
              key={a.iata}
              id={`${id}-${a.iata}`}
              role="option"
              aria-selected={i === active}
              onMouseDown={(e) => e.preventDefault()} // garde le focus dans le champ
              onClick={() => add(a.iata)}
              onMouseEnter={() => setActive(i)}
              className={`flex cursor-pointer items-baseline gap-3 px-3 py-1.5 text-sm ${i === active ? 'bg-accent-soft' : ''}`}
            >
              <span className="min-w-0 flex-1 truncate">
                <span className="font-medium">{a.city}</span>
                <span className="text-muted">
                  {' '}
                  {a.name}, {countryName(a.country)}
                </span>
              </span>
              <span className="text-xs text-muted tabular-nums">{a.iata}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
