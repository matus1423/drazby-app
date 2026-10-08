"""Príkazový riadok.

    python -m drazby ov                 # inkrementálne z Obchodného vestníka (Datahub)
    python -m drazby ov --since 2026-07-01
    python -m drazby ncrd               # NCRD: -7 dní až +120 dní od dnes
    python -m drazby geocode
    python -m drazby export             # web/public/data/*.json
    python -m drazby daily              # všetko za sebou (pre cron)
    python -m drazby stats
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import db as dbm
from .http import Blocked, PoliteClient, RateLimited

log = logging.getLogger("drazby")

ROOT = Path(__file__).resolve().parents[2]


def cmd_ov(store: dbm.Store, args) -> dict:
    from .sources import ov
    since = args.since or store.get_state("ov:since") or (
        datetime.now(timezone.utc) - timedelta(days=args.days)).strftime("%Y-%m-%dT00:00:00Z")
    if len(since) == 10:
        since += "T00:00:00Z"
    log.info("OV: od %s", since)
    stats = {"fetched": 0, "new": 0, "changed": 0, "errors": 0, "auctions": 0}
    run = store.start_run("ov")
    last = since
    t0 = time.time()
    # Datahub: 60 req/min → 1,1 s medzi požiadavkami
    with PoliteClient(min_delay=1.1) as c:
        try:
            for i, item in enumerate(ov.iter_raw(c, since, max_pages=args.max_pages)):
                stats["fetched"] += 1
                last = item.get("updated_at") or item.get("created_at") or last
                if not ov.is_auction(item.get("file_name")):
                    continue
                if item.get("content"):
                    store.save_raw("ov", item)
                try:
                    n = ov.parse_item(item)
                except Exception as e:  # jedna zlá položka nesmie zastaviť beh
                    stats["errors"] += 1
                    log.exception("OV %s: chyba parsera: %s", item.get("id"), e)
                    continue
                if not n:
                    continue
                stats["auctions"] += 1
                _ingest_count(store, n, stats)
                if i % 500 == 0:
                    store.commit()
                    store.set_state("ov:since", last)
                    log.info("OV: %d podaní, %d dražobných, posledné %s (%.0f s)",
                             stats["fetched"], stats["auctions"], last[:19], time.time() - t0)
        except Exception as e:
            stats["errors"] += 1
            log.error("OV: beh prerušený: %s", e)
            store.commit()
            store.set_state("ov:since", last)
            store.finish_run(run, {**stats, "new_auctions": store.pop_new_auctions()}, f"prerušené: {e}")
            raise
    store.set_state("ov:since", last)
    store.commit()
    store.finish_run(run, {**stats, "new_auctions": store.pop_new_auctions()})
    return stats


def _ingest_count(store, n, stats):
    r = store.ingest(n)
    stats[r] = stats.get(r, 0) + 1


def cmd_ncrd(store: dbm.Store, args) -> dict:
    from .sources import ncrd
    today = date.today()
    d_from = date.fromisoformat(args.date_from) if args.date_from else today - timedelta(days=7)
    d_to = date.fromisoformat(args.date_to) if args.date_to else today + timedelta(days=120)
    stats = {"fetched": 0, "new": 0, "changed": 0, "same": 0, "errors": 0, "skipped": 0}
    run = store.start_run("ncrd")
    known = {r["source_id"] for r in store.con.execute("SELECT source_id FROM notices WHERE source='ncrd'")}
    known |= set(json.loads(store.get_state("ncrd:skipped", "[]")))
    skipped = set(json.loads(store.get_state("ncrd:skipped", "[]")))
    # pri 1,5 s notar.sk vracal 503 a potom Retry-After: 3600 → pomalšie a bez PDF (väčšinou skeny)
    with PoliteClient(min_delay=5.0) as c:
        try:
            for row in ncrd.iter_listing(c, d_from, d_to):
                stats["fetched"] += 1
                if row["act_id"] in known and not args.refresh:
                    continue
                try:
                    html = c.get(ncrd.detail_url(row["act_id"])).text
                    det = ncrd.parse_detail(html)
                    pdf_text = None
                    if args.pdf and det["documents"]:
                        data = c.get(det["documents"][0]["url"]).content
                        pdf_text = ncrd.pdf_to_text(data) or None
                    n = ncrd.to_notice(row, det, pdf_text)
                except (Blocked, RateLimited):
                    raise
                except Exception as e:
                    stats["errors"] += 1
                    log.warning("NCRD %s: %s", row["act_id"], e)
                    continue
                if n is None:
                    stats["skipped"] += 1
                    skipped.add(row["act_id"])
                    continue
                _ingest_count(store, n, stats)
                store.commit()
        except RateLimited as e:
            # slušne skončiť – čo sme stihli, je uložené; zvyšok dobehne pri ďalšom behu
            log.warning("NCRD: %s – končím, pokračujem pri ďalšom behu", e)
            store.set_state("ncrd:skipped", json.dumps(sorted(skipped)))
            store.commit()
            store.finish_run(run, {**stats, "new_auctions": store.pop_new_auctions()}, f"obmedzené zdrojom: {e}")
            return {**stats, "rate_limited": str(e)}
        except Exception as e:
            stats["errors"] += 1
            log.error("NCRD: beh prerušený: %s", e)
            store.set_state("ncrd:skipped", json.dumps(sorted(skipped)))
            store.finish_run(run, {**stats, "new_auctions": store.pop_new_auctions()}, f"prerušené: {e}")
            raise
    store.set_state("ncrd:skipped", json.dumps(sorted(skipped)))
    store.commit()
    store.finish_run(run, {**stats, "new_auctions": store.pop_new_auctions()})
    return stats


def cmd_reparse(store, args):
    """Znova prečíta uložené podania OV aktuálnym parserom (po oprave parsera).

    Podania stiahnuté pred zavedením `raw_items` sa najprv dotiahnu z Datahubu podľa id.
    """
    from .sources import ov
    missing = [r["source_id"] for r in store.con.execute(
        "SELECT source_id FROM notices WHERE source='ov' AND source_id NOT IN"
        " (SELECT source_id FROM raw_items WHERE source='ov')")]
    stats = {"fetched": 0, "reparsed": 0, "changed": 0, "same": 0, "new": 0, "errors": 0}
    if missing:
        log.info("reparse: dosťahujem %d podaní z Datahubu", len(missing))
        with PoliteClient(min_delay=1.1) as c:
            for sid in missing:
                try:
                    item = c.get(f"{ov.DATAHUB_SYNC.rsplit('/', 1)[0]}/{sid}").json()
                except Exception as e:
                    stats["errors"] += 1
                    log.warning("reparse: %s → %s", sid, e)
                    continue
                if item.get("content"):
                    store.save_raw("ov", item)
                    stats["fetched"] += 1
                if stats["fetched"] % 50 == 0:
                    store.commit()
        store.commit()
    for item in store.iter_raw("ov"):
        try:
            n = ov.parse_item(item)
        except Exception as e:
            stats["errors"] += 1
            log.warning("reparse: %s → %s", item.get("id"), e)
            continue
        if not n:
            continue
        stats["reparsed"] += 1
        _ingest_count(store, n, stats)
    store.commit()
    return stats


def cmd_rebuild(store, args):
    """Poskladá všetky dražby nanovo z uložených oznámení (po zmene deduplikácie alebo parsera).

    OV sa číta zo surových XML (`raw_items`) aktuálnym parserom, NCRD z uložených oznámení.
    Všetko sa vloží v poradí zverejnenia, takže kolá, dodatky a výsledky sa spoja správne.
    Polohy z katastra ostávajú v `geocache`, takže následný `geocode` je rýchly.
    Pozor: čísla dražieb (id) sa zmenia.
    """
    from .sources import ov
    con = store.con
    notices = []
    for item in store.iter_raw("ov"):
        try:
            n = ov.parse_item(item)
        except Exception as e:
            log.warning("rebuild: OV %s → %s", item.get("id"), e)
            continue
        if n:
            notices.append(n)
    # NCRD a podania OV bez uloženého XML → už prečítané oznámenie z databázy
    for r in con.execute("SELECT payload FROM notices WHERE source != 'ov' OR source_id NOT IN"
                         " (SELECT source_id FROM raw_items WHERE source='ov')"):
        notices.append(json.loads(r["payload"]))
    for t in ("notifications", "auction_history", "properties", "notices", "auctions"):
        con.execute(f"DELETE FROM {t}")
    con.execute("DELETE FROM state WHERE key LIKE 'alias:%'")
    notices.sort(key=lambda n: (n.get("published_at") or "", n["source"] != "ov", str(n["source_id"])))
    stats = {"notices": len(notices)}
    for n in notices:
        _ingest_count(store, n, stats)
    store.commit()
    stats["auctions"] = con.execute("SELECT COUNT(*) FROM auctions").fetchone()[0]
    store.pop_new_auctions()
    return stats


def cmd_geocode(store, args):
    from .geocode import geocode_all
    return geocode_all(store, limit=args.limit, use_cadastre=not args.no_cadastre, redo=args.redo)


def cmd_export(store, args):
    from .export import export
    return export(store, Path(args.out))


def cmd_notify(store, args):
    from .notify import run_notifications
    return run_notifications(store, outdir=Path(args.out), dry_run=not args.send)


def cmd_pgsync(store, args):
    from .pg_sync import pg_sync
    return pg_sync(store)


def cmd_search_add(store, args):
    from .notify import add_search
    sid = add_search(store, args.email, json.loads(args.filters), args.name)
    return {"id": sid}


def cmd_stats(store, args):
    con = store.con
    out = {
        "auctions": con.execute("SELECT COUNT(*) FROM auctions").fetchone()[0],
        "by_kind": dict(con.execute("SELECT kind, COUNT(*) FROM auctions GROUP BY kind").fetchall()),
        "by_status": dict(con.execute("SELECT status, COUNT(*) FROM auctions GROUP BY status").fetchall()),
        "notices_by_source": dict(con.execute("SELECT source, COUNT(*) FROM notices GROUP BY source").fetchall()),
        "with_coords": con.execute("SELECT COUNT(*) FROM auctions WHERE lat IS NOT NULL").fetchone()[0],
        "geo_precision": dict(con.execute(
            "SELECT COALESCE(geo_precision,'-'), COUNT(*) FROM auctions GROUP BY 1").fetchall()),
        "upcoming": con.execute("SELECT COUNT(*) FROM auctions WHERE auction_at >= date('now')").fetchone()[0],
        "multi_source": con.execute(
            "SELECT COUNT(*) FROM auctions WHERE sources LIKE '%\"ncrd\"%' AND sources LIKE '%\"ov\"%'").fetchone()[0],
        "history_rows": con.execute("SELECT COUNT(*) FROM auction_history").fetchone()[0],
        "last_runs": [dict(r) for r in con.execute(
            "SELECT source, started_at, finished_at, fetched, new_notices, new_auctions, errors, message"
            " FROM scrape_runs ORDER BY id DESC LIMIT 6")],
    }
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return out


def cmd_daily(store, args):
    res = {}
    for name, fn in [("ov", cmd_ov), ("ncrd", cmd_ncrd), ("geocode", cmd_geocode), ("export", cmd_export),
                     ("notify", cmd_notify), ("pgsync", cmd_pgsync)]:
        try:
            res[name] = fn(store, args)
        except Exception as e:  # jeden zdroj nesmie zhodiť ostatné
            log.exception("%s zlyhal: %s", name, e)
            res[name] = {"error": str(e)}
    print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    failed = [k for k, v in res.items() if isinstance(v, dict) and v.get("error")]
    return 1 if len(failed) == len(res) else 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="drazby", description="Zber dražieb nehnuteľností (SK)")
    p.add_argument("--db", default=str(dbm.DEFAULT_PATH))
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--since", help="OV: od kedy (ISO dátum/čas)")
        sp.add_argument("--days", type=int, default=120, help="OV: pri prvom behu koľko dní dozadu")
        sp.add_argument("--max-pages", type=int, default=None)
        sp.add_argument("--from", dest="date_from")
        sp.add_argument("--to", dest="date_to")
        sp.add_argument("--refresh", action="store_true")
        sp.add_argument("--pdf", action="store_true", default=False, help="NCRD: sťahovať aj PDF listiny")
        sp.add_argument("--no-pdf", dest="pdf", action="store_false")
        sp.add_argument("--limit", type=int, default=None)
        sp.add_argument("--no-cadastre", action="store_true")
        sp.add_argument("--redo", action="store_true", help="geocode: prejsť znova aj nájdené parcely")
        sp.add_argument("--out", default=str(ROOT / "web" / "public" / "data"))
        sp.add_argument("--send", action="store_true", help="notify: naozaj poslať e-maily (inak len uloží)")

    for name in ["ov", "ncrd", "geocode", "export", "notify", "stats", "daily", "pgsync", "reparse", "rebuild"]:
        common(sub.add_parser(name))
    sa = sub.add_parser("search-add", help="uložiť hľadanie s e-mailovým upozornením")
    sa.add_argument("--email", required=True)
    sa.add_argument("--filters", required=True, help='JSON, napr. \'{"kraj":"Žilinský kraj","types":["byt"]}\'')
    sa.add_argument("--name")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    store = dbm.Store(args.db)
    try:
        fn = globals()[f"cmd_{args.cmd.replace('-', '_')}"]
        res = fn(store, args)
        if args.cmd in ("ov", "ncrd", "geocode", "export", "notify", "pgsync", "search-add", "reparse", "rebuild"):
            print(json.dumps(res, ensure_ascii=False, default=str))
        return res if isinstance(res, int) else 0
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
