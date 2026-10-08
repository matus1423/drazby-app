"""Deduplikácia: nájde existujúcu dražbu, ku ktorej oznámenie patrí.

Pravidlá (v poradí):
A) Rovnaká dražba v inom zdroji (NCRD ↔ OV): rovnaký dražobník (IČO alebo meno)
   a rovnaký deň dražby; pri viacerých kandidátoch rozhodne čas, potom obec/k. ú./miesto.
B) Ďalšie kolo tej istej dražby (nové číslo dražby): rovnaký dražobník, rovnaký druh,
   prekryv k. ú. + LV a dátumy dražieb sú od seba najviac rok (kolá prichádzajú v ľubovoľnom poradí).
   Exekútorov porovnávame bez titulov a bez ohľadu na poradie mena a priezviska.
"""

from __future__ import annotations

import json
import sqlite3

from . import text as T


MIN_ROUND_GAP_DAYS = 14


def compatible(row, n: dict) -> bool:
    """Môže oznámenie patriť k tejto dražbe? Nie, ak je v ten istý deň v inom čase a s iným číslom."""
    a, b = row["auction_at"] or "", n.get("auction_at") or ""
    if a[:10] and a[:10] == b[:10] and len(a) > 10 and len(b) > 10 and a[11:16] != b[11:16]:
        na, nb = T.norm_key(row["auction_number"]), T.norm_key(n.get("auction_number"))
        if na and nb and na != nb:
            return False
    return True


def _auctioneer_clause(n: dict) -> tuple[str, list]:
    ico = n.get("auctioneer_ico")
    name = T.norm_key(n.get("auctioneer_name"))
    if ico:
        return "(auctioneer_ico = ? OR (auctioneer_ico IS NULL AND auctioneer_name IS NOT NULL))", [ico]
    if name:
        return "auctioneer_name IS NOT NULL", []
    return "", []


def _same_auctioneer(row: sqlite3.Row, n: dict) -> bool:
    if n.get("auctioneer_ico") and row["auctioneer_ico"]:
        return n["auctioneer_ico"] == row["auctioneer_ico"]
    from .sources.ov import executor_key
    if row["kind"] == "exekucna" or n.get("kind") == "exekucna":
        return executor_key(row["auctioneer_name"]) == executor_key(n.get("auctioneer_name"))
    a, b = T.norm_key(row["auctioneer_name"]), T.norm_key(n.get("auctioneer_name"))
    if not a or not b:
        return False
    return a == b or (len(a) > 6 and len(b) > 6 and (a in b or b in a))


def _place_tokens(*vals) -> set[str]:
    out = set()
    for v in vals:
        for w in T.norm_key(v).split():
            if len(w) > 3:
                out.add(w)
    return out


def _lv_set(con, auction_id: int) -> set[tuple[str, str]]:
    s = set()
    for r in con.execute("SELECT ku, obec, lv FROM properties WHERE auction_id=?", (auction_id,)):
        for lv in json.loads(r["lv"] or "[]"):
            s.add((T.norm_key(r["ku"] or r["obec"]), str(lv)))
    return s


def _notice_lv_set(n: dict) -> set[tuple[str, str]]:
    s = set()
    for p in n.get("properties") or []:
        for lv in p.get("lv") or []:
            s.add((T.norm_key(p.get("ku") or p.get("obec")), str(lv)))
    return s


def find_match(con: sqlite3.Connection, n: dict) -> int | None:
    clause, params = _auctioneer_clause(n)
    if not clause:
        return None
    day = (n.get("auction_at") or "")[:10]

    # A) rovnaký deň, rovnaký dražobník, iný zdroj alebo bez čísla
    if day:
        rows = [r for r in con.execute(
            f"SELECT * FROM auctions WHERE substr(auction_at,1,10)=? AND {clause}", [day, *params])
            if _same_auctioneer(r, n)]
        if n.get("kind") in ("dobrovolna", None) or n["source"] == "ncrd":
            rows = [r for r in rows if r["kind"] == "dobrovolna"]
        else:
            rows = [r for r in rows if r["kind"] == n.get("kind")]
        # pravidlo A páruje len naprieč zdrojmi (NCRD ↔ OV); v rámci jedného zdroja rozhoduje
        # kľúč (číslo dražby / spis + LV) – inak by sa zlepili rôzne dražby toho istého dňa
        rows = [r for r in rows if n["source"] not in {s.get("source") for s in json.loads(r["sources"] or "[]")}]
        rows = [r for r in rows if not _same_source_other_number(con, r, n)]
        lvs_n = _notice_lv_set(n)
        if lvs_n:
            rows = [r for r in rows if not (_lv_set(con, r["id"]) and not (lvs_n & _lv_set(con, r["id"])))]
        if len(rows) > 1:
            tm = (n.get("auction_at") or "")[11:16]
            if tm:
                by_time = [r for r in rows if (r["auction_at"] or "")[11:16] == tm]
                if by_time:
                    rows = by_time
        if len(rows) > 1:
            toks = _place_tokens(n.get("venue"), *[p.get("obec") for p in n.get("properties") or []],
                                 *[p.get("ku") for p in n.get("properties") or []])
            scored = sorted(((len(toks & _place_tokens(r["venue"], r["obec"], r["ku"])), r) for r in rows),
                            key=lambda x: -x[0])
            if scored and scored[0][0] > 0 and (len(scored) == 1 or scored[0][0] > scored[1][0]):
                rows = [scored[0][1]]
        if len(rows) == 1:
            return rows[0]["id"]

    # B) ďalšie kolo: prekryv k. ú. + LV
    lvs = _notice_lv_set(n)
    if lvs and n.get("kind"):
        rows = [r for r in con.execute(
            f"SELECT * FROM auctions WHERE kind=? AND {clause} ORDER BY auction_at DESC", [n["kind"], *params])
            if _same_auctioneer(r, n)]
        for r in rows:
            # kolá môžu prísť v ľubovoľnom poradí (Datahub radí podľa času zverejnenia),
            # preto stačí, že sú od seba najviac rok
            if day and r["auction_at"]:
                gap = abs((_d(r["auction_at"]) - _d(day)).days)
                # ďalšie kolo býva o týždne až mesiace; tesne po sebe = iná dražba (iný byt v tom istom dome)
                if gap > 366 or gap < MIN_ROUND_GAP_DAYS:
                    continue
            if lvs & _lv_set(con, r["id"]):
                return r["id"]
    return None


def _d(s: str):
    from datetime import date
    return date.fromisoformat(s[:10])


def _same_source_other_number(con, row: sqlite3.Row, n: dict) -> bool:
    """Dve oznámenia z toho istého zdroja s rôznym číslom/spisom v ten istý deň = dve rôzne dražby.

    OV: rôzne číslo dražby. NCRD: rôzny spis (pôvodné oznámenie NCRdr) – jedna dražba má len jeden.
    """
    if n["source"] == "ncrd":
        keys = {r["k"] for r in con.execute(
            "SELECT json_extract(payload, '$.case_key') AS k FROM notices WHERE auction_id=? AND source='ncrd'",
            (row["id"],))}
        return bool(keys) and n.get("case_key") not in keys
    if n["source"] != "ov" or not n.get("auction_number") or not row["auction_number"]:
        return False
    srcs = {s.get("source") for s in json.loads(row["sources"] or "[]")}
    if "ov" not in srcs:
        return False
    return T.norm_key(row["auction_number"]) != T.norm_key(n["auction_number"])
