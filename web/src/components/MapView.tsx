import { GeolocateControl, Map as MLMap, NavigationControl, setWorkerUrl, type GeoJSONSource, type MapGeoJSONFeature, type MapLayerMouseEvent } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
// MapLibre 6 si worker hľadá vedľa svojho súboru; v produkčnom zostavení ho Vite zabalí zvlášť
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import { useEffect, useRef } from 'react'
import { TYPE_COLOR, TYPE_LABEL, moneyShort } from '../format'
import type { PType } from '../types'
import type { AuctionItem, Property } from '../types'

setWorkerUrl(workerUrl)

const STYLE = 'https://tiles.openfreemap.org/styles/positron'
const SK_BOUNDS: [number, number, number, number] = [16.83, 47.73, 22.57, 49.61]

interface Props {
  items: AuctionItem[]
  selectedId: string | null
  detailProps: Property[] | null
  onSelect: (id: string) => void
  onBounds: (b: [number, number, number, number]) => void
}

function toGeoJSON(items: AuctionItem[]): GeoJSON.FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: items
      .filter((a) => a.lat != null && a.lng != null)
      .map((a) => ({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [a.lng!, a.lat!] },
        properties: {
          pid: a.id,
          color: TYPE_COLOR[a.t] || '#64748b',
          price: moneyShort(a.mb ?? a.av),
          past: a.s === 'prebehla' || a.s === 'zrusena' || a.s === 'zmarena' ? 1 : 0,
          approx: a.gp === 'parcela' ? 0 : 1,
        },
      })),
  }
}

