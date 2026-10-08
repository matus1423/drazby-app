"""Obchodný vestník cez Slovensko.Digital Datahub.

Datahub vracia pôvodné XML podaní OV. Z nich vyberáme dražby (dobrovoľné, exekučné,
daňové) a prevádzame ich na jednotný formát „oznámenia“ (notice), z ktorého
`db.py` skladá dražby a ich históriu.
"""

from __future__ import annotations

import html as htmlmod
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Iterator

from selectolax.lexbor import LexborHTMLParser

from .. import text as T
from ..regions import NUTS3, kraj_for_obec, kraj_for_okres, normalize_okres

log = logging.getLogger(__name__)

DATAHUB_SYNC = "https://datahub.ekosystem.slovensko.digital/api/data/ov/raw_issues/sync"
OV_SEARCH_URL = "https://obchodnyvestnik.justice.gov.sk/ObchodnyVestnik/Formular/FormulareZverejnene.aspx"

# typ podania (z file_name) → (druh dražby, typ oznámenia)
DOBROVOLNA_TYPES = {
    "OV_DRAZBA_OZNAMENIE_DOBROVOLNA": "oznamenie",
    "OV_DRAZBA_OZNAMENIE_DOBROVOLNA_OPAKOVANA": "opakovana",
    "OV_DRAZBA_OZNAMENIE_DOBROVOLNA_DODATOK": "dodatok",
    "OV_DRAZBA_OZNAMENIE_DOBROVOLNA_UPUSTENIE": "upustenie",
    "OV_DRAZBA_OZNAMENIE_DOBROVOLNA_ZMARENIE": "zmarenie",
    "OV_DRAZBA_OZNAMENIE_DOBROVOLNA_VYSLEDOK": "vysledok",
    "OV_DRAZBA_OZNAMENIE_DOBROVOLNA_OPAKOVANA_VYSLEDOK": "vysledok",
    "OV_DRAZBA_OZNAMENIE_DOBROVOLNA_NEPLATNOST": "neplatnost",
}


def form_type(file_name: str | None) -> str | None:
    """'X059090-OV_DRAZBA_OZNAMENIE_DOBROVOLNA-v-2.xml' → 'OV_DRAZBA_OZNAMENIE_DOBROVOLNA'."""
    if not file_name or not file_name.lower().endswith(".xml"):
        return None
    rest = file_name.split("-", 1)[1] if "-" in file_name else file_name
    return rest.split("-v-")[0]


def is_auction(file_name: str | None) -> bool:
    ft = form_type(file_name)
    if not ft:
        return False
    return ft.startswith("OV_DRAZBA") or ft.endswith("Drazobna_vyhlaska")


def filing_code(file_name: str) -> str:
    return file_name.split("-", 1)[0]


# ---------------------------------------------------------------------------
# Sťahovanie
# ---------------------------------------------------------------------------

def iter_raw(client, since: str, max_pages: int | None = None) -> Iterator[dict]:
    """Prechádza Datahub sync od času `since` (ISO). Vracia všetky položky (aj nedražobné)."""
    url = f"{DATAHUB_SYNC}?since={since}"
    pages = 0
    while url:
        r = client.get(url)
        data = r.json()
        if not data:
            break
        yield from data
        pages += 1
        if max_pages and pages >= max_pages:
            break
        m = re.search(r"<([^>]+)>;\s*rel=.next.", r.headers.get("link", ""))
        url = m.group(1) if m else None


# ---------------------------------------------------------------------------
# Parsovanie
# ---------------------------------------------------------------------------

def parse_item(item: dict) -> dict | None:
    """Datahub položka → notice (alebo None, ak to nie je dražba / nevieme ju prečítať)."""
    fn = item.get("file_name")
    content = item.get("content")
    if not content or not is_auction(fn):
        return None
    ft = form_type(fn)
    try:
        root = ET.fromstring(content.lstrip("﻿").encode("utf-8"))
    except ET.ParseError as e:
        log.warning("OV %s: zlé XML (%s)", item.get("id"), e)
        return None
    _strip_ns(root)
    if root.tag == "AuctionDecree":
        n = parse_executor(root)
    elif root.tag == "Drazba":
        n = parse_voluntary(root, DOBROVOLNA_TYPES.get(ft, "ine"))
    elif root.tag.startswith("DrazbaSpravcaDane"):
        n = parse_tax(root)
    else:
        log.info("OV %s: neznámy koreň %s (%s)", item.get("id"), root.tag, ft)
        return None
    if n is None:
        return None
    bi = item.get("bulletin_issue") or {}
    code = filing_code(fn)
    n.update({
        "source": "ov",
        "source_id": str(item["id"]),
        "source_url": OV_SEARCH_URL,
        "source_label": f"Obchodný vestník {bi.get('number')}/{bi.get('year')}, podanie {code}"
        if bi else f"Obchodný vestník, podanie {code}",
        "filing_code": code,
        "form_type": ft,
        "published_at": (bi.get("published_at") or item.get("created_at") or "")[:10] or None,
    })
    return n


