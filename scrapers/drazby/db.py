"""Databázová vrstva (SQLite).

Model:
- `notices`   – jedno oznámenie z jedného zdroja (OV podanie, NCRD úkon). Surové, nemenné.
- `auctions`  – zjednotená dražba poskladaná z oznámení (aj naprieč zdrojmi a kolami).
- `properties`– nehnuteľnosti dražby (1:N, pozri DECISIONS.md).
- `auction_history` – zmeny sledovaných polí (dátum, kolo, najnižšie podanie, stav…).
- `scrape_runs` – log behov.

Tá istá schéma je pre Postgres/PostGIS v `supabase/migrations/`; `pg_sync.py` ju vie preliať.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from . import text as T
from .regions import kraj_for_obec, kraj_for_okres

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "drazby.sqlite"

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS auctions (
  id INTEGER PRIMARY KEY,
  group_key TEXT UNIQUE NOT NULL,
  kind TEXT NOT NULL,                -- dobrovolna | exekucna | danova
  status TEXT NOT NULL DEFAULT 'pripravovana',
  auction_number TEXT,
  auctioneer_name TEXT,
  auctioneer_ico TEXT,
  proposer TEXT,
  notary TEXT,
  auction_at TEXT,
  venue TEXT,
  round INTEGER,
  min_bid REAL,
  min_increment REAL,
  deposit REAL,
  appraised_value REAL,
  highest_bid REAL,
  sold INTEGER,
  inspection TEXT,
  title TEXT,
  description TEXT,
  reason TEXT,
  property_type TEXT,
  kraj TEXT,
  okres TEXT,
  obec TEXT,
  ku TEXT,
  lat REAL,
  lng REAL,
  geo_precision TEXT,                -- parcela | adresa | obec | okres
  sources TEXT NOT NULL DEFAULT '[]',-- JSON [{source,label,url}]
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  last_notice_at TEXT
);
CREATE INDEX IF NOT EXISTS auctions_date ON auctions(auction_at);
CREATE INDEX IF NOT EXISTS auctions_ico ON auctions(auctioneer_ico);

CREATE TABLE IF NOT EXISTS notices (
  id INTEGER PRIMARY KEY,
  source TEXT NOT NULL,              -- ov | ncrd
  source_id TEXT NOT NULL,
  auction_id INTEGER REFERENCES auctions(id),
  kind TEXT,
  notice_type TEXT,
  source_url TEXT,
  source_label TEXT,
  published_at TEXT,
  auction_at TEXT,
  payload TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  UNIQUE(source, source_id)
);
CREATE INDEX IF NOT EXISTS notices_auction ON notices(auction_id);

CREATE TABLE IF NOT EXISTS properties (
  id INTEGER PRIMARY KEY,
  auction_id INTEGER NOT NULL REFERENCES auctions(id) ON DELETE CASCADE,
  idx INTEGER NOT NULL,
  type TEXT,
  kraj TEXT, okres TEXT, obec TEXT, obec_code TEXT, ku TEXT,
  lv TEXT NOT NULL DEFAULT '[]',
  parcels TEXT NOT NULL DEFAULT '[]',
  supisne_cislo TEXT NOT NULL DEFAULT '[]',
  area_m2 REAL,
  address TEXT,
  share TEXT,
  lat REAL, lng REAL,
  geom TEXT,                         -- GeoJSON (polygón parcely)
  geo_source TEXT,
  UNIQUE(auction_id, idx)
);

CREATE TABLE IF NOT EXISTS auction_history (
  id INTEGER PRIMARY KEY,
  auction_id INTEGER NOT NULL REFERENCES auctions(id) ON DELETE CASCADE,
  changed_at TEXT NOT NULL,
  field TEXT NOT NULL,
  old_value TEXT,
  new_value TEXT,
  notice_id INTEGER REFERENCES notices(id)
);
CREATE INDEX IF NOT EXISTS history_auction ON auction_history(auction_id);

CREATE TABLE IF NOT EXISTS scrape_runs (
  id INTEGER PRIMARY KEY,
  source TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  fetched INTEGER DEFAULT 0,
  new_notices INTEGER DEFAULT 0,
  changed_notices INTEGER DEFAULT 0,
  new_auctions INTEGER DEFAULT 0,
  errors INTEGER DEFAULT 0,
  message TEXT
);

CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT);

-- surové podania (XML z OV), aby sa dali po oprave parsera prečítať znova (`drazby reparse`)
CREATE TABLE IF NOT EXISTS raw_items (
  source TEXT NOT NULL,
  source_id TEXT NOT NULL,
  file_name TEXT,
  content TEXT NOT NULL,
  meta TEXT NOT NULL DEFAULT '{}',
  fetched_at TEXT NOT NULL,
  PRIMARY KEY (source, source_id)
);

CREATE TABLE IF NOT EXISTS geocache (
  key TEXT PRIMARY KEY,
  lat REAL, lng REAL,
  precision TEXT,
  source TEXT,
  geom TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS saved_searches (
  id INTEGER PRIMARY KEY,
  email TEXT NOT NULL,
  name TEXT,
  filters TEXT NOT NULL,             -- JSON rovnaký ako filtre vo frontende
  created_at TEXT NOT NULL,
  last_notified_at TEXT,
  active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY,
  search_id INTEGER NOT NULL REFERENCES saved_searches(id) ON DELETE CASCADE,
  auction_id INTEGER NOT NULL REFERENCES auctions(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  sent_at TEXT,
  UNIQUE(search_id, auction_id)
);
"""

