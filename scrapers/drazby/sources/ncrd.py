"""NCRD — Notársky centrálny register dražieb (www.notar.sk/drazby/).

Vyhľadávanie je obyčajný GET formulár, ale vracia najviac 20 riadkov bez stránkovania.
Preto sa pýtame po jednotlivých dňoch dražby a keď deň vráti 20, rozdelíme ho ešte
podľa typu úkonu.
"""

from __future__ import annotations

import io
import logging
import re
from datetime import date, timedelta
from typing import Iterator
from urllib.parse import urlencode

from selectolax.lexbor import LexborHTMLParser

from .. import text as T
from ..regions import kraj_for_obec

log = logging.getLogger(__name__)

BASE = "https://www.notar.sk"
SEARCH = f"{BASE}/drazby/"
LIMIT = 20

ACT_TYPES = {
    "NEW_AUCTION": "oznamenie",
    "AUCTION_CHANGE_OR_ADDITION": "dodatok",
    "AUCTION_RENOUNCEMENT": "upustenie",
    "AUCTION_DEFEAT": "zmarenie",
    "AUCTION_INVALID": "neplatnost",
    "REPEATED_AUCTION": "opakovana",
    "AUCTION_RESULT": "vysledok",
}

ACT_LABELS = {
    "oznámenie o dražbe": "oznamenie",
    "zmena v oznámení o dražbe": "dodatok",
    "dodatok": "dodatok",
    "oznámenie o upustení od dražby": "upustenie",
    "oznámenie o zmarení dražby": "zmarenie",
    "oznámenie o neplatnosti dražby": "neplatnost",
    "oznámenie o konaní opakovanej dražby": "opakovana",
    "oznámenie o výsledku dražby": "vysledok",
}


def notice_type_from_label(label: str | None) -> str:
    low = (label or "").lower().strip()
    for k, v in ACT_LABELS.items():
        if low.startswith(k):
            return v
    return "ine"


def search_url(day_from: date, day_to: date, act_type: str = "") -> str:
    q = {
        "actNumber1": "", "actNumber2": "", "auctioneerName": "", "auctioneerCode": "",
        "subjectCity": "", "subjectRegionCode": "", "subjectDistrictCode": "", "subjectMunicipalityCode": "",
        "AuctionActType": act_type, "auctionDateFrom": day_from.isoformat(), "auctionDateTo": day_to.isoformat(),
        "auctioneerIdentifier": "", "venueCity": "", "venueRegionCode": "", "venueDistrictCode": "",
        "venueMunicipalityCode": "", "auction-search": "Hľadať",
    }
    return f"{SEARCH}?{urlencode(q)}"


# ---------------------------------------------------------------------------
# Zoznam
# ---------------------------------------------------------------------------

def parse_search(html: str) -> list[dict]:
    tree = LexborHTMLParser(html)
    out = []
    for tr in tree.css("table.search_results tbody tr"):
        tds = tr.css("td")
        if len(tds) < 6:
            continue
        a = tds[0].css_first("a")
        if not a:
            continue
        href = a.attributes.get("href") or ""
        m = re.search(r"actId=([0-9a-f]+)", href)
        if not m:
            continue
        orig = tds[4].css_first("a")
        orig_id = None
        if orig:
            mo = re.search(r"actId=([0-9a-f]+)", orig.attributes.get("href") or "")
            orig_id = mo.group(1) if mo else None

        def cell(i):
            return T.squash(tds[i].text(separator=" "))

        auct = cell(1)
        mi = re.search(r"IČO:\s*(\d+)", auct)
        out.append({
            "act_id": m.group(1),
            "number": T.squash(a.text()),
            "auctioneer_name": T.squash(re.sub(r"IČO:.*", "", auct)) or None,
            "auctioneer_ico": mi.group(1) if mi else None,
            "proposer": T.squash(re.sub(r"IČO:\s*\d*", "", cell(2))) or None,
            "act_label": cell(3),
            "orig_number": T.squash(orig.text()) if orig else None,
            "orig_act_id": orig_id,
            "auction_date": T.parse_date(cell(5)),
        })
    return out


def iter_listing(client, day_from: date, day_to: date) -> Iterator[dict]:
    """Všetky riadky zoznamu medzi dvoma dátumami (vrátane), deň po dni."""
    d = day_from
    while d <= day_to:
        rows = parse_search(client.get(search_url(d, d)).text)
        if len(rows) >= LIMIT:
            seen = set()
            rows = []
            for code in ACT_TYPES:
                part = parse_search(client.get(search_url(d, d, code)).text)
                if len(part) >= LIMIT:
                    log.warning("NCRD %s typ %s má ≥20 záznamov – časť môže chýbať", d, code)
                for r in part:
                    if r["act_id"] not in seen:
                        seen.add(r["act_id"])
                        rows.append(r)
        yield from rows
        d += timedelta(days=1)


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------

DETAIL_LABELS = [
    "Označenie notára, ktorý registráciu vykonal",
    "Spisová značka NCRdr",
    "Dátum a čas vykonania zápisu v NCRdr",
    "Registrovaný a uverejnený úkon v NCRdr",
    "Dražobník",
    "Navrhovateľ (-ia) dražby",
    "Miesto konania dražby",
    "Bližšie označenie miesta konania dražby",
    "Dátum a čas otvorenia dražby",
    "Druh predmetu dražby",
    "Súvisiace spisové značky",
    "Poznámka",
    "Uverejnené listiny",
]


def detail_url(act_id: str) -> str:
    return f"{BASE}/drazba?actId={act_id}"