def _strip_ns(root: ET.Element) -> None:
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]


def _t(el: ET.Element | None, path: str) -> str | None:
    if el is None:
        return None
    x = el.find(path)
    if x is None:
        return None
    s = "".join(x.itertext()).strip()
    return s or None


def _cl(el: ET.Element | None, path: str) -> tuple[str | None, str | None]:
    """Hodnota z číselníka: (ItemCode, ItemName)."""
    if el is None:
        return None, None
    x = el.find(path)
    if x is None:
        return None, None
    return _t(x, ".//ItemCode"), _t(x, ".//ItemName")


def _addr(el: ET.Element | None) -> str | None:
    if el is None:
        return None
    street = _t(el, "StreetName")
    num = _t(el, "BuildingNumber")
    psc = _t(el, "DeliveryAddress/PostalCode")
    _, obec = _cl(el, "Municipality")
    obec = obec or _t(el, "Place")
    parts = [" ".join(p for p in [street, num] if p), " ".join(p for p in [psc, obec] if p)]
    s = ", ".join(p for p in parts if p)
    return s or None


# --- exekučná dražobná vyhláška --------------------------------------------

def parse_executor(root: ET.Element) -> dict:
    case = _t(root, "NumberOfExecution")
    executor = _t(root, "ExecutorOffice/PersonData/Name")
    d = T.parse_date(_t(root, "Date"))
    tm = T.parse_time(_t(root, "Time"))
    order = _t(root, "Order")
    _, prop_kind = _cl(root, "TypeOfProperty")
    re_el = root.find("RealEstate")
    props = []
    descr_parts: list[str] = []
    appraised_total = 0.0
    if re_el is not None:
        for item in re_el.findall("Item"):
            p = _executor_item(item)
            props.append(p)
            if p.get("_value"):
                appraised_total += p.pop("_value")
            else:
                p.pop("_value", None)
            if p.get("_text"):
                descr_parts.append(p.pop("_text"))
            else:
                p.pop("_text", None)
    bid = re_el.find("Bid") if re_el is not None else None
    min_bid = T.parse_money(_t(bid, "LowestBid"))
    appraised = T.parse_money(_t(bid, "ValueOfPropertyDeterminedByExpert")) or appraised_total or None
    deposit = T.parse_money(_t(re_el, "Guarantee/AmountOfSecurity"))
    insp = None
    if re_el is not None and re_el.find("Inspection") is not None:
        ins = re_el.find("Inspection")
        idate = T.parse_date(_t(ins, "Date"))
        itime = T.parse_time(_t(ins, "Time"))
        when = (f"{idate.day}. {idate.month}. {idate.year}" if idate else _t(ins, "Date") or "")
        if itime:
            when += f" o {itime}"
        place = _addr(ins.find("Address")) or _t(ins, "Address/Place")
        insp = T.squash(", ".join(x for x in [when.strip(), place] if x)) or None
    free = T.html_to_text(_t(root, "ZverejnujeText"))
    more = T.html_to_text(_t(root, "MoreInformation"))
    note = T.html_to_text(_t(re_el, "Note"))
    raw = "\n".join(x for x in [free, *descr_parts, more, note] if x)
    if free and not props:
        props = [_props_from_text(free)]
    if free:
        d = d or _find_auction_date(free)
        tm = tm or _find_auction_time(free)
        min_bid = min_bid or T.find_money_after(free, "najnižšie podanie", "najnizsie podanie", "vyvolávacia cena")
        appraised = appraised or T.find_money_after(free, "všeobecná hodnota", "znaleck", "cena predmetu")
        deposit = deposit or T.find_money_after(free, "zábezpek", "zabezpek")
    ptype = T.detect_property_type(" ".join([raw] + [p.get("kind_text", "") for p in props]))
    for p in props:
        p.pop("kind_text", None)
        p.setdefault("type", ptype)
    return {
        "kind": "exekucna",
        "notice_type": "opakovana" if (T.parse_round(order) or 1) > 1 else "oznamenie",
        "auction_number": case,
        "case_key": _executor_case_key(executor, case),
        "auctioneer_name": _executor_name(executor),
        "auctioneer_ico": None,
        "proposer": None,
        "auction_at": T.combine(d, tm),
        "venue": _addr(root.find("Place")),
        "round": T.parse_round(order) or 1,
        "round_text": order,
        "min_bid": min_bid,
        "min_increment": None,
        "deposit": deposit,
        "appraised_value": appraised,
        "highest_bid": None,
        "inspection": insp,
        "title": None,
        "description": raw[:20000] or None,
        "property_kind": prop_kind,
        "properties": props,
        "declared_at": (T.parse_date(_t(root, "DeclarationDate")) or None) and str(T.parse_date(_t(root, "DeclarationDate"))),
    }


