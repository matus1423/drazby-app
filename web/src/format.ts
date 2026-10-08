import type { Kind, PType, Status } from './types'

export const KIND_LABEL: Record<Kind, string> = {
  dobrovolna: 'Dobrovoľná',
  exekucna: 'Exekučná',
  danova: 'Daňová',
}

export const STATUS_LABEL: Record<Status, string> = {
  pripravovana: 'Pripravovaná',
  odrocena: 'Odročená',
  prebehla: 'Prebehla',
  zrusena: 'Zrušená',
  zmarena: 'Zmarená',
  neplatna: 'Neplatná',
}

export const TYPE_LABEL: Record<PType, string> = {
  byt: 'Byt',
  dom: 'Rodinný dom',
  rekreacny: 'Chata / rekreačný',
  pozemok: 'Pozemok',
  nebytovy: 'Nebytový priestor',
  garaz: 'Garáž',
  ine: 'Iné',
}

export const TYPE_COLOR: Record<PType, string> = {
  byt: '#2563eb',
  dom: '#16a34a',
  rekreacny: '#0d9488',
  pozemok: '#ca8a04',
  nebytovy: '#9333ea',
  garaz: '#64748b',
  ine: '#64748b',
}

export const FIELD_LABEL: Record<string, string> = {
  auction_at: 'Dátum dražby',
  round: 'Kolo',
  min_bid: 'Najnižšie podanie',
  appraised_value: 'Znalecká cena',
  deposit: 'Zábezpeka',
  venue: 'Miesto konania',
  status: 'Stav',
  highest_bid: 'Najvyššie podanie',
  auction_number: 'Číslo dražby',
}

const eur = new Intl.NumberFormat('sk-SK', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 })

export function money(v: number | null | undefined): string {
  return v == null ? '—' : eur.format(v)
}

export function moneyShort(v: number | null | undefined): string {
  if (v == null) return ''
  if (v >= 1_000_000) return `${(v / 1_000_000).toLocaleString('sk-SK', { maximumFractionDigits: 2 })} mil. €`
  if (v >= 10_000) return `${Math.round(v / 1000).toLocaleString('sk-SK')} tis. €`
  return eur.format(v)
}

export function date(iso: string | null | undefined, withTime = false): string {
  if (!iso) return '—'
  const d = new Date(iso.length === 10 ? iso + 'T00:00:00' : iso)
  if (isNaN(d.getTime())) return iso
  const s = d.toLocaleDateString('sk-SK', { day: 'numeric', month: 'numeric', year: 'numeric' })
  if (withTime && iso.length > 10)
    return `${s} o ${d.toLocaleTimeString('sk-SK', { hour: '2-digit', minute: '2-digit' })}`
  return s
}

export function daysUntil(iso: string | null): number | null {
  if (!iso) return null
  const d = new Date(iso.slice(0, 10) + 'T00:00:00')
  const t = new Date()
  t.setHours(0, 0, 0, 0)
  return Math.round((d.getTime() - t.getTime()) / 86400000)
}

export function relDays(iso: string | null): string {
  const n = daysUntil(iso)
  if (n == null) return ''
  if (n === 0) return 'dnes'
  if (n === 1) return 'zajtra'
  if (n > 1 && n < 5) return `o ${n} dni`
  if (n >= 5) return `o ${n} dní`
  if (n === -1) return 'včera'
  return `pred ${-n} dňami`
}

export function discount(min: number | null, appraised: number | null): number | null {
  if (!min || !appraised || appraised <= 0 || min >= appraised) return null
  return Math.round((1 - min / appraised) * 100)
}