def parse_detail(html: str) -> dict:
    tree = LexborHTMLParser(html)
    for n in tree.css("script,style,header,footer,nav"):
        n.decompose()
    body = tree.body
    txt = body.text(separator="\n") if body else ""
    lines = [T.squash(x) for x in txt.split("\n")]
    lines = [x for x in lines if x]
    fields: dict[str, str] = {}
    cur = None
    for ln in lines:
        lab = next((L for L in DETAIL_LABELS if ln.rstrip(":").strip() == L), None)
        if lab:
            cur = lab
            fields.setdefault(cur, "")
            continue
        if ln.startswith("CIS NK SR") or ln.startswith("Výpis má informatívny"):
            cur = None
        if cur:
            fields[cur] = (fields[cur] + " " + ln).strip()
    docs = []
    for a in tree.css("a"):
        href = a.attributes.get("href") or ""
        if "/listina/" in href:
            docs.append({"title": T.squash(a.text()), "url": href if href.startswith("http") else BASE + href})
    return {"fields": fields, "documents": docs}


def to_notice(row: dict, det: dict, pdf_text: str | None = None) -> dict | None:
    f = det["fields"]
    if not f.get("Spisová značka NCRdr") or not f.get("Dátum a čas vykonania zápisu v NCRdr"):
        # web pri preťažení vracia stránku bez údajov – nič neukladať, skúsi sa nabudúce
        raise ValueError("prázdny detail NCRD")
    druh = (f.get("Druh predmetu dražby") or "").lower()
    if druh and "nehnuteľn" not in druh:
        return None  # hnuteľné veci (autá, stroje…) nás nezaujímajú
    number = f.get("Spisová značka NCRdr") or row.get("number")
    label = f.get("Registrovaný a uverejnený úkon v NCRdr") or row.get("act_label")
    nt = notice_type_from_label(label)
    auct = f.get("Dražobník") or ""
    mi = re.search(r"IČO:\s*(\d+)", auct)
    auct_name = T.squash(auct.split(",")[0]) if auct else row.get("auctioneer_name")
    venue = ", ".join(x for x in [f.get("Miesto konania dražby"), f.get("Bližšie označenie miesta konania dražby")] if x)
    notary = f.get("Označenie notára, ktorý registráciu vykonal")
    notary = T.squash(notary.split(",")[0].split("(")[0]) if notary else None
    proposer = f.get("Navrhovateľ (-ia) dražby")
    if proposer:
        proposer = "; ".join(T.squash(p.split(",")[0]) for p in re.split(r"(?<=Slovenská republika)\s*", proposer) if p.strip())
    orig = row.get("orig_number")
    props: list[dict] = []
    min_bid = appraised = deposit = increment = None
    title = None
    if pdf_text:
        cad = T.extract_cadastre(pdf_text)
        ptype = T.detect_property_type(pdf_text[:4000])
        if cad:
            obec = cad.get("obec") or cad.get("ku")
            props = [{"type": ptype, "kraj": kraj_for_obec(cad.get("okres") or obec), "okres": cad.get("okres"),
                      "obec": obec, "ku": cad.get("ku"), "lv": cad.get("lv") or [],
                      "parcels": cad.get("parcels") or [], "supisne_cislo": cad.get("supisne_cislo") or [],
                      "area_m2": cad.get("area_m2"), "address": None}]
        min_bid = T.find_money_after(pdf_text, "najnižšie podanie", "najnizsie podanie")
        appraised = T.find_money_after(pdf_text, "odhadu", "znaleck", "ocenenie", "cena predmetu dražby")
        deposit = T.find_money_after(pdf_text, "výška dražobnej zábezpeky", "dražobná zábezpeka", "zábezpek")
        increment = T.find_money_after(pdf_text, "minimálne prihodenie")
    return {
        "source": "ncrd",
        "source_id": row["act_id"],
        "source_url": detail_url(row["act_id"]),
        "source_label": f"NCRD {number}",
        "published_at": (T.parse_date(f.get("Dátum a čas vykonania zápisu v NCRdr")) or None)
        and str(T.parse_date(f.get("Dátum a čas vykonania zápisu v NCRdr"))),
        "kind": "dobrovolna",
        "notice_type": nt,
        "ncrd_number": number,
        "auction_number": None,
        "case_key": f"ncrd|{orig or number}",
        "auctioneer_name": auct_name or None,
        "auctioneer_ico": mi.group(1) if mi else row.get("auctioneer_ico"),
        "proposer": proposer or row.get("proposer"),
        "notary": notary,
        "auction_at": T.parse_datetime_sk(f.get("Dátum a čas otvorenia dražby"))
        or (row.get("auction_date") and str(row["auction_date"])),
        "venue": venue or None,
        "round": 2 if nt == "opakovana" else None,
        "min_bid": min_bid,
        "min_increment": increment,
        "deposit": deposit,
        "appraised_value": appraised,
        "highest_bid": None,
        "title": title,
        "description": pdf_text[:20000] if pdf_text else None,
        "documents": det.get("documents") or [],
        "properties": props,
    }


def pdf_to_text(data: bytes) -> str:
    """Text z PDF. Väčšina listín NCRD sú skeny → vráti prázdny reťazec (OCR nerobíme)."""
    import pdfplumber
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return "\n".join((p.extract_text() or "") for p in pdf.pages[:15]).strip()
    except Exception as e:  # poškodené PDF
        log.warning("PDF sa nedá prečítať: %s", e)
        return ""