def _executor_name(s: str | None) -> str | None:
    if not s:
        return None
    s = T.squash(s)
    # 'JUDr. Rus Marko' – v OV je priezvisko pred menom; necháme tak, len doplníme označenie
    return f"Súdny exekútor {s}" if "exek" not in s.lower() else s


def _executor_case_key(executor: str | None, case: str | None) -> str:
    base = (case or "").upper().replace(" ", "")
    m = re.search(r"(\d*EX\d+/\d+)", base)
    if m:
        base = m.group(1)
    else:
        base = re.sub(r"-\d+$", "", base)
    return f"ex|{executor_key(executor)}|{base}"


def executor_key(name: str | None) -> str:
    """'JUDr. Marko Rus' aj 'JUDr. Rus Marko' → 'marko rus' (poradie mena a priezviska v OV kolíše)."""
    words = [w for w in T.norm_key(name).split()
             if w not in {"judr", "mgr", "ing", "phd", "ll", "m", "llm", "bc", "sudny", "exekutor", "exekutorka"}]
    return " ".join(sorted(words))


def _executor_item(item: ET.Element) -> dict:
    rc, rn = _cl(item, "Region")
    cc, cn = _cl(item, "County")
    mc, mn = _cl(item, "Municipality")
    kraj = rn or (NUTS3.get(rc[:5]) if rc else None)
    okres = normalize_okres(cn) or (cn.replace("Okres ", "") if cn else None)
    parcels, kinds, texts = [], [], []
    area = 0.0
    for f in item.findall("Fields"):
        num = _t(f, "PlotNumber")
        if num:
            parcels.append({"register": (_t(f, "PlotType") or "").upper() or None, "number": num,
                            "area_m2": T.parse_money(_t(f, "PlotSize")), "kind": _t(f, "KindOfPlot")})
        kinds.append(_t(f, "KindOfPlot") or "")
        texts.append(_t(f, "DescriptionOfRealestate") or "")
    supisne = []
    for b in item.findall("Buildings"):
        kinds.append(_t(b, "KindOfBuild") or "")
        texts.append(T.html_to_text(_t(b, "DescriptionOfBuilding")) or "")
        sc = _t(b, "PropertyRegistrationNumber")
        if sc:
            supisne.append(sc)
    for fl in list(item.findall("Flats")) + list(item.findall("Flat")) + list(item.findall("NonResidentialPremises")):
        kinds.append("byt " + " ".join(fl.itertext()))
    texts.append(T.html_to_text(_t(item, "MoreInformation")) or "")
    kind_text = " ".join(k for k in kinds if k)
    return {
        "kraj": kraj,
        "okres": okres,
        "obec": mn,
        "obec_code": mc[-6:] if mc and len(mc) >= 6 else mc,
        "ku": _t(item, "CadastralUnit"),
        "lv": re.findall(r"\d+", _t(item, "FolioNumber") or ""),
        "parcels": parcels,
        "supisne_cislo": supisne,
        "area_m2": None,
        "address": None,
        "share": _t(item, "Owner/PartOfCapital"),
        "type": T.detect_property_type(kind_text + " " + " ".join(texts)) if kind_text or any(texts) else None,
        "kind_text": kind_text,
        "_value": T.parse_money(_t(item, "ValueOfPropertyDeterminedByExpert")),
        "_text": T.squash(" ".join(dict.fromkeys(T.squash(t) for t in texts if t and t.strip()))),
    }


