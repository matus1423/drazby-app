import { useEffect, useState } from 'react'
import { KIND_LABEL, STATUS_LABEL, TYPE_COLOR, date, discount, money, relDays } from '../format'
import { isActive } from '../filters'
import type { AuctionItem } from '../types'

interface Props {
  items: AuctionItem[]
  selectedId: string | null
  onSelect: (id: string) => void
}

const PAGE = 60

export default function AuctionList({ items, selectedId, onSelect }: Props) {
  const [shown, setShown] = useState(PAGE)
  useEffect(() => setShown(PAGE), [items])

  if (!items.length) {
    return (
      <div className="p-8 text-center text-slate-500">
        <p className="font-medium">Žiadne dražby nezodpovedajú filtrom.</p>
        <p className="mt-1 text-sm">Skúste zmeniť obdobie alebo zrušiť niektorý filter.</p>
      </div>
    )
  }

  return (
    <ul className="divide-y divide-slate-100">
      {items.slice(0, shown).map((a) => (
        <li key={a.id}>
          <Card a={a} selected={a.id === selectedId} onClick={() => onSelect(a.id)} />
        </li>
      ))}
      {shown < items.length && (
        <li className="p-4 text-center">
          <button
            type="button"
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm hover:bg-slate-50"
            onClick={() => setShown((s) => s + PAGE)}
          >
            Zobraziť ďalšie ({items.length - shown})
          </button>
        </li>
      )}
    </ul>
  )
}

function Card({ a, selected, onClick }: { a: AuctionItem; selected: boolean; onClick: () => void }) {
  const disc = discount(a.mb, a.av)
  const active = isActive(a)
  return (
    <button
      type="button"
      onClick={onClick}
      className={`block w-full px-4 py-3 text-left transition hover:bg-slate-50 ${selected ? 'bg-amber-50' : ''}`}
    >
      <div className="flex items-start gap-3">
        <span className="mt-1.5 h-3 w-3 shrink-0 rounded-full" style={{ background: TYPE_COLOR[a.t] }} aria-hidden />
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-2">
            <h3 className="truncate font-semibold text-slate-900">
              {a.t === 'ine' && !a.ob ? `Dražba – ${a.au || 'bez údajov o predmete'}` : a.ti}
            </h3>
            <span className="shrink-0 font-semibold tabular-nums text-slate-900">{money(a.mb ?? a.av)}</span>
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-slate-600">
            <span>{a.ok ? `okres ${a.ok}` : a.kr || 'miesto neuvedené'}</span>
            <span aria-hidden>·</span>
            <span>
              {date(a.d)}
              {active && a.d ? <span className="text-slate-400"> ({relDays(a.d)})</span> : null}
            </span>
          </div>
          <div className="mt-1.5 flex flex-wrap gap-1.5 text-xs">
            <span className="rounded bg-slate-100 px-1.5 py-0.5 text-slate-700">{KIND_LABEL[a.k]}</span>
            {(a.r ?? 1) > 1 && <span className="rounded bg-sky-100 px-1.5 py-0.5 text-sky-800">{a.r}. kolo</span>}
            {disc != null && disc >= 5 && (
              <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-emerald-800">−{disc} % zo znaleckej ceny</span>
            )}
            {!active && (
              <span
                className={`rounded px-1.5 py-0.5 ${
                  a.s === 'zrusena' || a.s === 'zmarena' || a.s === 'neplatna'
                    ? 'bg-rose-100 text-rose-800'
                    : 'bg-slate-200 text-slate-700'
                }`}
              >
                {STATUS_LABEL[active ? a.s : a.s === 'pripravovana' || a.s === 'odrocena' ? 'prebehla' : a.s]}
                {a.hb ? ` · vydražené za ${money(a.hb)}` : ''}
              </span>
            )}
            {a.s === 'odrocena' && <span className="rounded bg-amber-100 px-1.5 py-0.5 text-amber-800">Odročená</span>}
            {a.lat == null && <span className="rounded bg-slate-100 px-1.5 py-0.5 text-slate-500">bez polohy</span>}
          </div>
        </div>
      </div>
    </button>
  )
}
