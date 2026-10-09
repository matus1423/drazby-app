"""Geokódovanie nehnuteľností.

Poradie (od najpresnejšieho):
1. **parcela** – ÚGKK INSPIRE WFS (CP.CadastralParcel), identifikátor `<kód k. ú.>_<číslo>.C`.
   Vráti bod aj polygón parcely. Funguje len pre parcely registra C (register E služba nemá).
2. **ku** – stred katastrálneho územia (CP.CadastralZoning podľa názvu).
3. **obec** – stred k. ú. s rovnakým názvom ako obec (obec a jej hlavné k. ú. sa väčšinou volajú rovnako).

Nominatim (OpenStreetMap) nepoužívame: jeho robots.txt zakazuje automatické /search
(pozri DECISIONS D12). Kód zostáva vypnutý za `USE_NOMINATIM`.

Výsledky sa ukladajú do tabuľky `geocache`, takže každé k. ú./obec sa pýta len raz.
"""

from __future__ import annotations

import json
import logging
import math
import re
import time
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote, urlencode

from . import text as T
from .db import Store, now
from .http import PoliteClient

log = logging.getLogger(__name__)

WFS = "https://inspirews.skgeodesy.sk/geoserver/cp/ows"
NOMINATIM = "https://nominatim.openstreetmap.org/search"

USE_NOMINATIM = False
MAX_PARCELS = 6
MAX_FAILURES = 3      # po toľkých výpadkoch za sebou kataster v tomto behu vynecháme
KU_TABLE = Path(__file__).parent / "data" / "ku.json"  # stredy všetkých k. ú. (scrapers/tools/build_ku_table.py)
# už nájdené parcely (bod + tvar) – aby nočný beh na GitHube, odkiaľ kataster neodpovedá, nestratil presnosť
PARCEL_TABLE = Path(__file__).parent / "data" / "parcels.json"


@lru_cache(maxsize=1)
def _parcel_table() -> dict[str, list]:
    return json.loads(PARCEL_TABLE.read_text()) if PARCEL_TABLE.exists() else {}


@lru_cache(maxsize=1)
def _ku_table() -> dict[str, list[dict]]:
    """{normalizovaný názov: [{code, label, lat, lng}]} z pribaleného súboru (bez internetu)."""
    if not KU_TABLE.exists():
        return {}
    out: dict[str, list[dict]] = {}
    for code, (label, lat, lng) in json.loads(KU_TABLE.read_text()).items():
        out.setdefault(T.norm_key(label), []).append({"code": code, "label": label, "lat": lat, "lng": lng})
    return out  # koľko parciel jednej nehnuteľnosti kreslíme na mapu

# hrubý obdĺžnik Slovenska – kontrola, že výsledok dáva zmysel
SK_BBOX = (16.8, 47.7, 22.6, 49.65)


def _in_sk(lat, lng) -> bool:
    return lat is not None and SK_BBOX[1] <= lat <= SK_BBOX[3] and SK_BBOX[0] <= lng <= SK_BBOX[2]


def _esc(v: str) -> str:
    return v.replace("&", "&amp;").replace("<", "&lt;")


def _filter_eq(prop: str, val: str) -> str:
    return (f"<Filter><PropertyIsEqualTo><PropertyName>{prop}</PropertyName>"
            f"<Literal>{_esc(val)}</Literal></PropertyIsEqualTo></Filter>")


def _filter_like_ci(prop: str, val: str) -> str:
    return (f'<Filter><PropertyIsLike wildCard="*" singleChar="?" escapeChar="!" matchCase="false">'
            f"<PropertyName>{prop}</PropertyName><Literal>{_esc(val)}</Literal></PropertyIsLike></Filter>")


def _wfs_url(type_name: str, flt: str, max_features: int = 10) -> str:
    q = {"service": "WFS", "version": "1.1.0", "request": "GetFeature", "outputFormat": "application/json",
         "typeName": type_name, "maxFeatures": str(max_features)}
    return f"{WFS}?{urlencode(q)}&filter={quote(flt)}"


