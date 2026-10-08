import pytest

from conftest import all_ov, load_ov
from drazby.sources import ov


def test_form_type_and_filter():
    assert ov.form_type("X059090-OV_DRAZBA_OZNAMENIE_DOBROVOLNA-v-2.xml") == "OV_DRAZBA_OZNAMENIE_DOBROVOLNA"
    assert ov.form_type("X059085-00166073.MSSR_OV_Drazobna_vyhlaska-v-1.5.xml") == "00166073.MSSR_OV_Drazobna_vyhlaska"
    assert ov.is_auction("X059085-00166073.MSSR_OV_Drazobna_vyhlaska-v-1.5.xml")
    assert ov.is_auction("X059457-OV_DRAZBA_SPRAVCA_DANE_2-v-2.xml")
    assert not ov.is_auction("L005196-OV_LIKVIDATOR_2020-v-1.xml")
    # prílohy (PDF) nemajú obsah a nie sú XML
    assert not ov.is_auction("X059089-UPVS_00166073.MSSR_OV_Drazobna_vyhlaska-v-2-abc@Vyhlaska.pdf")


def test_all_fixtures_parse():
    items = all_ov()
    assert len(items) >= 30
    parsed = [ov.parse_item(i) for i in items]
    assert all(p is not None for p in parsed)
    for p in parsed:
        assert p["kind"] in ("dobrovolna", "exekucna", "danova")
        assert p["auction_at"], p["source_id"]
        assert p["case_key"]
        assert p["published_at"]


def test_all_fixtures_have_location():
    """Každá vzorka musí mať aspoň obec alebo k. ú. — inak ju nevieme dať na mapu."""
    for i in all_ov():
        p = ov.parse_item(i)
        prop = (p["properties"] or [{}])[0]
        assert prop.get("obec") or prop.get("ku"), (i["id"], i["file_name"])
        assert prop.get("lv"), (i["id"], i["file_name"])


def test_executor_decree_structured():
    n = ov.parse_item(load_ov(4204759 if False else _find("278EX 150/22-371")))
    assert n["kind"] == "exekucna"
    assert n["auction_at"] == "2026-11-19T10:00:00"
    assert n["round"] == 2
    assert n["min_bid"] == pytest.approx(20317.67)
    assert n["appraised_value"] == pytest.approx(27090.23)
    assert n["deposit"] == pytest.approx(10158.83)
    p = n["properties"][0]
    assert p["kraj"] == "Banskobystrický kraj"
    assert p["okres"] == "Zvolen"
    assert p["obec"] == "Zvolen"
    assert p["obec_code"] == "518158"
    assert p["lv"] == ["10079"]
    assert len(p["parcels"]) == 5
    assert p["parcels"][0] == {"register": "E", "number": "3393/2", "area_m2": 2325.0, "kind": "trvalý trávny porast"}
    assert p["type"] == "pozemok"
    # meno povinného (vlastníka) neukladáme
    assert "Suja" not in str(n)


def test_executor_case_key_groups_rounds():
    a = ov._executor_case_key("JUDr. Rus Marko", "278EX 150/22-371")
    b = ov._executor_case_key("JUDr. Rus Marko", "278EX 150/22-412")
    assert a == b


def test_voluntary_notice():
    n = ov.parse_item(load_ov(_find("028/2026")))
    assert n["kind"] == "dobrovolna" and n["notice_type"] == "oznamenie"
    assert n["auction_number"] == "028/2026"
    assert n["auctioneer_name"] == "AUKČNÁ SPOLOČNOSŤ s.r.o."
    assert n["auctioneer_ico"] == "46141341"
    assert n["proposer"] == "Prima banka Slovensko, a.s."
    assert n["notary"] == "JUDr. Tomáš Trella"
    assert n["auction_at"] == "2026-10-27T09:00:00"
    assert n["min_bid"] == 78200.0
    assert n["min_increment"] == 200.0
    assert n["deposit"] == 15000.0
    assert n["appraised_value"] == 78200.0
    p = n["properties"][0]
    assert p["type"] == "byt"
    assert (p["okres"], p["obec"], p["ku"], p["lv"]) == ("Nové Zámky", "Nové Zámky", "Nové Zámky", ["13558"])
    assert p["kraj"] == "Nitriansky kraj"
    assert p["area_m2"] == 78.3
    assert "Štvorizbový byt" in n["title"]