# polia, ktorých zmeny sledujeme v histórii
TRACKED = ["auction_at", "round", "min_bid", "appraised_value", "deposit", "venue", "status",
           "highest_bid", "auction_number"]

# polia, ktoré oznámenie môže nastaviť na dražbe
FIELDS = ["auction_number", "auctioneer_name", "auctioneer_ico", "proposer", "notary", "auction_at",
          "venue", "round", "min_bid", "min_increment", "deposit", "appraised_value", "highest_bid",
          "sold", "inspection", "title", "description", "reason"]

STATUS_BY_NOTICE = {
    "upustenie": "zrusena",
    "zmarenie": "zmarena",
    "neplatnost": "neplatna",
    "vysledok": "prebehla",
}

# priorita zdrojov pre obsahové polia: OV (štruktúrované) > NCRD
SOURCE_RANK = {"ov": 2, "ncrd": 1}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def content_hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:24]


class Store:
    def __init__(self, path: str | Path = DEFAULT_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(self.path)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA foreign_keys=ON")
        self.con.executescript(SCHEMA)

    def close(self):
        self.con.commit()
        self.con.close()

    # --- state -------------------------------------------------------------
    def get_state(self, key: str, default: str | None = None) -> str | None:
        r = self.con.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return r["value"] if r else default

    def set_state(self, key: str, value: str) -> None:
        self.con.execute("INSERT INTO state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                         (key, value))

    # --- runs --------------------------------------------------------------
    def start_run(self, source: str) -> int:
        cur = self.con.execute("INSERT INTO scrape_runs(source, started_at) VALUES(?,?)", (source, now()))
        self.con.commit()
        return cur.lastrowid

    def finish_run(self, run_id: int, stats: dict, message: str | None = None) -> None:
        self.con.execute(
            "UPDATE scrape_runs SET finished_at=?, fetched=?, new_notices=?, changed_notices=?, new_auctions=?,"
            " errors=?, message=? WHERE id=?",
            (now(), stats.get("fetched", 0), stats.get("new", 0), stats.get("changed", 0),
             stats.get("new_auctions", 0), stats.get("errors", 0), message, run_id))
        self.con.commit()

    # --- surové podania ------------------------------------------------------
    def save_raw(self, source: str, item: dict) -> None:
        meta = {k: item.get(k) for k in ("id", "file_name", "created_at", "updated_at", "bulletin_issue")}
        self.con.execute(
            "INSERT INTO raw_items(source, source_id, file_name, content, meta, fetched_at) VALUES(?,?,?,?,?,?)"
            " ON CONFLICT(source, source_id) DO UPDATE SET content=excluded.content, meta=excluded.meta,"
            " fetched_at=excluded.fetched_at",
            (source, str(item["id"]), item.get("file_name"), item.get("content") or "",
             json.dumps(meta, ensure_ascii=False), now()))

    def iter_raw(self, source: str):
        for r in self.con.execute("SELECT * FROM raw_items WHERE source=? ORDER BY CAST(source_id AS INTEGER)", (source,)):
            item = json.loads(r["meta"])
            item["content"] = r["content"]
            yield item

    # --- ingest ------------------------------------------------------------
    def ingest(self, n: dict) -> str:
        """Uloží oznámenie a premietne ho do dražby. Vracia 'new' | 'changed' | 'same'."""
        ts = now()
        h = content_hash({k: v for k, v in n.items() if k not in ("fetched_at",)})
        row = self.con.execute("SELECT id, content_hash, auction_id FROM notices WHERE source=? AND source_id=?",
                               (n["source"], n["source_id"])).fetchone()
        if row and row["content_hash"] == h:
            self.con.execute("UPDATE notices SET last_seen=? WHERE id=?", (ts, row["id"]))
            if row["auction_id"]:
                self.con.execute("UPDATE auctions SET last_seen=? WHERE id=?", (ts, row["auction_id"]))
            return "same"
        payload = json.dumps(n, ensure_ascii=False, default=str)
        if row:
            notice_id = row["id"]
            self.con.execute(
                "UPDATE notices SET payload=?, content_hash=?, last_seen=?, notice_type=?, auction_at=?, kind=? WHERE id=?",
                (payload, h, ts, n.get("notice_type"), n.get("auction_at"), n.get("kind"), notice_id))
            result = "changed"
        else:
            cur = self.con.execute(
                "INSERT INTO notices(source, source_id, kind, notice_type, source_url, source_label, published_at,"
                " auction_at, payload, content_hash, first_seen, last_seen) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (n["source"], n["source_id"], n.get("kind"), n.get("notice_type"), n.get("source_url"),
                 n.get("source_label"), n.get("published_at"), n.get("auction_at"), payload, h, ts, ts))
            notice_id = cur.lastrowid
            result = "new"
        auction_id, created = self._apply(n, notice_id, ts, existing=row["auction_id"] if row else None,
                                          reparsed=bool(row))
        self.con.execute("UPDATE notices SET auction_id=? WHERE id=?", (auction_id, notice_id))
        if created:
            self._new_auctions += 1
        return result

    _new_auctions = 0

    def pop_new_auctions(self) -> int:
        n, self._new_auctions = self._new_auctions, 0
        return n

    # --- skladanie dražby --------------------------------------------------
    def _group_key(self, n: dict) -> str:
        key = n.get("case_key") or f"{n['source']}|{n['source_id']}"
        if n.get("kind") == "exekucna":
            # jedna exekúcia môže dražiť viac rôznych nehnuteľností naraz → rozlíš podľa LV
            p = (n.get("properties") or [{}])[0]
            lv = ",".join(sorted(p.get("lv") or []))
            key += f"|{T.norm_key(p.get('ku'))}|{lv}"
        return key + n.get("_group_suffix", "")

    def find_auction(self, n: dict) -> int | None:
        from .dedup import compatible
        gk = self._group_key(n)
        r = self.con.execute("SELECT * FROM auctions WHERE group_key=?", (gk,)).fetchone()
        if r:
            if compatible(r, n):
                return r["id"]
            # rovnaký spis/LV, ale iná dražba v ten istý deň → vlastný kľúč
            n["_group_suffix"] = f"|{T.norm_key(n.get('auction_number'))}|{(n.get('auction_at') or '')[11:16]}"
            r2 = self.con.execute("SELECT id FROM auctions WHERE group_key=?", (gk + n["_group_suffix"],)).fetchone()
            return r2["id"] if r2 else None
        # alias kľúče (keď sa dražba už spojila s iným oznámením)
        r = self.con.execute("SELECT value FROM state WHERE key=?", (f"alias:{gk}",)).fetchone()
        if r:
            return int(r["value"])
        from .dedup import find_match
        return find_match(self.con, n)

    def _apply(self, n: dict, notice_id: int, ts: str, existing: int | None,
               reparsed: bool = False) -> tuple[int, bool]:
        auction_id = existing or self.find_auction(n)
        created = False
        if auction_id is None:
            gk = self._group_key(n)
            cur = self.con.execute(
                "INSERT INTO auctions(group_key, kind, first_seen, last_seen, updated_at) VALUES(?,?,?,?,?)",
                (gk, n.get("kind") or "dobrovolna", ts, ts, ts))
            auction_id = cur.lastrowid
            created = True
        else:
            gk = self._group_key(n)
            own = self.con.execute("SELECT group_key FROM auctions WHERE id=?", (auction_id,)).fetchone()["group_key"]
            if gk != own:
                self.set_state(f"alias:{gk}", str(auction_id))
        a = dict(self.con.execute("SELECT * FROM auctions WHERE id=?", (auction_id,)).fetchone())
        upd = self._merge(a, n, created)
        upd["last_seen"] = ts
        if n.get("published_at") and (not a.get("last_notice_at") or n["published_at"] >= a["last_notice_at"]):
            upd["last_notice_at"] = n["published_at"]
        # zdroje
        srcs = json.loads(a.get("sources") or "[]")
        entry = {"source": n["source"], "label": n.get("source_label"), "url": n.get("source_url"),
                 "notice_type": n.get("notice_type"), "published_at": n.get("published_at")}
        if not any(s.get("label") == entry["label"] and s.get("url") == entry["url"] for s in srcs):
            srcs.append(entry)
            upd["sources"] = json.dumps(srcs, ensure_ascii=False)
        # história
        changed = {k: v for k, v in upd.items() if k in TRACKED and _differs(a.get(k), v)}
        # do histórie len skutočné zmeny v rámci toho istého zdroja – rozdiel medzi NCRD a OV
        # (napr. 9:00 vs. 9:30, čiarka v mieste konania) nie je zmena dražby
        same_source = n["source"] in {s.get("source") for s in json.loads(a.get("sources") or "[]")}
        for k, v in changed.items():
            if k == "venue" and T.norm_key(a.get(k)) == T.norm_key(v):
                continue
            if k == "status" and v == "prebehla" and a.get(k) in ("zrusena", "zmarena", "neplatna"):
                continue
            if a.get(k) is not None and not created and (same_source or k == "status"):
                self.con.execute(
                    "INSERT INTO auction_history(auction_id, changed_at, field, old_value, new_value, notice_id)"
                    " VALUES(?,?,?,?,?,?)", (auction_id, n.get("published_at") or ts, k, _s(a.get(k)), _s(v), notice_id))
        upd["updated_at"] = ts if changed or created else a["updated_at"]
        sets = ", ".join(f"{k}=?" for k in upd)
        self.con.execute(f"UPDATE auctions SET {sets} WHERE id=?", (*upd.values(), auction_id))
        if n.get("properties"):
            self._set_properties(auction_id, n["properties"], n["source"], force=reparsed)
        self._refresh_location(auction_id)
        return auction_id, created

    def _merge(self, a: dict, n: dict, created: bool) -> dict:
        """Ktoré polia z oznámenia prepíšu dražbu."""
        upd: dict = {}
        nt = n.get("notice_type")
        src_rank = SOURCE_RANK.get(n["source"], 0)
        best_rank = max((SOURCE_RANK.get(s.get("source"), 0) for s in json.loads(a.get("sources") or "[]")), default=0)
        authoritative = created or src_rank >= best_rank
        newer = not a.get("last_notice_at") or (n.get("published_at") or "") >= (a.get("last_notice_at") or "")
        for f in FIELDS:
            v = n.get(f)
            if v in (None, "", []):
                continue
            if nt in ("upustenie", "zmarenie", "neplatnost", "vysledok", "dodatok") and f in (
                    "title", "description", "min_bid", "appraised_value", "round") and a.get(f) is not None:
                continue  # tieto oznámenia neopisujú celý predmet, len menia stav/dátum
            if nt in ("upustenie", "zmarenie", "neplatnost", "vysledok") and f == "auction_at" and a.get(f):
                continue  # tieto oznámenia neopisujú celý predmet, len menia stav/dátum
            if a.get(f) in (None, ""):
                upd[f] = v
            elif authoritative and newer:
                upd[f] = v
        if n.get("kind") and (created or not a.get("kind")):
            upd["kind"] = n["kind"]
        # stav
        st = STATUS_BY_NOTICE.get(nt)
        if st and (newer or a.get("status") in (None, "pripravovana", "odrocena")):
            upd["status"] = st
        elif nt in ("oznamenie", "opakovana") and newer:
            if a.get("status") in (None, "pripravovana", "prebehla", "zmarena") or created:
                upd["status"] = "pripravovana"
        elif nt == "dodatok" and n.get("auction_at") and a.get("auction_at") and _differs(a["auction_at"], n["auction_at"]):
            upd["status"] = "odrocena"
        if nt == "vysledok":
            if n.get("sold") is not None:
                upd["sold"] = 1 if n["sold"] else 0
            if n.get("highest_bid"):
                upd["highest_bid"] = n["highest_bid"]
        return upd

    def _set_properties(self, auction_id: int, props: list[dict], source: str, force: bool = False) -> None:
        old = [dict(r) for r in self.con.execute("SELECT * FROM properties WHERE auction_id=? ORDER BY idx", (auction_id,))]
        rich_new = sum(_richness(p) for p in props)
        rich_old = sum(_richness(p) for p in old)
        if old and rich_new < rich_old and not force:
            return
        geo = {(_pkey(o)): o for o in old if o.get("lat") is not None}
        self.con.execute("DELETE FROM properties WHERE auction_id=?", (auction_id,))
        for i, p in enumerate(props):
            g = geo.get(_pkey(p), {})
            self.con.execute(
                "INSERT INTO properties(auction_id, idx, type, kraj, okres, obec, obec_code, ku, lv, parcels,"
                " supisne_cislo, area_m2, address, share, lat, lng, geom, geo_source)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (auction_id, i, p.get("type"), p.get("kraj"), p.get("okres"), p.get("obec"), p.get("obec_code"),
                 p.get("ku"), json.dumps(p.get("lv") or [], ensure_ascii=False),
                 json.dumps(p.get("parcels") or [], ensure_ascii=False),
                 json.dumps(p.get("supisne_cislo") or [], ensure_ascii=False), p.get("area_m2"), p.get("address"),
                 p.get("share"), g.get("lat"), g.get("lng"), g.get("geom"), g.get("geo_source")))

    def _refresh_location(self, auction_id: int) -> None:
        """Zhrnie typ a polohu z nehnuteľností do dražby (na filtre)."""
        ps = [dict(r) for r in self.con.execute("SELECT * FROM properties WHERE auction_id=? ORDER BY idx", (auction_id,))]
        if not ps:
            return
        p = next((x for x in ps if x.get("obec") or x.get("ku")), ps[0])
        types = [x["type"] for x in ps if x.get("type")]
        ptype = _main_type(types)
        okres = p.get("okres")
        kraj = p.get("kraj") or kraj_for_okres(okres) or kraj_for_obec(p.get("obec"))
        pt = next((x for x in ps if x.get("lat") is not None), None)
        upd = {"property_type": ptype, "kraj": kraj, "okres": okres, "obec": p.get("obec"), "ku": p.get("ku")}
        if pt:
            upd.update({"lat": pt["lat"], "lng": pt["lng"], "geo_precision": pt.get("geo_source")})
        sets = ", ".join(f"{k}=?" for k in upd)
        self.con.execute(f"UPDATE auctions SET {sets} WHERE id=?", (*upd.values(), auction_id))

    def commit(self):
        self.con.commit()