# --- dobrovoľná dražba -------------------------------------------------------

def parse_voluntary(root: ET.Element, notice_type: str) -> dict:
    number = _t(root, "Cislo")
    auctioneer = _t(root, "Drazobnik/ObchodneMenoNazov") or _person(root.find("Drazobnik/CeleMeno"))
    ico = _t(root, "Drazobnik/Ico")
    proposers = []
    for nv in root.findall("Navrhovatelia/Navrhovatel"):
        cm = nv.find("CeleMeno")
        name = _t(cm, "ObchodneMenoNazov") or _person(cm)
        if name:
            proposers.append(T.squash(name))
    notary = _person(root.find("Notar/CeleMeno"))
    d = T.parse_date(_t(root, "KonanieDatum"))
    tm = T.parse_time(_t(root, "KonanieCas"))
    predmet_html = _t(root, "Predmet") or ""
    predmet = T.html_to_text(predmet_html)
    opis = T.html_to_text(_t(root, "PredmetOpis"))
    stav = T.html_to_text(_t(root, "PredmetStavOpis"))
    prava = T.html_to_text(_t(root, "PredmetPravaZavazky"))
    cena_txt = T.html_to_text(_t(root, "PredmetCenaSposobStanovenia")) or T.html_to_text(_t(root, "PredmetCenaOdhad"))
    oznamuje = T.html_to_text(_t(root, "DrazobnikOznamuje"))
    dovod = T.html_to_text(_t(root, "DovodUpustenia"))

    min_bid_txt = _t(root, "NajnizsiePodanie")
    min_bid = T.parse_money(min_bid_txt)
    appraised = None
    for src in (T.html_to_text(_t(root, "PredmetCenaOdhad")), cena_txt):
        if src and re.search(r"eur|€", src, re.I):
            appraised = T.parse_money(src)
            if appraised:
                break
    highest = None
    sold = None
    if notice_type == "vysledok":
        vyska = _t(root, "PredmetCenaVyska") or _t(root, "NajvyssiePodanie")
        highest = T.parse_money(vyska) or None
        low = (vyska or "").lower()
        sold = bool(highest) and "nebolo" not in low
        if "nebolo" in low:
            highest = None
        if min_bid is None and min_bid_txt and "nebolo" not in min_bid_txt.lower():
            min_bid = None

    # katastrálne údaje: najprv tabuľky v HTML predmetu, potom voľný text
    cad = _cadastre_from_tables(predmet_html)
    for src in (predmet, opis):
        if not src:
            continue
        found = T.extract_cadastre(src)
        for k, v in found.items():
            if not cad.get(k) or (k in ("okres", "obec", "ku") and not valid_place(cad.get(k))):
                cad[k] = v
    ptype = T.detect_property_type(predmet or opis)
    prop = _prop_from_cad(cad, ptype)
    if T.extract_cadastre(opis).get("area_m2") and not prop.get("area_m2"):
        prop["area_m2"] = T.extract_cadastre(opis)["area_m2"]
    title = _title_from(opis) or _title_from(predmet)
    desc = "\n\n".join(x for x in [predmet, opis, stav, prava, oznamuje, dovod] if x)
    return {
        "kind": "dobrovolna",
        "notice_type": notice_type,
        "auction_number": number,
        "case_key": f"dd|{ico or T.norm_key(auctioneer)}|{T.norm_key(number)}",
        "auctioneer_name": T.squash(auctioneer) if auctioneer else None,
        "auctioneer_ico": _ico(ico),
        "proposer": "; ".join(proposers) or None,
        "notary": notary,
        "auction_at": T.combine(d, tm),
        "venue": T.squash(T.html_to_text(_t(root, "KonanieMiesto"))) or None,
        "round": _vol_round(_t(root, "Kolo"), notice_type),
        "round_text": _t(root, "Kolo"),
        "min_bid": min_bid,
        "min_increment": T.parse_money(_t(root, "MinimalnePrihodenie")),
        "deposit": T.parse_money(_t(root, "Zabezpeka/Vyska")),
        "appraised_value": appraised,
        "highest_bid": highest,
        "sold": sold,
        "inspection": T.squash(T.html_to_text(_t(root, "ObhliadkaDatum"))) or None,
        "title": title,
        "description": desc[:20000] or None,
        "reason": dovod or oznamuje or None,
        "properties": [prop] if prop else [],
        "previous_date": _t(root, "ZoDna"),
    }


