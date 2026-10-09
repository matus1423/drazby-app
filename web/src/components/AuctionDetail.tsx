import { useState } from 'react'
import { FIELD_LABEL, STATUS_LABEL, TYPE_LABEL, date, discount, money, relDays } from '../format'
import type { AuctionDetail as D, Status } from '../types'

interface Props {
  detail: D | null
  loading: boolean
  error: string | null
  onClose: () => void
}

const GEO_LABEL: Record<string, string> = {
  parcela: 'presne podľa parcely v katastri',
  ku: 'približne – stred katastrálneho územia',
  obec: 'približne – stred obce',
  okres: 'len okres',
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  if (v == null || v === '') return null
  return (
    <div className="grid grid-cols-[9.5rem_1fr] gap-2 py-1.5 text-sm">
      <dt className="text-slate-500">{k}</dt>
      <dd className="break-words text-slate-900">{v}</dd>
    </div>
  )
}

function fmtHist(field: string, v: string | null) {
  if (v == null) return '—'
  if (['min_bid', 'appraised_value', 'deposit', 'highest_bid'].includes(field)) return money(Number(v))
  if (field === 'auction_at') return date(v, true)
  if (field === 'status') return STATUS_LABEL[v as Status] || v
  if (field === 'round') return `${v}. kolo`
  return v
}

function statusClass(s: Status) {
  if (s === 'pripravovana') return 'bg-emerald-100 text-emerald-800'
  if (s === 'zrusena' || s === 'zmarena' || s === 'neplatna') return 'bg-rose-100 text-rose-800'
  if (s === 'odrocena') return 'bg-amber-100 text-amber-800'
  return 'bg-slate-200 text-slate-700'
}

