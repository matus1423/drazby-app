from datetime import date

import pytest

from drazby import text as T
from drazby.regions import kraj_for_okres, normalize_okres


@pytest.mark.parametrize("s,expected", [
    ("78.200,- EUR (slovom: sedemdesiatosemtisícdvesto EURO)", 78200.0),
    ("3.310,00 EUR (slovom tritisíctristodesať eur)", 3310.0),
    ("27090.23", 27090.23),
    ("19.257,30", 19257.30),
    ("500 €", 500.0),
    ("2.000 €", 2000.0),
    ("61 300,00 EUR", 61300.0),
    ("Všeobecná cena odhadu 19.900-eur.", 19900.0),
    ("posudok č.72/2026 ... cena 19.900-eur", 19900.0),
    ("1 575 000,00 €", 1575000.0),
    ("965.000,- €.", 965000.0),
    (None, None),
    ("", None),
    ("bolo urobené", None),
])
def test_parse_money(s, expected):
    assert T.parse_money(s) == expected


@pytest.mark.parametrize("s,expected", [
    ("2026-10-27", date(2026, 10, 27)),
    ("13.11.2026 09:30:00", date(2026, 11, 13)),
    ("13. 11. 2026", date(2026, 11, 13)),
    ("13. októbra 2026", date(2026, 10, 13)),
    ("bez dátumu", None),
    ("31.02.2026", None),
])
def test_parse_date(s, expected):
    assert T.parse_date(s) == expected


@pytest.mark.parametrize("s,expected", [
    ("09:00 hod.", "09:00"), ("10,00 hod.", "10:00"), ("13.15 hod.", "13:15"), ("10 hod", "10:00"), ("11:00", "11:00"),
])
def test_parse_time(s, expected):
    assert T.parse_time(s) == expected


@pytest.mark.parametrize("s,expected", [
    ("prvé", 1), ("Druhé kolo dražby", 2), ("2. kolo", 2), ("1. kolo dražby", 1),
    ("opakovaná", 2), ("prvá opakov. dražba", 2), ("druhá opakovaná dražba", 3), ("tretie", 3), (None, None),
])
def test_parse_round(s, expected):
    assert T.parse_round(s) == expected


def test_html_to_text_double_escaped():
    s = "&lt;p&gt;Nehnuteľnosti, v&amp;nbsp;podiele 1/1, zap&amp;iacute;san&amp;eacute;&lt;/p&gt;"
    assert T.html_to_text(s) == "Nehnuteľnosti, v podiele 1/1, zapísané"


def test_extract_cadastre_free_text():
    t = ("Nehnuteľnosti zapísané v evidencii Okresného úradu Nové Zámky, katastrálny odbor, na liste "
         "vlastníctva č. 13558, okres: Nové Zámky, obec: Nové Zámky, katastrálne územie: Nové Zámky, a to: "
         "byt č. 4 v bytovom dome so súpisným číslom 4578, na pozemku parcely registra „C“ č. 9238 o výmere 176 m²")
    c = T.extract_cadastre(t)
    assert c["okres"] == "Nové Zámky"
    assert c["obec"] == "Nové Zámky"
    assert c["ku"] == "Nové Zámky"
    assert c["lv"] == ["13558"]
    assert c["supisne_cislo"] == ["4578"]
    assert {"register": "C", "number": "9238"} in c["parcels"]


def test_extract_cadastre_okresny_urad_fallback():
    t = ("v katastrálnom území Pravotice, zapísané okresným úradom Bánovce nad Bebravou, katastrálny odbor "
         "Pravotice, na LV č. 596, 116. Súp. č. 136, parc. č. 14/2")
    c = T.extract_cadastre(t)
    assert c["ku"] == "Pravotice"
    assert c["okres_urad"] == "Bánovce nad Bebravou"
    assert "okres" not in c
    assert c["lv"] == ["596"]
    assert c["supisne_cislo"] == ["136"]
    assert c["parcels"][0]["number"] == "14/2"