def _vol_round(kolo: str | None, notice_type: str) -> int:
    r = T.parse_round(kolo)
    if notice_type == "opakovana" and (r or 1) < 2:
        return 2
    return r or 1


def _ico(s: str | None) -> str | None:
    if not s:
        return None
    s = re.sub(r"\s", "", s)
    return s if re.fullmatch(r"\d{6,8}", s) else None


def _person(el: ET.Element | None) -> str | None:
    if el is None:
        return None
    parts = [_t(el, "TitulPred"), _t(el, "Meno"), _t(el, "Priezvisko")]
    tz = _t(el, "TitulZa")
    s = " ".join(p for p in parts if p)
    if tz:
        s += f", {tz}"
    return s or None


_TABLE_LABELS = {
    "lv": re.compile(r"^(?:(?:číslo\s+)?lv\b|(?:číslo\s+)?list(?:u)?\s+vlastn)", re.I),
    "okres": re.compile(r"^okres\b", re.I),
    "obec": re.compile(r"^obec\b", re.I),
    "ku": re.compile(r"^(?:katastr[áa]lne\s+[úu]zemie|k\.\s*[úu])", re.I),
    # „Okresný úrad, katastrálny odbor“, „Správa katastra“, „Vedené Okresným úradom…“ → okres úradu
    "okres_urad": re.compile(r"^(?:vedené\s+)?(?:okresn\w*\s+úrad|katastr[áa]ln\w*\s+odbor|správa\s+katastra)", re.I),
}
# ostatné popisy v tabuľkách – nie sú to hodnoty
_OTHER_LABEL = re.compile(
    r"^(?:súpisné|súp\.|na pozemku|druh|popis|vo vlastníctve|spoluvlastnícky|parc|číslo|výmera|stavba|pozemky|"
    r"základná|predmet|poznámk|charakteristik|postavená)", re.I)


def _lines(node) -> list[str]:
    out = []
    for x in node.text(separator="\n").split("\n"):
        x = T.squash(x)
        if not x:
            continue
        # „Okres : Obec : Katastrálne územie :“ v jednom riadku → tri popisy
        parts = [p.strip() + ":" for p in re.split(r":\s*", x) if p.strip()] if x.count(":") >= 2 and x.endswith(":") else [x]
        out += parts
    # „Číslo“ + „LV“ pod sebou = jeden popis
    merged: list[str] = []
    for x in out:
        if merged and re.fullmatch(r"(?i)číslo", merged[-1].rstrip(": ")) and re.match(r"(?i)lv\b|listu", x):
            merged[-1] = f"{merged[-1]} {x}"
        else:
            merged.append(x)
    return merged


def _is_label(line: str) -> bool:
    c = line.strip()
    # „Okresný úrad Prievidza, katastrálny odbor“ je hodnota (obsahuje názov miesta), nie popis
    caps = re.findall(r"\s([A-ZÁČĎÉÍĽĹŇÓÔŔŠŤÚÝŽ][a-záäčďéíľĺňóôŕšťúýž]+)", c)
    if not c.endswith(":") and any(not re.match(r"(?i)okresn|katastr|úrad|správ|veden|odbor", w) for w in caps):
        return False
    return bool(_label_key(c)) or (len(c) < 45 and (c.endswith(":") or bool(_OTHER_LABEL.match(c))))


def valid_place(v: str | None) -> bool:
    """Hodnota obce/k. ú./okresu nesmie byť ďalší popis ani kus vety."""
    if not v:
        return False
    v = v.strip()
    if len(v) > 45 or ":" in v or re.search(r"\d{3,}", v):
        return False
    if re.search(r"úrad|odbor|katastr|územie|vlastn|súpis|predmet|parcel|dražb", v, re.I):
        return False
    return True


def _clean_value(k: str, v: str) -> str | list | None:
    v = v.strip().strip(":").strip()
    if k == "lv":
        nums = re.findall(r"\d{1,6}", v)
        return nums[:1] or None
    if k == "okres_urad":
        m = re.search(r"(?:okresn\w*\s+úrad\w*|správa\s+katastra)\s+([A-ZÁ-Ž][^,]{1,40})", v)
        v = m.group(1) if m else v
        v = re.sub(r"\s*[-–,]\s*katastr.*$", "", v).strip()
        return v if valid_place(v) else None
    v = re.sub(r"\s+", " ", v)
    return v if valid_place(v) else None