def _differs(a, b) -> bool:
    if a is None and b is None:
        return False
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) > 0.005
    return _s(a) != _s(b)


def _s(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _richness(p: dict) -> int:
    def ln(x):
        if isinstance(x, str):
            try:
                x = json.loads(x)
            except ValueError:
                return 1
        return len(x or [])
    return sum(1 for k in ("obec", "ku", "okres", "kraj") if p.get(k)) + ln(p.get("lv")) + ln(p.get("parcels"))


def _pkey(p: dict) -> str:
    lv = p.get("lv")
    if isinstance(lv, str):
        lv = json.loads(lv or "[]")
    return f"{T.norm_key(p.get('ku') or p.get('obec'))}|{','.join(sorted(lv or []))}"


TYPE_PRIORITY = ["byt", "dom", "rekreacny", "nebytovy", "garaz", "pozemok", "ine"]


def _main_type(types: list[str]) -> str | None:
    for t in TYPE_PRIORITY:
        if t in types:
            return t
    return None


def effective_status(status: str | None, auction_at: str | None, today: date | None = None) -> str:
    today = today or date.today()
    st = status or "pripravovana"
    if st in ("pripravovana", "odrocena") and auction_at:
        try:
            d = date.fromisoformat(auction_at[:10])
        except ValueError:
            return st
        if d < today:
            return "prebehla"
    return st
