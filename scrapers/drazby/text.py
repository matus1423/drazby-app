"""Pomocné funkcie na vyťahovanie údajov z voľného slovenského textu oznámení."""

from __future__ import annotations

import html
import re
import unicodedata
from datetime import date, datetime

# ---------------------------------------------------------------------------
# HTML → text
# ---------------------------------------------------------------------------

_BLOCK_TAGS = re.compile(r"</?(p|div|li|ul|ol|br|tr|h\d|table)\b[^>]*>", re.I)
_TAGS = re.compile(r"<[^>]+>")


def html_to_text(s: str | None) -> str:
    """Odstráni HTML (aj dvojito escapované, ako ho posiela OV) a znormalizuje medzery."""
    if not s:
        return ""
    # OV posiela HTML escapované v XML a vnútri ešte raz entity (&amp;aacute;)
    for _ in range(3):
        un = html.unescape(s)
        if un == s:
            break
        s = un
    s = unicodedata.normalize("NFC", s)  # niektoré podania majú „á“ ako „a“ + U+0301
    s = _BLOCK_TAGS.sub("\n", s)
    s = _TAGS.sub(" ", s)
    s = html.unescape(s)
    s = s.replace("\xa0", " ").replace("​", "")
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    s = re.sub(r" *\n *", "\n", s)
    s = re.sub(r"\n{2,}", "\n", s)
    return s.strip()