def centroid(geom: dict | None) -> tuple[float, float] | None:
    """Ťažisko (najväčšieho) polygónu ako (lon, lat)."""
    if not geom or geom.get("type") not in ("Polygon", "MultiPolygon"):
        return None
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    best, best_a = None, 0.0
    for poly in polys:
        ring = poly[0]
        a = cx = cy = 0.0
        for (x0, y0), (x1, y1) in zip(ring, ring[1:]):
            cr = x0 * y1 - x1 * y0
            a += cr
            cx += (x0 + x1) * cr
            cy += (y0 + y1) * cr
        if a != 0 and abs(a) > best_a:
            best_a = abs(a)
            best = (cx / (3 * a), cy / (3 * a))
    return best


def simplify_ring(coords, tol=0.00002):
    """Vynechá body bližšie ako `tol` stupňa – menší JSON, tvar parcely ostane."""
    out = [coords[0]]
    for p in coords[1:-1]:
        if abs(p[0] - out[-1][0]) > tol or abs(p[1] - out[-1][1]) > tol:
            out.append(p)
    out.append(coords[-1])
    return [[round(x, 6), round(y, 6)] for x, y in out]


class Geocoder:
    def __init__(self, store: Store, use_cadastre: bool = True):
        self.store = store
        self.use_cadastre = use_cadastre
        # parcely odpovedajú pomaly (~4 s), občas aj viac ako minútu; zo zahraničia (GitHub) vôbec
        self.wfs = PoliteClient(min_delay=0.6, timeout=45, retries=2)
        self.nom = PoliteClient(min_delay=1.2, timeout=30)
        self.stats = {"parcela": 0, "ku": 0, "obec": 0, "okres": 0, "fail": 0, "requests": 0}
        self.failures = 0
        self.wfs_down = False

    def close(self):
        self.wfs.close()
        self.nom.close()

    # --- cache -------------------------------------------------------------
    def _cache_get(self, key):
        r = self.store.con.execute("SELECT * FROM geocache WHERE key=?", (key,)).fetchone()
        return dict(r) if r else None

    def _cache_put(self, key, lat, lng, precision, source, geom=None):
        self.store.con.execute(
            "INSERT OR REPLACE INTO geocache(key, lat, lng, precision, source, geom, created_at) VALUES(?,?,?,?,?,?,?)",
            (key, lat, lng, precision, source, json.dumps(geom) if geom is not None else None, now()))

    def _get_json(self, client, url):
        if client is self.wfs and self.wfs_down:
            return None
        self.stats["requests"] += 1
        try:
            d = client.get(url).json()
            if client is self.wfs:
                self.failures = 0
            return d
        except Exception as e:
            log.warning("geokódovanie: %s → %s", url[:120], e)
            if client is self.wfs:
                self.failures += 1
                if self.failures >= MAX_FAILURES:
                    self.wfs_down = True
                    log.warning("geokódovanie: kataster neodpovedá – v tomto behu len stredy k. ú. z tabuľky")
            return None

    # --- k. ú. -------------------------------------------------------------
    def ku_lookup(self, name: str) -> list[dict]:
        """[{code, label, lat, lng}] pre názov k. ú. (rovnaký názov môže mať viac území)."""
        key = f"ku:{T.norm_key(name)}"
        c = self._cache_get(key)
        if c:
            return json.loads(c["geom"] or "[]")
        table = _ku_table()
        if table:
            return list(table.get(T.norm_key(name), []))
        out = []
        failed = False
        for flt in (_filter_eq("label", name), _filter_like_ci("label", name)):
            d = self._get_json(self.wfs, _wfs_url("cp:CP.CadastralZoning", flt))
            if d is None:
                failed = True
                continue
            for f in d.get("features") or []:
                p = f["properties"]
                if T.norm_key(p.get("label")) != T.norm_key(name):
                    continue
                cen = centroid(f.get("geometry"))
                out.append({"code": p.get("nationalCadastalZoningReference"), "label": p.get("label"),
                            "lng": cen[0] if cen else None, "lat": cen[1] if cen else None})
            if out:
                break
        if out or not failed:
            self._cache_put(key, None, None, "ku-list", "ugkk", out)
        return out

    def parcels_lookup(self, ku_code: str, numbers: list[str]) -> dict[str, dict | None]:
        """Viac parciel jedného k. ú. naraz (jeden dopyt s <Or>) – služba je pomalá na dopyt,
        nie na počet parciel. Vracia {číslo: {lat, lng, geom} | None}."""
        out: dict[str, dict | None] = {}
        todo = []
        bundled = _parcel_table()
        for num in numbers:
            b = bundled.get(f"{ku_code}_{num}.C")
            if b:
                out[num] = {"lat": b[0], "lng": b[1], "geom": b[2]}
                continue
            c = self._cache_get(f"parcel:{ku_code}_{num}.C")
            if c:
                out[num] = None if c["lat"] is None else {
                    "lat": c["lat"], "lng": c["lng"], "geom": json.loads(c["geom"]) if c["geom"] else None}
            else:
                todo.append(num)
        if not todo:
            return out
        refs = {f"{ku_code}_{n}.C": n for n in todo}
        flt = "<Filter><Or>" + "".join(
            f"<PropertyIsEqualTo><PropertyName>nationalCadastralReference</PropertyName>"
            f"<Literal>{_esc(r)}</Literal></PropertyIsEqualTo>" for r in refs) + "</Or></Filter>"
        if len(refs) == 1:
            flt = _filter_eq("nationalCadastralReference", next(iter(refs)))
        d = self._get_json(self.wfs, _wfs_url("cp:CP.CadastralParcel", flt, len(refs)))
        if d is None:
            return out  # chyba siete – necachuj, skúsi sa nabudúce
        found = {}
        for f in d.get("features") or []:
            ref = f["properties"].get("nationalCadastralReference")
            if ref not in refs:
                continue
            rp = (f["properties"].get("referencePoint") or {}).get("coordinates")
            geom = f.get("geometry")
            if geom and geom["type"] == "Polygon":
                geom = {"type": "Polygon", "coordinates": [simplify_ring(r) for r in geom["coordinates"]]}
            if not rp:
                cen = centroid(geom)
                rp = list(cen) if cen else None
            if rp:
                found[refs[ref]] = {"lat": rp[1], "lng": rp[0], "geom": geom}
        for ref, num in refs.items():
            hit = found.get(num)
            self._cache_put(f"parcel:{ref}", hit["lat"] if hit else None, hit["lng"] if hit else None,
                            "parcela", "ugkk", hit["geom"] if hit else None)
            out[num] = hit
        return out

    def parcel_lookup(self, ku_code: str, number: str) -> dict | None:
        return self.parcels_lookup(ku_code, [number]).get(number)

    # --- Nominatim ---------------------------------------------------------
    def nominatim(self, query: dict, key: str, precision: str) -> dict | None:
        if not USE_NOMINATIM:
            return None
        c = self._cache_get(key)
        if c:
            return None if c["lat"] is None else {"lat": c["lat"], "lng": c["lng"]}
        q = {**query, "countrycodes": "sk", "format": "jsonv2", "limit": "1", "accept-language": "sk"}
        d = self._get_json(self.nom, f"{NOMINATIM}?{urlencode(q)}")
        if d is None:
            return None
        if d and _in_sk(float(d[0]["lat"]), float(d[0]["lon"])):
            lat, lng = float(d[0]["lat"]), float(d[0]["lon"])
            self._cache_put(key, lat, lng, precision, "nominatim")
            return {"lat": lat, "lng": lng}
        self._cache_put(key, None, None, precision, "nominatim")
        return None

    def obec(self, obec: str, okres: str | None) -> dict | None:
        name = re.sub(r"^(BA|KE)\s*-\s*m\.\s*č\.\s*", "", obec).strip()
        name = re.sub(r"\s*-\s*mestská časť\s*", "-", name)
        r = self.nominatim({"q": f"{name}, okres {okres}" if okres else name},
                           f"obec:{T.norm_key(name)}|{T.norm_key(okres)}", "obec")
        if not r and okres:
            r = self.nominatim({"q": name}, f"obec:{T.norm_key(name)}|", "obec")
        return r

    def okres(self, okres: str) -> dict | None:
        return self.nominatim({"q": f"okres {okres}"}, f"okres:{T.norm_key(okres)}", "okres")

    # --- jedna nehnuteľnosť ------------------------------------------------
    def locate(self, p: dict) -> dict | None:
        parcels = p.get("parcels") or []
        if isinstance(parcels, str):
            parcels = json.loads(parcels or "[]")
        ku = p.get("ku") or p.get("obec")
        if self.use_cadastre and ku:
            ku_name = re.sub(r"^(Bratislava|Košice|BA|KE)\s*-\s*(m\.\s*č\.\s*)?", "", ku).strip()
            cands = self.ku_lookup(ku_name)
            if len(cands) > 1 and p.get("obec") and T.norm_key(p["obec"]) != T.norm_key(ku_name):
                ref = next((c for c in self.ku_lookup(p["obec"]) if c.get("lat") is not None), None)
                if ref:
                    cands.sort(key=lambda c: _dist(c, ref) if c.get("lat") is not None else 1e9)
            nums = []
            for parc in parcels:
                if (parc.get("register") or "C").upper() != "C":
                    continue
                num = re.sub(r"\s", "", str(parc.get("number") or ""))
                if re.fullmatch(r"\d+(/\d+)?", num) and num not in nums:
                    nums.append(num)
            for cand in cands[:2]:
                if not nums:
                    break
                hits = self.parcels_lookup(cand["code"], nums[:MAX_PARCELS])
                found = [hits[n] for n in nums[:MAX_PARCELS] if hits.get(n)]
                if not found:
                    continue
                polys = []
                for h in found:
                    g = h.get("geom")
                    if g and g["type"] == "Polygon":
                        polys.append(g["coordinates"])
                    elif g and g["type"] == "MultiPolygon":
                        polys += g["coordinates"]
                geom = {"type": "MultiPolygon", "coordinates": polys} if len(polys) > 1 else found[0].get("geom")
                return {"lat": found[0]["lat"], "lng": found[0]["lng"], "geom": geom, "precision": "parcela"}
            if cands and cands[0].get("lat") is not None:
                return {"lat": cands[0]["lat"], "lng": cands[0]["lng"], "precision": "ku"}
        if p.get("obec"):
            obec = re.sub(r"^(Bratislava|Košice|BA|KE)\s*-\s*(m\.\s*č\.\s*)?", "", p["obec"]).strip()
            if self.use_cadastre and T.norm_key(obec) != T.norm_key(p.get("ku")):
                c = next((c for c in self.ku_lookup(obec) if c.get("lat") is not None), None)
                if c:
                    return {"lat": c["lat"], "lng": c["lng"], "precision": "obec"}
            r = self.obec(p["obec"], p.get("okres"))
            if r:
                return {**r, "precision": "obec"}
        if p.get("okres"):
            r = self.okres(p["okres"])
            if r:
                return {**r, "precision": "okres"}
        return None