def test_extract_cadastre_tax_text():
    t = ("nehnuteľnosť evidovaná na Okresnom úrade Senec, Katastrálny odbor, Okres: Senec, Obec: Bernolákovo, "
         "Katastrálne územie: Bernolákovo, na liste vlastníctva č. 1358. Záhrada - parc. číslo 2739/88")
    c = T.extract_cadastre(t)
    assert (c["okres"], c["obec"], c["ku"], c["lv"]) == ("Senec", "Bernolákovo", "Bernolákovo", ["1358"])
    assert c["parcels"][0]["number"] == "2739/88"


@pytest.mark.parametrize("s,expected", [
    ("byt č. 4 nachádzajúci sa na 1.p. bytového domu", "byt"),
    ("Rodinný dom súpisné číslo 173 v obci Horné Semerovce", "dom"),
    ("pozemok parc. č. 4396/5 orná pôda", "pozemok"),
    ("trvalý trávny porast", "pozemok"),
    ("nebytový priestor č. 3 – obchodná prevádzka", "nebytovy"),
    ("rekreačná chata so súpisným číslom 12", "rekreacny"),
    ("garáž súp. č. 1200", "garaz"),
    ("osobné motorové vozidlo", "ine"),
])
def test_property_type(s, expected):
    assert T.detect_property_type(s) == expected


def test_regions():
    assert normalize_okres("Okres Zvolen") == "Zvolen"
    assert normalize_okres("Bratislava 4") == "Bratislava IV"
    assert normalize_okres("Košice-okolie") == "Košice - okolie"
    assert normalize_okres("Bratislava") is None
    assert kraj_for_okres("Nové Zámky") == "Nitriansky kraj"
    assert kraj_for_okres("Stará Ľubovňa") == "Prešovský kraj"


def test_norm_key():
    assert T.norm_key("DRAŽOBNÍK, s.r.o.") == T.norm_key("Dražobník s. r. o.")


def test_redact_personal():
    s = ("Záložné právo v prospech: Tibor Kováč (nar. 21.02.1966), bytom Nitra; - Ing. Peter Jančiar r. Jančiar "
         "(nar. 19.09.1963); Vo vlastníctve: Rudolf Pajdič, rod. Pajdič, nar. 03.03.1972, Lekárovce 193; "
         "r. č. 720303/1234; veriteľ - Ing. Peter Jančiar, Banská Bystrica (nar. 19.09.1963). Dražobník: DRAŽOBNÍK, s.r.o., IČO 36764281.")
    r = T.redact_personal(s)
    for leak in ("Tibor", "Kováč", "Jančiar", "Pajdič", "21.02.1966", "19.09.1963", "03.03.1972", "720303"):
        assert leak not in r, (leak, r)
    assert "DRAŽOBNÍK, s.r.o., IČO 36764281" in r
    assert T.redact_personal(None) is None


def test_redact_owner_and_address():
    s = ("vo vlastníctve:\nEva Žiaková r. Žiaková, bytom Bieloruská 5192/40, Bratislava, PSČ 821 06, občan SR, "
         "Dátum narodenia: 14.11.1989 , Spoluvlastnícky podiel 1/74. Správca dlžníka: Michal Jarka, nar. 17.06.1991, "
         "trvale bytom Čičava 86, 093 01 Vranov. Navrhovateľ: Prima banka Slovensko, a.s., IČO 31575951")
    r = T.redact_personal(s)
    for leak in ("Žiaková", "Bieloruská", "14.11.1989", "Jarka", "17.06.1991", "Čičava 86"):
        assert leak not in r, (leak, r)
    assert "Prima banka Slovensko, a.s., IČO 31575951" in r
    assert "Spoluvlastnícky podiel 1/74" in r


def test_redact_decomposed_unicode():
    import unicodedata
    s = unicodedata.normalize("NFD", "občan SR, Dátum narodenia: 14.11.1989 , podiel")
    assert "14.11.1989" not in T.redact_personal(s)
