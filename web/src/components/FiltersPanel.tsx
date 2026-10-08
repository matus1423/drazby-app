import { useMemo } from 'react'
import { DEFAULT_FILTERS, activeCount, type Filters } from '../filters'
import { KIND_LABEL, TYPE_LABEL } from '../format'
import type { AuctionItem, Kind, PType } from '../types'

interface Props {
  filters: Filters
  items: AuctionItem[]
  onChange: (f: Filters) => void
  onClose?: () => void
  resultCount?: number
}

const TYPES: PType[] = ['byt', 'dom', 'rekreacny', 'pozemok', 'nebytovy', 'garaz', 'ine']
const KINDS: Kind[] = ['dobrovolna', 'exekucna', 'danova']

function Chip({ on, children, onClick }: { on: boolean; children: React.ReactNode; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={on}
      className={`rounded-full border px-3 py-1.5 text-sm transition ${
        on ? 'border-slate-800 bg-slate-800 text-white' : 'border-slate-300 bg-white text-slate-700 hover:border-slate-500'
      }`}
    >
      {children}
    </button>
  )
}

function toggle<T>(arr: T[], v: T): T[] {
  return arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]
}

const label = 'mb-1.5 block text-xs font-semibold uppercase tracking-wide text-slate-500'
const input =
  'w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-slate-600 focus:outline-none'

function parseNum(s: string): number | null {
  const d = s.replace(/\D/g, '')
  return d ? Number(d) : null
}

export default function FiltersPanel({ filters: f, items, onChange, onClose, resultCount }: Props) {
  const set = (patch: Partial<Filters>) => onChange({ ...f, ...patch })
  const kraje = useMemo(
    () => [...new Set(items.map((a) => a.kr).filter(Boolean) as string[])].sort((a, b) => a.localeCompare(b, 'sk')),
    [items],
  )
  const okresy = useMemo(
    () =>
      [...new Set(items.filter((a) => !f.kraj || a.kr === f.kraj).map((a) => a.ok).filter(Boolean) as string[])].sort(
        (a, b) => a.localeCompare(b, 'sk'),
      ),
    [items, f.kraj],
  )
  const n = activeCount(f)

  return (
    <div className="flex flex-col gap-5 p-4">
      <div>
        <span className={label}>Kedy</span>
        <div className="flex flex-wrap gap-2">
          <Chip on={f.when === 'upcoming'} onClick={() => set({ when: 'upcoming' })}>
            Nadchádzajúce
          </Chip>
          <Chip on={f.when === 'past'} onClick={() => set({ when: 'past' })}>
            Minulé a zrušené
          </Chip>
          <Chip on={f.when === 'all'} onClick={() => set({ when: 'all' })}>
            Všetky
          </Chip>
        </div>
      </div>

      <div>
        <span className={label}>Typ nehnuteľnosti</span>
        <div className="flex flex-wrap gap-2">
          {TYPES.map((t) => (
            <Chip key={t} on={f.types.includes(t)} onClick={() => set({ types: toggle(f.types, t) })}>
              {TYPE_LABEL[t]}
            </Chip>
          ))}
        </div>
      </div>

      <div>
        <span className={label}>Druh dražby</span>
        <div className="flex flex-wrap gap-2">
          {KINDS.map((k) => (
            <Chip key={k} on={f.kinds.includes(k)} onClick={() => set({ kinds: toggle(f.kinds, k) })}>
              {KIND_LABEL[k]}
            </Chip>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={label} htmlFor="kraj">
            Kraj
          </label>
          <select id="kraj" className={input} value={f.kraj} onChange={(e) => set({ kraj: e.target.value, okres: '' })}>
            <option value="">Celé Slovensko</option>
            {kraje.map((k) => (
              <option key={k}>{k}</option>
            ))}
          </select>
        </div>
        <div>
          <label className={label} htmlFor="okres">
            Okres
          </label>
          <select id="okres" className={input} value={f.okres} onChange={(e) => set({ okres: e.target.value })}>
            <option value="">Všetky</option>
            {okresy.map((o) => (
              <option key={o}>{o}</option>
            ))}
          </select>
        </div>
      </div>

      <div>
        <span className={label}>Najnižšie podanie (€)</span>
        <div className="grid grid-cols-2 gap-3">
          <input
            className={input}
            inputMode="numeric"
            placeholder="od"
            aria-label="Cena od"
            value={f.minPrice ?? ''}
            onChange={(e) => set({ minPrice: parseNum(e.target.value) })}
          />
          <input
            className={input}
            inputMode="numeric"
            placeholder="do"
            aria-label="Cena do"
            value={f.maxPrice ?? ''}
            onChange={(e) => set({ maxPrice: parseNum(e.target.value) })}
          />
        </div>
      </div>

      <div>
        <span className={label}>Dátum dražby</span>
        <div className="grid grid-cols-2 gap-3">
          <input className={input} type="date" aria-label="Dátum od" value={f.from} onChange={(e) => set({ from: e.target.value })} />
          <input className={input} type="date" aria-label="Dátum do" value={f.to} onChange={(e) => set({ to: e.target.value })} />
        </div>
      </div>

      <div>
        <span className={label}>Kolo dražby</span>
        <div className="flex flex-wrap gap-2">
          <Chip on={f.round === ''} onClick={() => set({ round: '' })}>
            Všetky
          </Chip>
          <Chip on={f.round === '1'} onClick={() => set({ round: '1' })}>
            1. kolo
          </Chip>
          <Chip on={f.round === '2+'} onClick={() => set({ round: '2+' })}>
            Opakované (nižšia cena)
          </Chip>
        </div>
      </div>

      <div className="sticky bottom-0 -mx-4 flex items-center justify-between gap-2 border-t border-slate-200 bg-white px-4 py-3">
        <button
          type="button"
          className="text-sm text-slate-600 underline disabled:opacity-40"
          disabled={n === 0}
          onClick={() => onChange({ ...DEFAULT_FILTERS, inView: f.inView, sort: f.sort })}
        >
          Zrušiť filtre{n ? ` (${n})` : ''}
        </button>
        {onClose && (
          <button type="button" className="rounded-lg bg-slate-800 px-4 py-2 text-sm font-medium text-white" onClick={onClose}>
            Zobraziť {resultCount != null ? `${resultCount} ` : ''}výsledkov
          </button>
        )}
      </div>
    </div>
  )
}