def test_voluntary_table_predmet():
    """Predmet ako HTML tabuľka 'LV č. | Okresný úrad | Okres | Obec | Katastrálne územie'."""
    n = ov.parse_item(load_ov(_find("HP029/26")))
    p = n["properties"][0]
    assert p["lv"] == ["228"]
    assert p["okres"] == "Levice"
    assert p["ku"] == "Horné Semerovce"
    assert p["type"] == "dom"
    assert n["notice_type"] == "vysledok"
    assert n["highest_bid"] == 45975.0
    assert n["sold"] is True
    assert n["appraised_value"] == 61300.0


def test_voluntary_result_not_sold():
    n = ov.parse_item(load_ov(_find("034/2026")))
    assert n["notice_type"] == "vysledok"
    assert n["highest_bid"] is None
    assert n["sold"] is False


def test_voluntary_repeated_round():
    n = ov.parse_item(load_ov(_find("DU-POS DD 010a")))
    assert n["notice_type"] == "opakovana"
    assert n["round"] == 2
    assert n["min_bid"] == 1575000.0
    assert n["appraised_value"] == 2100000.0


def test_voluntary_cancelled():
    n = ov.parse_item(load_ov(_find("030/2026")))
    assert n["notice_type"] == "upustenie"
    assert "§ 19" in n["reason"]


def test_tax_auction():
    n = ov.parse_item(load_ov(_find("110000716520")))
    assert n["kind"] == "danova"
    assert n["auction_at"] == "2026-11-03T10:30:00"
    assert n["min_bid"] == 3310.0
    assert n["deposit"] == 1700.0
    assert n["auctioneer_name"] == "Daňový úrad Bratislava"
    p = n["properties"][0]
    assert (p["obec"], p["lv"], p["okres"], p["kraj"]) == ("Bernolákovo", ["1358"], "Senec", "Bratislavský kraj")


def _find(needle: str) -> int:
    for i in all_ov():
        if needle in i["content"]:
            return i["id"]
    raise AssertionError(f"vzorka s '{needle}' nenájdená")


@pytest.mark.parametrize("item_id,expected", [
    # hlavička 'Číslo LV | Katastrálne územie | Okresný úrad, katastrálny odbor' + riadok hodnôt
    (4122613, ("Nitriansky kraj", "Komárno", "Komárno", "Komárno", ["7278"])),
    # popisy pod sebou v jednej bunke ('Okres : Obec : Katastrálne územie :'), hodnoty cez viac riadkov
    (4137807, ("Trenčiansky kraj", "Prievidza", "Prievidza", "Prievidza", ["6347"])),
    # 'Okres: Obec: Katastrálne územie:' | 'Sobrance Lekárovce Lekárovce'
    (4163351, ("Košický kraj", "Sobrance", "Lekárovce", "Lekárovce", ["1295"])),
    # koniec vety: '…katastrálne územie: Chrastné. Príslušenstvo…'
    (4126720, ("Košický kraj", "Košice - okolie", "Chrastné", "Chrastné", ["557"])),
    # okres len z 'Okresným úradom - katastrálny odbor: Prievidza'
    (4158807, ("Trenčiansky kraj", "Prievidza", "Handlová", "Handlová", ["5132"])),
    # 'Katastrálny odbor Okresného úradu' je popis, nie hodnota
    (4147094, ("Košický kraj", "Rožňava", "Rožňava", "Rožňava", ["540"])),
    # Košice bez čísla okresu → aspoň kraj
    (4147093, ("Košický kraj", "Košice", "Šaca", "Šaca", ["1511"])),
])
def test_real_world_tables(item_id, expected):
    p = ov.parse_item(load_ov(item_id))["properties"][0]
    assert (p["kraj"], p["okres"], p["obec"], p["ku"], p["lv"]) == expected


def test_no_label_leaks_into_places():
    """Žiadna vzorka nesmie mať v obci/k. ú./okrese text popisu (úrad, odbor, územie…)."""
    for i in all_ov():
        for p in ov.parse_item(i)["properties"]:
            for v in (p.get("okres"), p.get("obec"), p.get("ku")):
                assert v is None or ov.valid_place(v), (i["id"], v)