def _innermost_tables(tree) -> list:
    return [t for t in tree.css("table") if not t.css("table table") and len(t.css("table")) <= 1]


def _cadastre_from_tables(predmet_html: str) -> dict:
    """Katastrálne údaje z HTML tabuliek v predmete dražby.

    Podporuje (všetko videné v reálnych oznámeniach):
    - hlavička + riadok hodnôt: `Číslo LV | Katastrálne územie | Okresný úrad…` / `7278 | Komárno | Komárno`
    - popis | hodnota v jednom riadku: `Číslo listu vlastníctva: | 1295`
    - viac popisov pod sebou v jednej bunke a hodnoty pod sebou v susednej:
      `Okres: Obec: Katastrálne územie:` | `Sobrance Lekárovce Lekárovce`
    """
    low = (predmet_html or "").lower()
    if "<table" not in low and "&lt;table" not in low:
        return {}
    h = predmet_html
    for _ in range(2):
        h = htmlmod.unescape(h)
    tree = LexborHTMLParser(h)
    out: dict = {}
    parcels = []

    def put(k, v):
        if k and v is not None and not out.get(k):
            cv = _clean_value(k, v)
            if cv:
                out[k] = cv

    for table in _innermost_tables(tree):
        rows = [[_lines(td) for td in tr.css("td,th")] for tr in table.css("tr")]
        rows = [r for r in rows if r and len(r) <= 12]
        for i, row in enumerate(rows):
            flat = [ln for cell in row for ln in cell]
            label_keys = [_label_key(ln) if _is_label(ln) else None for ln in flat]
            all_labels = flat and all(_is_label(ln) for ln in flat)
            # 1) celý riadok sú popisy → hodnoty sú v nasledujúcom riadku (riadkoch)
            if all_labels and sum(1 for k in label_keys if k) >= 1 and i + 1 < len(rows):
                vals = []
                for r2 in rows[i + 1:]:
                    f2 = [ln for cell in r2 for ln in cell]
                    if any(_is_label(ln) for ln in f2):
                        break
                    vals += f2
                    if len(vals) >= len(flat):
                        break
                if len(vals) == len(flat):
                    for k, v in zip(label_keys, vals):
                        put(k, v)
                elif len(row) == len(rows[i + 1]):  # aspoň po bunkách (prvý riadok bunky)
                    for cell, vcell in zip(row, rows[i + 1]):
                        if vcell:
                            put(_label_key(" ".join(cell)), vcell[0])
                continue
            # 2) popisná bunka a vedľa hodnotová bunka (aj viac riadkov pod sebou)
            for j in range(len(row) - 1):
                lab, val = row[j], row[j + 1]
                if lab and all(_is_label(x) for x in lab) and val and not any(_is_label(x) for x in val):
                    if len(lab) == len(val):
                        for a, b in zip(lab, val):
                            put(_label_key(a), b)
                    elif len(lab) == 1:
                        put(_label_key(lab[0]), " ".join(val))
            # 3) parcely: 'Parcelné číslo | Druh pozemku | Výmera'
            first = row[0][0] if row and row[0] else ""
            if re.search(r"parc(?:eln[ée]|el)?\.?\s+č", first, re.I) and i + 1 < len(rows):
                for r2 in rows[i + 1:]:
                    cells = [" ".join(c) for c in r2]
                    num_idx = next((x for x, c in enumerate(cells[:2]) if re.fullmatch(r"\d+\s*(?:/\s*\d+)?", c)), None)
                    if num_idx is None:
                        break
                    rest = cells[num_idx + 1:]
                    parcels.append({"register": None, "number": re.sub(r"\s", "", cells[num_idx]),
                                    "kind": rest[0] if rest else None,
                                    "area_m2": T.parse_money(re.sub(r"m\s*2.*", "", rest[1])) if len(rest) > 1 else None})
    if parcels:
        out["parcels"] = parcels
    if out.get("okres"):
        out["okres"] = normalize_okres(out["okres"]) or out["okres"]
    return out


def _label_key(cell: str) -> str | None:
    c = cell.strip().rstrip(":").strip()
    if len(c) > 45:
        return None
    for k, rx in _TABLE_LABELS.items():
        if rx.search(c):
            return k
    return None