export default function AuctionDetail({ detail: d, loading, error, onClose }: Props) {
  // stav z exportu môže byť zo včera – dražba s minulým dátumom už prebehla
  if (d && (d.status === 'pripravovana' || d.status === 'odrocena') && d.auction_at &&
      d.auction_at.slice(0, 10) < new Date().toLocaleDateString('sv-SE')) {
    d = { ...d, status: 'prebehla', status_label: STATUS_LABEL.prebehla }
  }
  const [more, setMore] = useState(false)
  const [copied, setCopied] = useState(false)
  const disc = d ? discount(d.min_bid, d.appraised_value) : null
  return (
    <div className="flex h-full flex-col bg-white">
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
        <button type="button" onClick={onClose} className="text-sm font-medium text-slate-700 hover:text-slate-900">
          ← Späť na zoznam
        </button>
        {d && (
          <button
            type="button"
            className="text-sm text-slate-600 hover:text-slate-900"
            onClick={() => {
              const url = location.href
              if (navigator.share) navigator.share({ title: document.title, url }).catch(() => {})
              else navigator.clipboard?.writeText(url).then(() => setCopied(true))
            }}
          >
            {copied ? 'Odkaz skopírovaný' : 'Zdieľať'}
          </button>
        )}
      </div>
      <div className="flex-1 overflow-y-auto">
        {loading && !d && <p className="p-6 text-slate-500">Načítavam…</p>}
        {error && <p className="p-6 text-rose-700">{error}</p>}
        {d && (
          <article className="p-4 pb-10">
            <div className="flex flex-wrap gap-1.5 text-xs">
              <span className="rounded bg-slate-800 px-2 py-0.5 text-white">{d.kind_label} dražba</span>
              <span className={`rounded px-2 py-0.5 ${statusClass(d.status)}`}>{d.status_label}</span>
              {(d.round ?? 1) > 1 && <span className="rounded bg-sky-100 px-2 py-0.5 text-sky-800">{d.round}. kolo</span>}
            </div>
            <h2 className="mt-2 text-xl font-bold leading-snug text-slate-900">
              {d.property_type_label}
              {d.obec ? `, ${d.obec}` : ''}
            </h2>
            {d.title && <p className="mt-1 text-sm text-slate-600">{d.title}</p>}

            <div className="mt-4 grid grid-cols-2 gap-3">
              <div className="rounded-xl bg-slate-50 p-3">
                <div className="text-xs text-slate-500">Najnižšie podanie</div>
                <div className="text-lg font-bold tabular-nums">{money(d.min_bid)}</div>
                {disc != null && <div className="text-xs text-emerald-700">−{disc} % zo znaleckej ceny</div>}
              </div>
              <div className="rounded-xl bg-slate-50 p-3">
                <div className="text-xs text-slate-500">Dátum dražby</div>
                <div className="text-lg font-bold">{date(d.auction_at, true)}</div>
                {(d.status === 'pripravovana' || d.status === 'odrocena') && (
                  <div className="text-xs text-slate-500">{relDays(d.auction_at)}</div>
                )}
              </div>
            </div>
            {d.highest_bid != null && (
              <p className="mt-3 rounded-lg bg-emerald-50 p-3 text-sm text-emerald-900">
                Vydražené za <strong>{money(d.highest_bid)}</strong>
              </p>
            )}
            {d.sold === false && (
              <p className="mt-3 rounded-lg bg-slate-100 p-3 text-sm">Dražba bola neúspešná – nikto neurobil podanie.</p>
            )}
            {d.reason && (d.status === 'zrusena' || d.status === 'zmarena' || d.status === 'neplatna') && (
              <p className="mt-3 rounded-lg bg-rose-50 p-3 text-sm text-rose-900">{d.reason.slice(0, 500)}</p>
            )}

            <dl className="mt-4 divide-y divide-slate-100">
              <Row k="Znalecká cena" v={d.appraised_value != null ? money(d.appraised_value) : null} />
              <Row k="Minimálne prihodenie" v={d.min_increment != null ? money(d.min_increment) : null} />
              <Row k="Dražobná zábezpeka" v={d.deposit != null ? money(d.deposit) : null} />
              <Row k="Miesto konania" v={d.venue} />
              <Row k="Obhliadky" v={d.inspection} />
              <Row
                k={d.kind === 'exekucna' ? 'Exekútor' : d.kind === 'danova' ? 'Správca dane' : 'Dražobník'}
                v={d.auctioneer_name ? `${d.auctioneer_name}${d.auctioneer_ico ? `, IČO ${d.auctioneer_ico}` : ''}` : null}
              />
              <Row k="Navrhovateľ" v={d.proposer} />
              <Row k="Notár" v={d.notary} />
              <Row k={d.kind === 'exekucna' ? 'Spisová značka' : 'Číslo dražby'} v={d.auction_number} />
              <Row k="Kraj / okres" v={[d.kraj, d.okres && `okres ${d.okres}`].filter(Boolean).join(', ') || null} />
            </dl>

            {d.properties.length > 0 && (
              <section className="mt-5">
                <h3 className="font-semibold">Predmet dražby</h3>
                {d.properties.map((p, i) => (
                  <div key={i} className="mt-2 rounded-lg border border-slate-200 p-3 text-sm">
                    <div className="font-medium">
                      {TYPE_LABEL[p.type || 'ine']}
                      {p.ku ? ` · k. ú. ${p.ku}` : ''}
                      {p.obec && p.obec !== p.ku ? ` · ${p.obec}` : ''}
                    </div>
                    <div className="mt-1 text-slate-600">
                      {[
                        p.lv.length ? `LV č. ${p.lv.join(', ')}` : null,
                        p.supisne_cislo.length ? `súp. č. ${p.supisne_cislo.join(', ')}` : null,
                        p.area_m2 ? `${String(p.area_m2).replace('.', ',')} m²` : null,
                        p.share ? `podiel ${p.share}` : null,
                      ]
                        .filter(Boolean)
                        .join(' · ')}
                    </div>
                    {p.parcels.length > 0 && (
                      <div className="mt-1 text-slate-600">
                        Parcely:{' '}
                        {p.parcels
                          .slice(0, 12)
                          .map((pc) => `${pc.register ? pc.register + ' ' : ''}${pc.number}${pc.area_m2 ? ` (${pc.area_m2} m²)` : ''}`)
                          .join(', ')}
                        {p.parcels.length > 12 ? ` a ďalších ${p.parcels.length - 12}` : ''}
                      </div>
                    )}
                    {p.geo_source && (
                      <div className="mt-1 text-xs text-slate-400">Poloha na mape: {GEO_LABEL[p.geo_source] || p.geo_source}</div>
                    )}
                  </div>
                ))}
              </section>
            )}

            {d.description && (
              <section className="mt-5">
                <h3 className="font-semibold">Text z oznámenia</h3>
                <p className={`mt-1 whitespace-pre-line text-sm text-slate-700 ${more ? '' : 'line-clamp-[12]'}`}>
                  {d.description}
                </p>
                {d.description.length > 700 && (
                  <button type="button" className="mt-1 text-sm text-sky-700 underline" onClick={() => setMore(!more)}>
                    {more ? 'Skryť' : 'Zobraziť celý text'}
                  </button>
                )}
              </section>
            )}

            {(d.history.length > 0 || d.notices.length > 1) && (
              <section className="mt-5">
                <h3 className="font-semibold">História</h3>
                <ol className="mt-2 space-y-2 border-l-2 border-slate-200 pl-4 text-sm">
                  {d.notices.map((n, i) => (
                    <li key={`n${i}`}>
                      <span className="text-slate-500">{date(n.published_at)}</span> – {n.type_label}
                      <span className="text-slate-400"> ({n.source === 'ov' ? 'Obchodný vestník' : 'NCRD'})</span>
                    </li>
                  ))}
                  {d.history.map((h, i) => (
                    <li key={`h${i}`}>
                      <span className="text-slate-500">{date(h.at)}</span> – {FIELD_LABEL[h.field] || h.field}:{' '}
                      <s className="text-slate-400">{fmtHist(h.field, h.old)}</s> → <strong>{fmtHist(h.field, h.new)}</strong>
                    </li>
                  ))}
                </ol>
              </section>
            )}

            <section className="mt-5">
              <h3 className="font-semibold">Zdroje</h3>
              <ul className="mt-1 space-y-1 text-sm">
                {d.sources.map((s, i) => (
                  <li key={i}>
                    {s.url ? (
                      <a className="text-sky-700 underline" href={s.url} target="_blank" rel="noreferrer">
                        {s.label || s.url}
                      </a>
                    ) : (
                      s.label
                    )}
                  </li>
                ))}
                {d.notices
                  .flatMap((n) => n.documents)
                  .map((doc, i) => (
                    <li key={`d${i}`}>
                      <a className="text-sky-700 underline" href={doc.url} target="_blank" rel="noreferrer">
                        {doc.title || 'Listina'} (PDF)
                      </a>
                    </li>
                  ))}
              </ul>
              <p className="mt-3 text-xs text-slate-500">
                Údaje majú len informatívny charakter a nie sú právne záväzné. Pred účasťou na dražbe si overte všetky
                údaje v pôvodnom oznámení a na katastri.
              </p>
            </section>
          </article>
        )}
      </div>
    </div>
  )
}
