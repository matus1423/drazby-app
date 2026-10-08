import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from 'react'
import AuctionDetail from './components/AuctionDetail'
import AuctionList from './components/AuctionList'
import FiltersPanel from './components/FiltersPanel'
import { activeCount, applyFilters, filtersToQuery, queryToFilters, type Filters, type Sort } from './filters'
import { date } from './format'
import type { AuctionDetail as Detail, AuctionItem, Meta } from './types'

const MapView = lazy(() => import('./components/MapView'))

const DATA = import.meta.env.VITE_DATA_URL || '/data'

function readHash() {
  const p = new URLSearchParams(location.hash.replace(/^#\??/, ''))
  const id = p.get('id')
  p.delete('id')
  return { filters: queryToFilters(p.toString()), id: id || null }
}

function writeHash(filters: Filters, id: string | null, push: boolean) {
  const p = new URLSearchParams(filtersToQuery(filters))
  if (id != null) p.set('id', id)
  const h = p.toString()
  if (location.hash.replace(/^#/, '') === h) return
  const url = h ? `#${h}` : location.pathname + location.search
  if (push) history.pushState(null, '', url)
  else history.replaceState(null, '', url)
}

function plural(n: number) {
  return n === 1 ? 'dražba' : n >= 2 && n <= 4 ? 'dražby' : 'dražieb'
}

export default function App() {
  const init = useMemo(readHash, [])
  const [items, setItems] = useState<AuctionItem[]>([])
  const [meta, setMeta] = useState<Meta | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [filters, setFilters] = useState<Filters>(init.filters)
  const [selectedId, setSelectedId] = useState<string | null>(init.id)
  const [detail, setDetail] = useState<Detail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [bounds, setBounds] = useState<[number, number, number, number] | null>(null)
  const [mobileView, setMobileView] = useState<'list' | 'map'>('list')
  const [showFilters, setShowFilters] = useState(false)

  useEffect(() => {
    Promise.all([
      fetch(`${DATA}/auctions.json`).then((r) => (r.ok ? r.json() : Promise.reject(r.status))),
      fetch(`${DATA}/meta.json`).then((r) => (r.ok ? r.json() : null)),
    ])
      .then(([a, m]) => {
        setItems(a)
        setMeta(m)
      })
      .catch(() => setLoadError('Dáta sa nepodarilo načítať. Skúste obnoviť stránku.'))
  }, [])

  // filtre → adresa (bez nového záznamu v histórii)
  useEffect(() => writeHash(filters, selectedId, false), [filters, selectedId])

  // tlačidlo Späť v prehliadači
  useEffect(() => {
    const onPop = () => {
      const h = readHash()
      setFilters(h.filters)
      setSelectedId(h.id)
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  // detail
  useEffect(() => {
    if (selectedId == null) {
      setDetail(null)
      return
    }
    let cancel = false
    setDetailLoading(true)
    setDetailError(null)
    fetch(`${DATA}/a/${selectedId}.json`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((d) => !cancel && setDetail(d))
      .catch(() => !cancel && setDetailError('Detail dražby sa nepodarilo načítať.'))
      .finally(() => !cancel && setDetailLoading(false))
    return () => {
      cancel = true
    }
  }, [selectedId])

  const base = useMemo(() => applyFilters(items, { ...filters, inView: false }), [items, filters])
  const listed = useMemo(
    () => (filters.inView && bounds ? applyFilters(items, filters, bounds) : base),
    [items, filters, bounds, base],
  )
  const noCoords = useMemo(() => base.filter((a) => a.lat == null).length, [base])

  const select = useCallback(
    (id: string) => {
      writeHash(filters, id, true)
      setSelectedId(id)
    },
    [filters],
  )
  const close = useCallback(() => {
    if (history.length > 1 && readHash().id != null) history.back()
    setSelectedId(null)
  }, [])
  const nActive = activeCount(filters)

  return (
    <div className="flex h-dvh flex-col bg-slate-100 text-slate-900">
      <header className="flex items-center justify-between gap-3 bg-[#1e3a5f] px-4 py-2.5 text-white">
        <button type="button" onClick={() => setSelectedId(null)} className="flex items-center gap-2 font-bold">
          <img src="/favicon.svg" alt="" className="h-7 w-7" />
          <span>Dražby nehnuteľností</span>
        </button>
        <div className="hidden text-xs text-slate-300 sm:block">
          {meta ? `Aktualizované ${date(meta.generated_at)} · ${meta.upcoming} pripravovaných dražieb` : ''}
        </div>
      </header>

      {loadError && <div className="bg-rose-100 p-3 text-center text-rose-800">{loadError}</div>}

      <main className="relative flex min-h-0 flex-1">
        {/* ľavý panel: zoznam / filtre / detail */}
        <section
          className={`absolute inset-0 z-10 flex-col bg-white lg:static lg:flex lg:w-[430px] lg:shrink-0 lg:border-r lg:border-slate-200 ${
            mobileView === 'map' && selectedId == null && !showFilters ? 'hidden' : 'flex'
          }`}
        >
          {selectedId != null ? (
            <AuctionDetail detail={detail} loading={detailLoading} error={detailError} onClose={close} />
          ) : showFilters ? (
            <div className="flex-1 overflow-y-auto">
              <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
                <h2 className="font-semibold">Filtre</h2>
                <button type="button" className="text-sm text-slate-600" onClick={() => setShowFilters(false)}>
                  Zavrieť
                </button>
              </div>
              <FiltersPanel
                filters={filters}
                items={items}
                onChange={setFilters}
                onClose={() => setShowFilters(false)}
                resultCount={base.length}
              />
            </div>
          ) : (
            <>
              <div className="space-y-2 border-b border-slate-200 p-3">
                <div className="flex gap-2">
                  <input
                    className="min-w-0 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-slate-600 focus:outline-none"
                    placeholder="Hľadať obec, okres…"
                    value={filters.q}
                    onChange={(e) => setFilters({ ...filters, q: e.target.value })}
                    aria-label="Hľadať"
                  />
                  <button
                    type="button"
                    onClick={() => setShowFilters(true)}
                    className="shrink-0 rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium hover:bg-slate-50"
                  >
                    Filtre{nActive ? ` (${nActive})` : ''}
                  </button>
                </div>
                <div className="flex items-center justify-between gap-2 text-sm">
                  <span className="text-slate-600">
                    <strong className="text-slate-900">{listed.length}</strong> {plural(listed.length)}
                  </span>
                  <div className="flex items-center gap-3">
                    <label className="hidden items-center gap-1.5 text-slate-600 lg:flex">
                      <input
                        type="checkbox"
                        checked={filters.inView}
                        onChange={(e) => setFilters({ ...filters, inView: e.target.checked })}
                      />
                      len na mape
                    </label>
                    <select
                      className="rounded border border-slate-300 bg-white px-2 py-1"
                      value={filters.sort}
                      onChange={(e) => setFilters({ ...filters, sort: e.target.value as Sort })}
                      aria-label="Zoradiť"
                    >
                      <option value="date">Podľa dátumu</option>
                      <option value="price_asc">Najlacnejšie</option>
                      <option value="price_desc">Najdrahšie</option>
                      <option value="discount">Najväčšia zľava</option>
                      <option value="new">Najnovšie pridané</option>
                    </select>
                  </div>
                </div>
              </div>
              <div className="flex-1 overflow-y-auto pb-20 lg:pb-0">
                {!items.length && !loadError ? (
                  <p className="p-6 text-slate-500">Načítavam dražby…</p>
                ) : (
                  <AuctionList items={listed} selectedId={selectedId} onSelect={select} />
                )}
                {noCoords > 0 && !filters.inView && (
                  <p className="px-4 pb-4 text-xs text-slate-400">
                    {noCoords} z nich nemá polohu, preto nie sú na mape.
                  </p>
                )}
                <Disclaimer />
              </div>
            </>
          )}
        </section>

        {/* mapa */}
        <section className="min-w-0 flex-1">
          <Suspense fallback={<div className="p-6 text-slate-500">Načítavam mapu…</div>}>
            <MapView
              items={base}
              selectedId={selectedId}
              detailProps={detail?.properties ?? null}
              onSelect={select}
              onBounds={setBounds}
            />
          </Suspense>
        </section>

        {/* prepínač mapa / zoznam na mobile */}
        {selectedId == null && !showFilters && (
          <div className="absolute bottom-5 left-1/2 z-20 -translate-x-1/2 lg:hidden">
            <button
              type="button"
              className="rounded-full bg-slate-900 px-5 py-3 text-sm font-semibold text-white shadow-lg"
              onClick={() => setMobileView(mobileView === 'list' ? 'map' : 'list')}
            >
              {mobileView === 'list' ? 'Zobraziť mapu' : `Zoznam (${listed.length})`}
            </button>
          </div>
        )}
      </main>
    </div>
  )
}

function Disclaimer() {
  return (
    <footer className="border-t border-slate-100 p-4 text-xs leading-relaxed text-slate-500">
      Údaje majú len informatívny charakter a nie sú právne záväzné. Zdroje: Obchodný vestník (cez Slovensko.Digital
      Datahub), Notársky centrálny register dražieb (NCRD), kataster ÚGKK SR a OpenStreetMap. Exekučné dražby sú
      z dražobných vyhlášok exekútorov zverejnených v Obchodnom vestníku. Pred účasťou na dražbe si údaje overte
      v pôvodnom oznámení.
    </footer>
  )
}