export default function MapView({ items, selectedId, detailProps, onSelect, onBounds }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const map = useRef<MLMap | null>(null)
  const ready = useRef(false)
  const latest = useRef({ items, onSelect, onBounds })
  latest.current = { items, onSelect, onBounds }

  useEffect(() => {
    if (!ref.current) return
    const m = new MLMap({
      container: ref.current,
      style: STYLE,
      bounds: SK_BOUNDS,
      fitBoundsOptions: { padding: 20 },
      attributionControl: { compact: true },
      maxZoom: 18,
    })
    map.current = m
    m.addControl(new NavigationControl({ showCompass: false }), 'top-right')
    m.addControl(new GeolocateControl({ positionOptions: { enableHighAccuracy: false } }), 'top-right')

    m.on('load', () => {
      m.addSource('auctions', {
        type: 'geojson',
        data: toGeoJSON(latest.current.items),
        cluster: true,
        promoteId: 'pid',
        clusterRadius: 45,
        clusterMaxZoom: 13,
      })
      m.addSource('selected-geom', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
      m.addLayer({
        id: 'sel-fill',
        type: 'fill',
        source: 'selected-geom',
        paint: { 'fill-color': '#f59e0b', 'fill-opacity': 0.25 },
      })
      m.addLayer({
        id: 'sel-line',
        type: 'line',
        source: 'selected-geom',
        paint: { 'line-color': '#b45309', 'line-width': 2 },
      })
      m.addLayer({
        id: 'clusters',
        type: 'circle',
        source: 'auctions',
        filter: ['has', 'point_count'],
        paint: {
          'circle-color': '#1e3a5f',
          'circle-opacity': 0.88,
          'circle-stroke-color': '#fff',
          'circle-stroke-width': 2,
          'circle-radius': ['step', ['get', 'point_count'], 15, 10, 19, 50, 24, 200, 30],
        },
      })
      m.addLayer({
        id: 'cluster-count',
        type: 'symbol',
        source: 'auctions',
        filter: ['has', 'point_count'],
        layout: { 'text-field': ['get', 'point_count_abbreviated'], 'text-size': 12, 'text-font': ['Noto Sans Bold'] },
        paint: { 'text-color': '#fff' },
      })
      m.addLayer({
        id: 'points',
        type: 'circle',
        source: 'auctions',
        filter: ['!', ['has', 'point_count']],
        paint: {
          'circle-color': ['get', 'color'],
          'circle-opacity': ['case', ['==', ['get', 'past'], 1], 0.45, 0.95],
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 6, 5, 12, 8, 16, 10],
          'circle-stroke-color': ['case', ['boolean', ['feature-state', 'selected'], false], '#f59e0b', '#ffffff'],
          'circle-stroke-width': ['case', ['boolean', ['feature-state', 'selected'], false], 4, 1.5],
        },
      })
      m.addLayer({
        id: 'prices',
        type: 'symbol',
        source: 'auctions',
        filter: ['!', ['has', 'point_count']],
        minzoom: 11,
        layout: {
          'text-field': ['get', 'price'],
          'text-size': 11,
          'text-offset': [0, 1.4],
          'text-font': ['Noto Sans Regular'],
          'text-allow-overlap': false,
        },
        paint: { 'text-color': '#0f172a', 'text-halo-color': '#fff', 'text-halo-width': 1.5 },
      })

      m.on('click', 'clusters', async (e: MapLayerMouseEvent) => {
        const f = e.features?.[0] as MapGeoJSONFeature | undefined
        if (!f) return
        const src = m.getSource('auctions') as GeoJSONSource
        const zoom = await src.getClusterExpansionZoom(f.properties.cluster_id)
        m.easeTo({ center: (f.geometry as GeoJSON.Point).coordinates as [number, number], zoom })
      })
      m.on('click', 'points', (e: MapLayerMouseEvent) => {
        const f = e.features?.[0]
        if (f) latest.current.onSelect(String(f.properties.pid))
      })
      for (const l of ['clusters', 'points']) {
        m.on('mouseenter', l, () => (m.getCanvas().style.cursor = 'pointer'))
        m.on('mouseleave', l, () => (m.getCanvas().style.cursor = ''))
      }
      const emit = () => {
        const b = m.getBounds()
        latest.current.onBounds([b.getWest(), b.getSouth(), b.getEast(), b.getNorth()])
      }
      m.on('moveend', emit)
      emit()
      ready.current = true
    })
    return () => {
      ready.current = false
      m.remove()
    }
  }, [])

  // nové dáta po zmene filtrov
  useEffect(() => {
    const m = map.current
    if (!m || !ready.current) return
    ;(m.getSource('auctions') as GeoJSONSource | undefined)?.setData(toGeoJSON(items))
  }, [items])

  // zvýraznenie vybranej dražby
  const prevSel = useRef<string | null>(null)
  useEffect(() => {
    const m = map.current
    if (!m || !ready.current) return
    if (prevSel.current != null) m.setFeatureState({ source: 'auctions', id: prevSel.current }, { selected: false })
    if (selectedId != null) m.setFeatureState({ source: 'auctions', id: selectedId }, { selected: true })
    prevSel.current = selectedId
  }, [selectedId, items])

  // polygón parciel vybranej dražby + priblíženie
  useEffect(() => {
    const m = map.current
    if (!m) return
    const run = () => {
      const src = m.getSource('selected-geom') as GeoJSONSource | undefined
      if (!src) return
      const feats: GeoJSON.Feature[] = (detailProps || [])
        .filter((p) => p.geom)
        .map((p) => ({ type: 'Feature', geometry: p.geom!, properties: {} }))
      src.setData({ type: 'FeatureCollection', features: feats })
      // priblíž tak, aby boli vidieť všetky parcely; inak aspoň bod
      const coords: number[][] = []
      const walk = (c: unknown): void => {
        if (Array.isArray(c) && typeof c[0] === 'number') coords.push(c as number[])
        else if (Array.isArray(c)) c.forEach(walk)
      }
      feats.forEach((f) => walk((f.geometry as GeoJSON.Polygon | GeoJSON.MultiPolygon).coordinates))
      if (coords.length) {
        const xs = coords.map((c) => c[0])
        const ys = coords.map((c) => c[1])
        m.fitBounds(
          [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)],
          { padding: 80, maxZoom: 17, duration: 600 },
        )
        return
      }
      const pts = (detailProps || []).filter((p) => p.lat != null)
      if (pts.length) {
        const p = pts[0]
        m.easeTo({ center: [p.lng!, p.lat!], zoom: Math.max(m.getZoom(), p.geo_source === 'ku' ? 12 : 11), duration: 600 })
      }
    }
    if (ready.current) run()
    else m.once('load', run)
  }, [detailProps])

  return (
    <div className="relative h-full w-full">
      <div ref={ref} className="h-full w-full" aria-label="Mapa dražieb" />
      <Legend />
    </div>
  )
}

const LEGEND: PType[] = ['byt', 'dom', 'rekreacny', 'pozemok', 'nebytovy', 'ine']

function Legend() {
  return (
    <div className="pointer-events-none absolute bottom-8 left-2 hidden rounded-lg bg-white/90 px-2.5 py-2 text-xs text-slate-700 shadow sm:block">
      {LEGEND.map((t) => (
        <div key={t} className="flex items-center gap-1.5 leading-5">
          <span className="h-2.5 w-2.5 rounded-full" style={{ background: TYPE_COLOR[t] }} />
          {t === 'ine' ? 'Garáž / iné' : TYPE_LABEL[t]}
        </div>
      ))}
      <div className="mt-1 flex items-center gap-1.5 leading-5 text-slate-500">
        <span className="h-2.5 w-2.5 rounded-full bg-slate-400 opacity-50" /> prebehnutá / zrušená
      </div>
    </div>
  )
}