def squash(s: str | None) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def norm_key(s: str | None) -> str:
    """Kľúč na porovnávanie mien: bez diakritiky, malé písmená, bez právnej formy a interpunkcie."""
    s = strip_accents((s or "").lower())
    s = re.sub(r"\b(s\s*\.?\s*r\s*\.?\s*o|a\s*\.?\s*s|k\s*\.?\s*s|v\s*\.?\s*o\s*\.?\s*s|spol)\b\.?", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return s.strip()


# ---------------------------------------------------------------------------
# Peniaze
# ---------------------------------------------------------------------------

_NUM = re.compile(
    r"(?<![\d/])(\d{1,3}(?:[ . ]\d{3})+|\d+)(?:[,.](\d{1,2})(?!\d)|,-+|,–)?"
)


def parse_money(s: str | None) -> float | None:
    """'78.200,- EUR (slovom …)' → 78200.0, '3.310,00 EUR' → 3310.0, '27090.23' → 27090.23."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    s = s.replace("\xa0", " ").strip()
    if not s:
        return None
    if re.fullmatch(r"\d+(\.\d+)?", s):  # číslo z XML
        return float(s)
    # preferuj číslo bezprostredne pred EUR/€
    m = re.search(r"(\d[\d . ]*(?:[,.]\d{1,2}|,-+)?)\s*[-–]?\s*(?:eur|€|euro)", s, re.I)
    cand = m.group(1) if m else s
    m2 = _NUM.search(cand)
    if not m2:
        return None
    whole = re.sub(r"[ . ]", "", m2.group(1))
    dec = m2.group(2) or "0"
    try:
        v = float(f"{int(whole)}.{dec}")
    except ValueError:
        return None
    return v


def find_money_after(text: str, *labels: str, window: int = 160) -> float | None:
    """Nájde sumu v okolí niektorého z návestí, napr. 'najnižšie podanie'."""
    low = text.lower()
    for lab in labels:
        for m in re.finditer(re.escape(lab.lower()), low):
            chunk = text[m.end(): m.end() + window]
            m2 = re.search(r"\d[\d . ]*(?:[,.]\d{1,2}|,-+)?\s*[-–]?\s*(?:eur|€|euro)", chunk, re.I)
            if m2:
                v = parse_money(m2.group(0))
                if v:
                    return v
    return None


# ---------------------------------------------------------------------------
# Dátumy a časy
# ---------------------------------------------------------------------------

MONTHS = {
    "januar": 1, "februar": 2, "marec": 3, "marca": 3, "april": 4, "aprila": 4, "maj": 5, "maja": 5,
    "jun": 6, "juna": 6, "jul": 7, "jula": 7, "august": 8, "augusta": 8, "september": 9,
    "septembra": 9, "oktober": 10, "oktobra": 10, "november": 11, "novembra": 11,
    "december": 12, "decembra": 12, "januara": 1, "februara": 2,
}


def parse_date(s: str | None) -> date | None:
    if not s:
        return None
    s = s.strip()
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"(\d{1,2})\s*\.\s*(\d{1,2})\s*\.\s*(\d{4})", s)
    if m:
        return _mk(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    m = re.search(r"(\d{1,2})\.\s*([a-záäčďéíĺľňóôŕšťúýž]+)\s+(\d{4})", s, re.I)
    if m:
        mon = MONTHS.get(strip_accents(m.group(2).lower()))
        if mon:
            return _mk(int(m.group(3)), mon, int(m.group(1)))
    return None


def _mk(y: int, mo: int, d: int) -> date | None:
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def parse_time(s: str | None) -> str | None:
    if not s:
        return None
    m = re.search(r"(\d{1,2})\s*[:.,]\s*(\d{2})", s)
    if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    m = re.search(r"(\d{1,2})\s*hod", s)
    if m and int(m.group(1)) < 24:
        return f"{int(m.group(1)):02d}:00"
    return None


def combine(d: date | None, t: str | None) -> str | None:
    if not d:
        return None
    if t:
        return f"{d.isoformat()}T{t}:00"
    return d.isoformat()


def parse_datetime_sk(s: str | None) -> str | None:
    """'13.11.2026 09:30:00' → '2026-11-13T09:30:00'."""
    d = parse_date(s)
    if not d:
        return None
    m = re.search(r"(\d{1,2}):(\d{2})", s or "")
    return combine(d, f"{int(m.group(1)):02d}:{m.group(2)}" if m else None)


# ---------------------------------------------------------------------------
# Kolo dražby
# ---------------------------------------------------------------------------

_ROUND_WORDS = {
    "prv": 1, "1.": 1, "druh": 2, "2.": 2, "opakovan": 2, "tret": 3, "3.": 3,
    "štvrt": 4, "stvrt": 4, "4.": 4, "piat": 5, "5.": 5,
}


def parse_round(s: str | None) -> int | None:
    if not s:
        return None
    low = s.lower().strip()
    base = None
    m = re.match(r"(\d+)", low)
    if m:
        base = int(m.group(1))
    else:
        for k, v in _ROUND_WORDS.items():
            if k != "opakovan" and (low.startswith(k) or f" {k}" in f" {low}"):
                base = v
                break
    if "opakov" in low:
        # 'prvá opakovaná dražba' = 2. kolo, 'opakovaná' bez poradia = 2. kolo
        return (base or 1) + 1
    return base


# ---------------------------------------------------------------------------
# Kataster: okres, obec, k. ú., LV, parcely, súpisné číslo
# ---------------------------------------------------------------------------

_NAME = r"([A-ZÁÄČĎÉÍĹĽŇÓÔŔŠŤÚÝŽ][\wáäčďéíĺľňóôŕšťúýžÁÄČĎÉÍĹĽŇÓÔŔŠŤÚÝŽ.\- ]{1,60}?)"
_END = (r"(?=\s*(?:[,;:\n(|]|(?<=[^\W\d_]{3})\.(?:\s|$)|\s(?:na|v|a|ako|zapísan\w*|vedenom|obec|obci|okres\w*|kat|"
        r"k\.\s*ú|katastr[áa]ln\w*|list|LV|č\.|parc\w*|súpis\w*|pre)\b|$))")


def _first(pattern: str, text: str, flags=re.I) -> str | None:
    m = re.search(pattern, text, flags)
    return squash(m.group(1)).strip(" ,.;:") if m else None


def extract_cadastre(text: str) -> dict:
    """Vytiahne katastrálne údaje z voľného textu. Vracia len nájdené kľúče."""
    # zalomenia riadkov a bunky tabuliek sú hranice hodnôt
    t = squash(re.sub(r"\s*[\n|]\s*", " ; ", text or ""))
    out: dict = {}
    okres = _first(r"\bokres(?:u|e)?\b\s*[:\-]?\s*" + _NAME + _END, t)
    if okres and not re.match(r"(?i)(?:úrad|urad|súd|sud)", okres):
        out["okres"] = _clean_place(okres)
    else:
        # katastrálny odbor sídli na okresnom úrade → zvyčajne to je aj okres nehnuteľnosti
        from .regions import normalize_okres
        for pat in (r"\bokresn(?:ý|ého|ým|om)\s+úrad(?:u|om|e)?\s*[:\-]?\s*" + _NAME + _END,
                    r"\bkatastr[áa]ln\w*\s+odbor\w*\s*:\s*" + _NAME + _END,
                    r"\bokresn(?:ý|ého|ým|om)\s+úrad\w*\s+" + _NAME + r"\s*[-–]\s*katastr"):
            for m in re.finditer(pat, t, re.I):
                cand = _clean_place(squash(m.group(1)).strip(" ,.;:"))
                if normalize_okres(cand) or cand.lower().startswith(("bratislava", "košice")):
                    out["okres_urad"] = cand
                    break
            if "okres_urad" in out:
                break
    obec = _first(r"(?<![\w])ob(?:ec|ci)\b\s*[:\-]?\s*" + _NAME + _END, t)
    if obec:
        out["obec"] = _clean_place(obec)
    ku = _first(
        r"(?:katastr[áa]ln(?:e|om|eho)\s+[úu]zem(?:ie|í|ia)|katastr\.\s*[úu]zemie|kat\.\s*[úu]z(?:emie)?\.?|k\.\s*[úu]\.?)"
        r"\s*[:\-]?\s*" + _NAME + _END, t)
    if ku:
        out["ku"] = _clean_place(ku)
    lvs = re.findall(
        r"(?:list(?:e|u|om)?\s+vlastn[íi]ctva|LV)\s*(?:č\.|číslo|c\.|čísl\.)?\s*[:\-]?\s*(\d{1,6})", t, re.I)
    if lvs:
        out["lv"] = list(dict.fromkeys(lvs))
    parcels = []
    for m in re.finditer(
            r"(?:parcel[ay]?|parc\.|(?<![\wú])p\.\s*č\.)\s*(?:registra\s*[„\"“']?\s*([CE])\s*[\"“”']?\s*(?:KN)?\s*)?"
            r"(?:parc\.\s*)?(?:č\.|číslo|čísl\.|c\.)?\s*[:\-]?\s*(\d{1,6}(?:/\d{1,4})?)", t, re.I):
        reg = (m.group(1) or "").upper() or None
        parcels.append({"register": reg, "number": m.group(2)})
    if parcels:
        seen = set()
        out["parcels"] = [p for p in parcels if not (p["number"] in seen or seen.add(p["number"]))]
    sc = re.findall(r"(?:s[úu]pisn(?:é|ým|ého|e|ym|eho|om)|s[úu]p\.)\s*(?:č\.|číslom|číslo|c\.)\s*(\d{1,6})", t, re.I)
    if sc:
        out["supisne_cislo"] = list(dict.fromkeys(sc))
    m = re.search(r"podlahov\w+\s+ploch\w*.{0,60}?(\d{1,4}(?:[,.]\d{1,2})?)\s*m(?:2|²|\s*2)", t, re.I)
    if m:
        out["area_m2"] = float(m.group(1).replace(",", "."))
    return out


def _clean_place(s: str) -> str:
    s = re.sub(r"\s+(?:a|na|v|pre|so|s)$", "", s.strip())
    return s.strip(" ,.;:")


# ---------------------------------------------------------------------------
# Typ nehnuteľnosti
# ---------------------------------------------------------------------------

PROPERTY_TYPES = {
    "byt": "Byt",
    "dom": "Rodinný dom",
    "rekreacny": "Chata / rekreačný objekt",
    "pozemok": "Pozemok",
    "nebytovy": "Nebytový priestor / budova",
    "garaz": "Garáž",
    "ine": "Iné",
}


def detect_property_type(text: str) -> str:
    t = strip_accents((text or "").lower())
    if re.search(r"\bbyt(u|ov|y)?\s*(c\.|cislo|č)|bytov(a|u|ej)\s+jednotk|\bbyt\s+v\s+bytovom|\d-izbov", t):
        return "byt"
    if re.search(r"\bbyt(u)?\b", t) and "bytov" in t and "rodinn" not in t:
        return "byt"
    if re.search(r"rodinn(y|eho|om)\s+dom|rodinny\s+dom|\brd\b|dom\s+so?\s+supisn", t):
        return "dom"
    if re.search(r"rekreac|chat[ay]\b|chalup|zahradn(a|u)\s+chat", t):
        return "rekreacny"
    if re.search(r"nebytov|administrativ|obchodn|vyrobn|sklad|hal[ay]\b|polyfunkc|hotel|penzion|prevadzk", t):
        return "nebytovy"
    if re.search(r"\bgaraz", t):
        return "garaz"
    if re.search(r"\bstavb|budov", t):
        return "dom" if re.search(r"byvan|obytn", t) else "nebytovy"
    if re.search(r"pozem|parcel|orna poda|travny porast|zahrad|lesn|vinic|ovocn|zastavan", t):
        return "pozemok"
    return "ine"


# ---------------------------------------------------------------------------
# Osobné údaje
# ---------------------------------------------------------------------------

_DOB = re.compile(
    r"\(?\s*(?:nar\.|narodený|narodená|narodenie|dátum narodenia|dát\.\s*nar\.)\s*:?\s*"
    r"\d{1,2}\s*\.\s*\d{1,2}\s*\.\s*\d{4}\s*\)?", re.I)
_RC = re.compile(r"(?:r\.\s*č\.|rodné\s+číslo)\s*:?\s*\d{6}\s*/?\s*\d{3,4}", re.I)
_UP = "A-ZÁÄČĎÉÍĹĽŇÓÔŔŠŤÚÝŽ"
_LO = "a-záäčďéíĺľňóôŕšťúýž"
# „Ing. Peter Jančiar r. Jančiar (nar. …“, „Rudolf Pajdič, rod. Pajdič, nar. …“
_NAME_BEFORE = re.compile(
    rf"(?:(?:[{_UP}][{_LO}]{{0,5}}\.\s*)+)?[{_UP}][{_LO}]+(?:\s+[{_UP}][{_LO}]+){{1,2}}"
    rf"(?=\s*,?\s*(?:(?:r|rod)\.\s*[{_UP}][{_LO}]+\s*,?\s*)?"
    rf"(?:\[skryté\]\s*,?\s*|[{_UP}][{_LO}]+(?:\s+[{_UP}][{_LO}]+){{0,2}}\s*,?\s*)?"  # „, Banská Bystrica“
    rf"[^\S\n]*(?:\(\s*)?(?:nar\.|narodený|narodená))")
_ROD = re.compile(rf"\b(?:r|rod)\.\s*[{_UP}][{_LO}]+(?=\s*,?\s*\(?\s*nar)")
REDACTED = "[skryté]"
# „vo vlastníctve: Eva Nová r. Nová“, „povinný: Ján Novák“, „správca dlžníka: Michal X“
_NAME_AFTER = re.compile(
    rf"((?:vo\s+vlastníctve|vlastník\w*|povinn\w+|dlžník\w*|úpadc\w+)\s*:?\s*(?:\d+\.\s*)?)"
    rf"(?:(?:[{_UP}][{_LO}]{{0,5}}\.\s*)+)?[{_UP}][{_LO}]+(?:\s+[{_UP}][{_LO}]+){{1,2}}"
    rf"(?:\s*,?\s*(?:r|rod)\.\s*[{_UP}][{_LO}]+)?(?=\s*[,;(\n]|\s+(?:bytom|trvale|nar))", re.I)
_ADDR = re.compile(r"\b((?:trvale\s+)?bytom)\s+[^,;\n().]{1,60}(?:,\s*[^,;\n().\d]{2,30}(?=,\s*(?:PSČ\s*)?\d))?"
                   r"(?:,\s*(?:PSČ\s*)?\d{3}\s?\d{2}(?:\s+[^,;\n().\d]{1,30})?)?", re.I)


def redact_personal(s: str | None) -> str | None:
    """Skryje dátumy narodenia, rodné čísla a meno osoby uvedené pri nich.

    Mená firiem, dražobníkov a exekútorov ostávajú (nie sú pri nich dátumy narodenia).
    """
    if not s:
        return s
    s = unicodedata.normalize("NFC", s)
    s = _NAME_AFTER.sub(lambda m: m.group(1) + REDACTED, s)
    s = _NAME_BEFORE.sub(REDACTED, s)
    s = _ADDR.sub(lambda m: f"{m.group(1)} {REDACTED}", s)
    s = _ROD.sub("", s)
    s = _DOB.sub(f"(nar. {REDACTED})", s)
    s = _RC.sub(f"r. č. {REDACTED}", s)
    return s
