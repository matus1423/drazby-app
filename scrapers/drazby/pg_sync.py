"""Prelievanie SQLite → Supabase/Postgres (PostGIS).

    DATABASE_URL=postgresql://postgres:…@db.<projekt>.supabase.co:5432/postgres python -m drazby pgsync

Upsert podľa `id`; schéma musí existovať (supabase/migrations). Kým DATABASE_URL nie je
nastavená, príkaz nič nerobí – appka beží zo SQLite a statických JSON súborov.
"""

from __future__ import annotations

import json
import logging
import os

from .db import Store

log = logging.getLogger(__name__)

TABLES = {
    "auctions": None,
    "notices": None,
    "properties": None,
    "auction_history": None,
    "scrape_runs": None,
}

JSON_COLS = {"sources", "payload", "lv", "parcels", "supisne_cislo"}


def pg_sync(store: Store, url: str | None = None) -> dict:
    url = url or os.environ.get("DATABASE_URL")
    if not url:
        log.info("pgsync: DATABASE_URL nie je nastavená – preskakujem")
        return {"skipped": True}
    import psycopg  # voliteľná závislosť: pip install 'drazby[postgres]'

    stats = {}
    with psycopg.connect(url) as pg:
        for table in TABLES:
            rows = [dict(r) for r in store.con.execute(f"SELECT * FROM {table}")]
            if not rows:
                continue
            cols = list(rows[0].keys())
            out_cols, exprs = [], []
            for c in cols:
                if table == "auctions" and c in ("lat", "lng"):
                    continue
                if table == "properties" and c in ("lat", "lng", "geom"):
                    continue
                if table == "auctions" and c == "group_key":
                    pass
                out_cols.append(c)
                exprs.append("%s::jsonb" if c in JSON_COLS else "%s")
            extra = ""
            if table == "auctions":
                out_cols.append("geom")
                exprs.append("case when %s is null then null else st_setsrid(st_makepoint(%s, %s), 4326)::geography end")
            if table == "properties":
                out_cols += ["point", "geom"]
                exprs += ["case when %s is null then null else st_setsrid(st_makepoint(%s, %s), 4326)::geography end",
                          "case when %s is null then null else st_setsrid(st_geomfromgeojson(%s), 4326) end"]
            updates = ", ".join(f"{c}=excluded.{c}" for c in out_cols if c != "id")
            sql = (f"insert into {table} ({', '.join(out_cols)}) values ({', '.join(exprs)}) "
                   f"on conflict (id) do update set {updates}{extra}")
            batch = []
            for r in rows:
                vals = []
                for c in cols:
                    if (table == "auctions" and c in ("lat", "lng")) or (table == "properties" and c in ("lat", "lng", "geom")):
                        continue
                    v = r[c]
                    if c in JSON_COLS and v is not None and not isinstance(v, str):
                        v = json.dumps(v, ensure_ascii=False)
                    if c == "sold" and v is not None:
                        v = bool(v)
                    vals.append(v)
                if table == "auctions":
                    vals += [r["lat"], r["lng"], r["lat"]]
                if table == "properties":
                    vals += [r["lat"], r["lng"], r["lat"], r["geom"], r["geom"]]
                batch.append(vals)
            with pg.cursor() as cur:
                cur.executemany(sql, batch)
            stats[table] = len(batch)
            log.info("pgsync: %s → %d riadkov", table, len(batch))
    return stats
