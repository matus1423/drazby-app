"""Export dát pre frontend ako statické JSON súbory.

- `auctions.json` – kompaktný zoznam všetkých dražieb (mapa + zoznam + filtre)
- `a/<id>.json`   – detail dražby (všetky polia, nehnuteľnosti s polygónmi, história, oznámenia)
- `meta.json`     – čas exportu, počty, posledné behy

Statické súbory = žiadny server, funguje na Verceli aj lokálne. Keď bude Supabase,
frontend môže čítať priamo z neho (pozri README).
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from datetime import date
from pathlib import Path

from .db import Store, effective_status, now
from .text import PROPERTY_TYPES, redact_personal

log = logging.getLogger(__name__)

KIND_LABELS = {"dobrovolna": "Dobrovoľná", "exekucna": "Exekučná", "danova": "Daňová"}
STATUS_LABELS = {
    "pripravovana": "Pripravovaná", "odrocena": "Odročená", "prebehla": "Prebehla", "zrusena": "Zrušená",
    "zmarena": "Zmarená", "neplatna": "Neplatná",
}
NOTICE_LABELS = {
    "oznamenie": "Oznámenie o dražbe", "opakovana": "Oznámenie o opakovanej dražbe", "dodatok": "Dodatok / zmena",
    "upustenie": "Upustenie od dražby", "zmarenie": "Zmarenie dražby", "vysledok": "Výsledok dražby",
    "neplatnost": "Neplatnosť dražby",
}

DETAIL_FIELDS = ("id", "kind", "auction_number", "auctioneer_name", "auctioneer_ico", "proposer", "notary",
                 "auction_at", "venue", "round", "min_bid", "min_increment", "deposit", "appraised_value",
                 "highest_bid", "inspection", "title", "description", "reason", "property_type", "kraj", "okres",
                 "obec", "ku", "lat", "lng", "geo_precision", "first_seen", "updated_at")


def public_id(group_key: str) -> str:
    """Stabilný kód dražby do odkazov (nezmení sa ani po `rebuild`, na rozdiel od poradového id)."""
    return hashlib.sha1(group_key.encode()).hexdigest()[:10]


def _int(v):
    return None if v is None else int(round(v))


def _jl(s):
    return json.loads(s or "[]")


def export(store: Store, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    detail_dir = out / "a"
    tmp_dir = out / "a.tmp"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir()
    today = date.today()
    con = store.con
    rows = [dict(r) for r in con.execute("SELECT * FROM auctions ORDER BY auction_at DESC")]
    props_by: dict[int, list] = {}
    for p in con.execute("SELECT * FROM properties ORDER BY auction_id, idx"):
        props_by.setdefault(p["auction_id"], []).append(dict(p))
    hist_by: dict[int, list] = {}
    for h in con.execute("SELECT * FROM auction_history ORDER BY changed_at, id"):
        hist_by.setdefault(h["auction_id"], []).append(dict(h))
    notices_by: dict[int, list] = {}
    for n in con.execute("SELECT auction_id, source, source_url, source_label, notice_type, published_at,"
                         " auction_at, payload FROM notices ORDER BY published_at, id"):
        notices_by.setdefault(n["auction_id"], []).append(dict(n))

    items = []
    for a in rows:
        props = props_by.get(a["id"], [])
        st = effective_status(a["status"], a["auction_at"], today)
        area = next((p["area_m2"] for p in props if p["area_m2"]), None)
        land = sum(sum((pc.get("area_m2") or 0) for pc in _jl(p["parcels"])) for p in props) or None
        srcs = _jl(a["sources"])
        items.append({
            "id": public_id(a["group_key"]),
            "k": a["kind"],
            "s": st,
            "t": a["property_type"] or "ine",
            "ti": short_title(a, props),
            "kr": a["kraj"], "ok": a["okres"], "ob": a["obec"] or a["ku"],
            "d": a["auction_at"],
            "r": a["round"],
            "mb": _int(a["min_bid"]),
            "av": _int(a["appraised_value"]),
            "hb": _int(a["highest_bid"]),
            "lat": round(a["lat"], 6) if a["lat"] is not None else None,
            "lng": round(a["lng"], 6) if a["lng"] is not None else None,
            "gp": a["geo_precision"],
            "au": a["auctioneer_name"],
            "src": sorted({s["source"] for s in srcs}),
            "fs": a["first_seen"][:10],
            "ar": area,
            "la": _int(land),
        })
        detail = {
            **{k: a[k] for k in DETAIL_FIELDS},
            # web je verejný → bez dátumov narodenia, rodných čísel a mien pri nich
            **{k: redact_personal(a[k]) for k in ("description", "title", "reason", "inspection", "proposer")},
            "id": public_id(a["group_key"]),
            "sold": None if a["sold"] is None else bool(a["sold"]),
            "status": st,
            "status_label": STATUS_LABELS.get(st, st),
            "kind_label": KIND_LABELS.get(a["kind"], a["kind"]),
            "property_type_label": PROPERTY_TYPES.get(a["property_type"] or "ine"),
            "sources": srcs,
            "properties": [{
                **{k: p[k] for k in ("type", "kraj", "okres", "obec", "ku", "area_m2", "address", "share",
                                     "lat", "lng", "geo_source")},
                "lv": _jl(p["lv"]),
                "parcels": _jl(p["parcels"]),
                "supisne_cislo": _jl(p["supisne_cislo"]),
                "geom": json.loads(p["geom"]) if p["geom"] else None,
            } for p in props],
            "history": [{"at": h["changed_at"], "field": h["field"], "old": h["old_value"], "new": h["new_value"]}
                        for h in hist_by.get(a["id"], [])],
            "notices": [{"source": n["source"], "url": n["source_url"], "label": n["source_label"],
                         "type": n["notice_type"], "type_label": NOTICE_LABELS.get(n["notice_type"], n["notice_type"]),
                         "published_at": n["published_at"], "auction_at": n["auction_at"],
                         "documents": json.loads(n["payload"]).get("documents") or []}
                        for n in notices_by.get(a["id"], [])],
        }
        (tmp_dir / f"{public_id(a['group_key'])}.json").write_text(json.dumps(detail, ensure_ascii=False, separators=(",", ":")))

    # výmena naraz, aby web nikdy nevidel polovičný export
    if detail_dir.exists():
        shutil.rmtree(detail_dir)
    tmp_dir.rename(detail_dir)
    (out / "auctions.json").write_text(json.dumps(items, ensure_ascii=False, separators=(",", ":")))
    runs = [dict(r) for r in con.execute(
        "SELECT source, started_at, finished_at, fetched, new_notices, new_auctions, errors, message"
        " FROM scrape_runs ORDER BY id DESC LIMIT 10")]
    meta = {
        "generated_at": now(),
        "count": len(items),
        "upcoming": sum(1 for i in items if i["s"] in ("pripravovana", "odrocena")),
        "by_source": dict(con.execute(
            "SELECT source, COUNT(DISTINCT auction_id) FROM notices GROUP BY source").fetchall()),
        "with_coords": sum(1 for i in items if i["lat"] is not None),
        "runs": runs,
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    log.info("export: %d dražieb → %s", len(items), out)
    return {"count": len(items), "with_coords": meta["with_coords"], "out": str(out)}


def short_title(a: dict, props: list[dict]) -> str:
    t = PROPERTY_TYPES.get(a["property_type"] or "ine", "Nehnuteľnosť")
    place = a["obec"] or a["ku"] or a["okres"] or ""
    s = f"{t}, {place}" if place else t
    area = next((p["area_m2"] for p in props if p.get("area_m2")), None)
    if area and a["property_type"] in ("byt", "dom", "nebytovy"):
        s += f", {area:g} m²".replace(".", ",")
    return s
