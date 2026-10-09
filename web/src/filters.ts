import type { AuctionItem, Kind, PType } from './types'

export type When = 'upcoming' | 'past' | 'all'
export type Sort = 'date' | 'price_asc' | 'price_desc' | 'discount' | 'new'

export interface Filters {
  q: string
  kraj: string
  okres: string
  types: PType[]
  kinds: Kind[]
  minPrice: number | null
  maxPrice: number | null
  when: When
  round: '' | '1' | '2+'
  from: string
  to: string
  sort: Sort
  inView: boolean
}

export const DEFAULT_FILTERS: Filters = {
  q: '',
  kraj: '',
  okres: '',
  types: [],
  kinds: [],
  minPrice: null,
  maxPrice: null,
  when: 'upcoming',
  round: '',
  from: '',
  to: '',
  sort: 'date',
  inView: false,
}

const norm = (s: string) =>
  s
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')

// stav sa počíta pri exporte dát; medzi nočnými behmi ho doplníme podľa dnešného dátumu
const today = () => new Date().toLocaleDateString('sv-SE')
export const isActive = (a: AuctionItem) =>
  (a.s === 'pripravovana' || a.s === 'odrocena') && (!a.d || a.d.slice(0, 10) >= today())

export function applyFilters(items: AuctionItem[], f: Filters, bounds?: [number, number, number, number] | null) {
  const q = norm(f.q.trim())
  const words = q ? q.split(/\s+/) : []
  const out = items.filter((a) => {
    if (f.kraj && a.kr !== f.kraj) return false
    if (f.okres && a.ok !== f.okres) return false
    if (f.types.length && !f.types.includes(a.t)) return false
    if (f.kinds.length && !f.kinds.includes(a.k)) return false
    const price = a.mb ?? a.av
    if (f.minPrice != null && (price == null || price < f.minPrice)) return false
    if (f.maxPrice != null && (price == null || price > f.maxPrice)) return false
    if (f.when === 'upcoming' && !isActive(a)) return false
    if (f.when === 'past' && isActive(a)) return false
    const d = (a.d || '').slice(0, 10)
    if (f.from && (!d || d < f.from)) return false
    if (f.to && (!d || d > f.to)) return false
    if (f.round === '1' && (a.r ?? 1) !== 1) return false
    if (f.round === '2+' && (a.r ?? 1) < 2) return false
    if (words.length) {
      const hay = norm([a.ti, a.ob, a.ok, a.kr, a.au].filter(Boolean).join(' '))
      if (!words.every((w) => hay.includes(w))) return false
    }
    if (f.inView && bounds) {
      if (a.lat == null || a.lng == null) return false
      const [w, s, e, n] = bounds
      if (a.lng < w || a.lng > e || a.lat < s || a.lat > n) return false
    }
    return true
  })
  const disc = (a: AuctionItem) => (a.mb && a.av && a.av > a.mb ? 1 - a.mb / a.av : 0)
  const sorters: Record<Sort, (a: AuctionItem, b: AuctionItem) => number> = {
    date: (a, b) =>
      f.when === 'past' ? (b.d || '').localeCompare(a.d || '') : (a.d || '9').localeCompare(b.d || '9'),
    price_asc: (a, b) => (a.mb ?? a.av ?? 1e12) - (b.mb ?? b.av ?? 1e12),
    price_desc: (a, b) => (b.mb ?? b.av ?? -1) - (a.mb ?? a.av ?? -1),
    discount: (a, b) => disc(b) - disc(a),
    new: (a, b) => b.fs.localeCompare(a.fs) || a.id.localeCompare(b.id),
  }
  return out.sort(sorters[f.sort])
}

/** Filtre ↔ adresa (#kraj=…&typ=byt,dom) – aby sa dali poslať odkazom. */
export function filtersToQuery(f: Filters): string {
  const p = new URLSearchParams()
  if (f.q) p.set('q', f.q)
  if (f.kraj) p.set('kraj', f.kraj)
  if (f.okres) p.set('okres', f.okres)
  if (f.types.length) p.set('typ', f.types.join(','))
  if (f.kinds.length) p.set('druh', f.kinds.join(','))
  if (f.minPrice != null) p.set('od', String(f.minPrice))
  if (f.maxPrice != null) p.set('do', String(f.maxPrice))
  if (f.when !== DEFAULT_FILTERS.when) p.set('kedy', f.when)
  if (f.round) p.set('kolo', f.round)
  if (f.from) p.set('datum_od', f.from)
  if (f.to) p.set('datum_do', f.to)
  if (f.sort !== DEFAULT_FILTERS.sort) p.set('zoradit', f.sort)
  return p.toString()
}

export function queryToFilters(qs: string): Filters {
  const p = new URLSearchParams(qs)
  const num = (k: string) => {
    const v = p.get(k)
    return v && !isNaN(Number(v)) ? Number(v) : null
  }
  return {
    ...DEFAULT_FILTERS,
    q: p.get('q') || '',
    kraj: p.get('kraj') || '',
    okres: p.get('okres') || '',
    types: (p.get('typ') || '').split(',').filter(Boolean) as PType[],
    kinds: (p.get('druh') || '').split(',').filter(Boolean) as Kind[],
    minPrice: num('od'),
    maxPrice: num('do'),
    when: (p.get('kedy') as When) || DEFAULT_FILTERS.when,
    round: (p.get('kolo') as Filters['round']) || '',
    from: p.get('datum_od') || '',
    to: p.get('datum_do') || '',
    sort: (p.get('zoradit') as Sort) || DEFAULT_FILTERS.sort,
  }
}

export function activeCount(f: Filters): number {
  let n = 0
  if (f.q) n++
  if (f.kraj) n++
  if (f.okres) n++
  if (f.types.length) n++
  if (f.kinds.length) n++
  if (f.minPrice != null || f.maxPrice != null) n++
  if (f.when !== DEFAULT_FILTERS.when) n++
  if (f.round) n++
  if (f.from || f.to) n++
  return n
}
