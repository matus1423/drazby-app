export type Kind = 'dobrovolna' | 'exekucna' | 'danova'
export type Status = 'pripravovana' | 'odrocena' | 'prebehla' | 'zrusena' | 'zmarena' | 'neplatna'
export type PType = 'byt' | 'dom' | 'rekreacny' | 'pozemok' | 'nebytovy' | 'garaz' | 'ine'

/** Kompaktný záznam z auctions.json (krátke kľúče kvôli veľkosti súboru). */
export interface AuctionItem {
  /** stabilný kód dražby (10 znakov), používa sa aj v odkaze #id=… */
  id: string
  k: Kind
  s: Status
  t: PType
  ti: string
  kr: string | null
  ok: string | null
  ob: string | null
  d: string | null
  r: number | null
  mb: number | null
  av: number | null
  hb: number | null
  lat: number | null
  lng: number | null
  gp: 'parcela' | 'ku' | 'obec' | 'okres' | null
  au: string | null
  src: string[]
  fs: string
  ar: number | null
  la: number | null
}

export interface Parcel {
  register: string | null
  number: string
  area_m2?: number | null
  kind?: string | null
}

export interface Property {
  type: PType | null
  kraj: string | null
  okres: string | null
  obec: string | null
  ku: string | null
  area_m2: number | null
  address: string | null
  share: string | null
  lat: number | null
  lng: number | null
  geo_source: string | null
  lv: string[]
  parcels: Parcel[]
  supisne_cislo: string[]
  geom: GeoJSON.Geometry | null
}

export interface Notice {
  source: string
  url: string | null
  label: string | null
  type: string
  type_label: string
  published_at: string | null
  auction_at: string | null
  documents: { title: string; url: string }[]
}

export interface AuctionDetail {
  id: string
  kind: Kind
  kind_label: string
  status: Status
  status_label: string
  auction_number: string | null
  auctioneer_name: string | null
  auctioneer_ico: string | null
  proposer: string | null
  notary: string | null
  auction_at: string | null
  venue: string | null
  round: number | null
  min_bid: number | null
  min_increment: number | null
  deposit: number | null
  appraised_value: number | null
  highest_bid: number | null
  sold: boolean | null
  inspection: string | null
  title: string | null
  description: string | null
  reason: string | null
  property_type: PType | null
  property_type_label: string | null
  kraj: string | null
  okres: string | null
  obec: string | null
  ku: string | null
  lat: number | null
  lng: number | null
  geo_precision: string | null
  first_seen: string
  updated_at: string
  sources: { source: string; label: string | null; url: string | null; notice_type?: string; published_at?: string }[]
  properties: Property[]
  history: { at: string; field: string; old: string | null; new: string | null }[]
  notices: Notice[]
}

export interface Meta {
  generated_at: string
  count: number
  upcoming: number
  by_source: Record<string, number>
  with_coords: number
}