def _prop_from_cad(cad: dict, ptype: str) -> dict:
    if not cad and ptype == "ine":
        return {}
    okres = (normalize_okres(cad.get("okres")) or normalize_okres(cad.get("okres_urad"))
             or (cad.get("okres") if valid_place(cad.get("okres")) else None))
    ku = cad.get("ku") if valid_place(cad.get("ku")) else None
    # k. ú. sa väčšinou volá rovnako ako obec; keď obec chýba, je to najlepší odhad
    obec = cad.get("obec") if valid_place(cad.get("obec")) else None
    obec = obec or ku
    kraj = (kraj_for_okres(okres) or kraj_for_obec(cad.get("okres")) or kraj_for_obec(cad.get("okres_urad"))
            or kraj_for_obec(obec) or kraj_for_obec(ku))
    return {
        "type": ptype,
        "kraj": kraj,
        "okres": okres,
        "obec": obec,
        "ku": ku,
        "lv": cad.get("lv") or [],
        "parcels": cad.get("parcels") or [],
        "supisne_cislo": cad.get("supisne_cislo") or [],
        "area_m2": cad.get("area_m2"),
        "address": None,
    }


def _props_from_text(text: str) -> dict:
    cad = T.extract_cadastre(text)
    return _prop_from_cad(cad, T.detect_property_type(text))


def _title_from(text: str | None) -> str | None:
    if not text:
        return None
    first = text.strip().split("\n")[0]
    first = re.sub(r"^(predmetom dražby (?:je|sú)|predmet dražby:?)\s*", "", first, flags=re.I)
    return (first[:157] + "…") if len(first) > 160 else first or None


def _find_auction_date(text: str):
    m = re.search(r"(?:dátum|deň|dňa)\s+(?:konania\s+)?dražby\s*[:\-]?\s*([^\n]{0,40})", text, re.I)
    if m:
        d = T.parse_date(m.group(1))
        if d:
            return d
    m = re.search(r"dražba\s+sa\s+(?:uskutoční|bude\s+konať|koná)\s+(?:dňa\s+)?([^\n]{0,40})", text, re.I)
    return T.parse_date(m.group(1)) if m else None


def _find_auction_time(text: str):
    m = re.search(r"(?:čas\s+(?:konania\s+)?dražby|o)\s*[:\-]?\s*(\d{1,2}[:.]\d{2})\s*hod", text, re.I)
    return T.parse_time(m.group(1)) if m else None


# --- daňová dražba -----------------------------------------------------------

def parse_tax(root: ET.Element) -> dict | None:
    office = " ".join(x for x in [_t(root, "Typ"), _t(root, "Nazov")] if x)
    text = T.html_to_text(_t(root, "ZverejnujeText"))
    if not text:
        return None
    low = text.lower()
    if "dražob" not in low and "drazob" not in low and "dražb" not in low:
        return None
    d = _find_auction_date(text)
    tm = _find_auction_time(text)
    m = re.search(r"Číslo\s+daňového\s+exekučného\s+konania\s*:\s*(\d+)", text, re.I)
    case = m.group(1) if m else None
    venue = None
    mv = re.search(r"Miesto\s+konania\s+dražby\s*:\s*([^\n]+?)(?:\.\s+[A-ZČŠŽ]|\n|$)", text)
    if mv:
        venue = T.squash(mv.group(1))
    min_bid = T.find_money_after(text, "vyvolávacia cena", "najnižšie podanie")
    deposit = T.find_money_after(text, "zábezpeku", "zábezpeka")
    prop = _props_from_text(text)
    nehn = re.search(r"Predmetom\s+dražby\s+je\s*:?\s*(.{0,600})", text, re.I | re.S)
    return {
        "kind": "danova",
        "notice_type": "opakovana" if "opakovan" in low else "oznamenie",
        "auction_number": case,
        "case_key": f"du|{T.norm_key(office)}|{case or T.norm_key(text[:120])}",
        "auctioneer_name": T.squash(office) or None,
        "auctioneer_ico": None,
        "proposer": None,
        "auction_at": T.combine(d, tm),
        "venue": venue,
        "round": 2 if "opakovan" in low else 1,
        "min_bid": min_bid,
        "min_increment": T.find_money_after(text, "minimálne prihodenie", "prihodenie"),
        "deposit": deposit,
        "appraised_value": T.find_money_after(text, "všeobecná hodnota", "hodnota nehnuteľnosti", "ohodnoten"),
        "highest_bid": None,
        "inspection": None,
        "title": T.squash(nehn.group(1))[:160] if nehn else None,
        "description": text[:20000],
        "properties": [prop] if prop else [],
    }


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
