"""Okresy a kraje Slovenska (79 okresov, 8 krajov)."""

from __future__ import annotations

from .text import strip_accents

KRAJE: dict[str, list[str]] = {
    "Bratislavský kraj": [
        "Bratislava I", "Bratislava II", "Bratislava III", "Bratislava IV", "Bratislava V",
        "Malacky", "Pezinok", "Senec",
    ],
    "Trnavský kraj": [
        "Dunajská Streda", "Galanta", "Hlohovec", "Piešťany", "Senica", "Skalica", "Trnava",
    ],
    "Trenčiansky kraj": [
        "Bánovce nad Bebravou", "Ilava", "Myjava", "Nové Mesto nad Váhom", "Partizánske",
        "Považská Bystrica", "Prievidza", "Púchov", "Trenčín",
    ],
    "Nitriansky kraj": [
        "Komárno", "Levice", "Nitra", "Nové Zámky", "Šaľa", "Topoľčany", "Zlaté Moravce",
    ],
    "Žilinský kraj": [
        "Bytča", "Čadca", "Dolný Kubín", "Kysucké Nové Mesto", "Liptovský Mikuláš", "Martin",
        "Námestovo", "Ružomberok", "Turčianske Teplice", "Tvrdošín", "Žilina",
    ],
    "Banskobystrický kraj": [
        "Banská Bystrica", "Banská Štiavnica", "Brezno", "Detva", "Krupina", "Lučenec", "Poltár",
        "Revúca", "Rimavská Sobota", "Veľký Krtíš", "Zvolen", "Žarnovica", "Žiar nad Hronom",
    ],
    "Prešovský kraj": [
        "Bardejov", "Humenné", "Kežmarok", "Levoča", "Medzilaborce", "Poprad", "Prešov", "Sabinov",
        "Snina", "Stará Ľubovňa", "Stropkov", "Svidník", "Vranov nad Topľou",
    ],
    "Košický kraj": [
        "Gelnica", "Košice I", "Košice II", "Košice III", "Košice IV", "Košice - okolie",
        "Michalovce", "Rožňava", "Sobrance", "Spišská Nová Ves", "Trebišov",
    ],
}

# kódy NUTS3 (prvých 5 znakov kódu obce v OV, napr. SK032B518158 → SK032)
NUTS3 = {
    "SK010": "Bratislavský kraj", "SK021": "Trnavský kraj", "SK022": "Trenčiansky kraj",
    "SK023": "Nitriansky kraj", "SK031": "Žilinský kraj", "SK032": "Banskobystrický kraj",
    "SK041": "Prešovský kraj", "SK042": "Košický kraj",
}


def _k(s: str) -> str:
    s = strip_accents(s.lower()).replace("-", " ")
    s = s.replace("okres ", "").replace("okolie", " okolie")
    return " ".join(s.split())


_OKRES_KEY = {_k(o): o for os_ in KRAJE.values() for o in os_}
_OKRES_KRAJ = {o: k for k, os_ in KRAJE.items() for o in os_}


def normalize_okres(name: str | None) -> str | None:
    """'Okres Zvolen' → 'Zvolen', 'Kosice-okolie' → 'Košice - okolie', 'Bratislava' → None (nejednoznačné)."""
    if not name:
        return None
    key = _k(name)
    if key in _OKRES_KEY:
        return _OKRES_KEY[key]
    # 'Bratislava 2' / 'Bratislava II'
    roman = {"1": "i", "2": "ii", "3": "iii", "4": "iv", "5": "v"}
    parts = key.split()
    if len(parts) == 2 and parts[1] in roman:
        k2 = f"{parts[0]} {roman[parts[1]]}"
        if k2 in _OKRES_KEY:
            return _OKRES_KEY[k2]
    return None


def kraj_for_okres(okres: str | None) -> str | None:
    o = normalize_okres(okres) if okres else None
    return _OKRES_KRAJ.get(o) if o else None


def kraj_for_obec(obec: str | None) -> str | None:
    """Pre krajské/okresné mestá, kde sa obec zhoduje s okresom."""
    if not obec:
        return None
    if _k(obec).startswith("bratislava"):
        return "Bratislavský kraj"
    if _k(obec).startswith("kosice") and "okolie" not in _k(obec):
        return "Košický kraj"
    return kraj_for_okres(obec)


ALL_OKRESY = list(_OKRES_KRAJ)