def _dist(a: dict, b: dict) -> float:
    return math.hypot(a["lat"] - b["lat"], (a["lng"] - b["lng"]) * 0.66)


def geocode_all(store: Store, limit: int | None = None, use_cadastre: bool = True, redo: bool = False,
                budget_s: float | None = None) -> dict:
    """Doplní polohu nehnuteľnostiam bez nej. `redo=True` prejde znova aj tie s presnou parcelou
    (napr. keď sa pridalo kreslenie viacerých parciel) – vďaka cache je to lacné."""
    g = Geocoder(store, use_cadastre=use_cadastre)
    where = "p.lat IS NULL OR p.geo_source='parcela'" if redo else "p.lat IS NULL"
    rows = [dict(r) for r in store.con.execute(
        f"SELECT p.* FROM properties p JOIN auctions a ON a.id=p.auction_id WHERE {where}"
        " ORDER BY a.auction_at DESC")]
    if limit:
        rows = rows[:limit]
    log.info("geokódovanie: %d nehnuteľností", len(rows))
    touched = set()
    t0 = time.monotonic()
    try:
        for i, p in enumerate(rows):
            if budget_s and time.monotonic() - t0 > budget_s:
                log.warning("geokódovanie: vyčerpaný čas (%d s), zvyšok nabudúce", budget_s)
                g.stats["stopped"] = len(rows) - i
                break
            r = g.locate(p)
            if not r:
                g.stats["fail"] += 1
                continue
            g.stats[r["precision"]] += 1
            store.con.execute("UPDATE properties SET lat=?, lng=?, geom=?, geo_source=? WHERE id=?",
                              (r["lat"], r["lng"], json.dumps(r.get("geom")) if r.get("geom") else None,
                               r["precision"], p["id"]))
            touched.add(p["auction_id"])
            if i % 25 == 0:
                store.commit()
                log.info("geokódovanie: %d/%d %s", i + 1, len(rows), g.stats)
    finally:
        for aid in touched:
            store._refresh_location(aid)
        store.commit()
        g.close()
    return g.stats
