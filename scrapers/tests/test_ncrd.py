from datetime import date

from conftest import FIX
from drazby.sources import ncrd


def _search():
    return ncrd.parse_search((FIX / "ncrd" / "search_2026-10-08_2026-12-31.html").read_text(encoding="utf-8"))


def test_parse_search_rows():
    rows = _search()
    assert len(rows) == 20  # stránka vráti max. 20 riadkov
    r = rows[0]
    assert r["act_id"] == "6ac38c5016f10a2bd353a7e3"
    assert r["number"] == "1167/2026"
    assert r["auctioneer_name"] == "Arveres s. r. o."
    assert r["auctioneer_ico"] == "55997121"
    assert r["auction_date"] == date(2026, 11, 13)
    assert ncrd.notice_type_from_label(r["act_label"]) == "oznamenie"


def test_parse_search_repeated_links_original():
    rep = [r for r in _search() if r["number"] == "1181/2026"][0]
    assert ncrd.notice_type_from_label(rep["act_label"]) == "opakovana"
    assert rep["orig_number"] == "478/2026"
    assert rep["orig_act_id"] == "69f099eb186f7b1b87dc944b"


def test_parse_detail_fields():
    det = ncrd.parse_detail((FIX / "ncrd" / "detail_6ab4f41616f10a2bd353a593.html").read_text(encoding="utf-8"))
    f = det["fields"]
    assert f["Spisová značka NCRdr"]
    assert "Nehnuteľná vec" in f["Druh predmetu dražby"]
    assert det["documents"] and det["documents"][0]["url"].startswith("https://www.notar.sk/listina/")


def test_to_notice_from_fixture():
    rows = {r["act_id"]: r for r in _search()}
    html = (FIX / "ncrd" / "detail_6abce8a416f10a2bd353a6bd.html").read_text(encoding="utf-8")
    n = ncrd.to_notice(rows["6abce8a416f10a2bd353a6bd"], ncrd.parse_detail(html))
    assert n["source"] == "ncrd"
    assert n["auctioneer_ico"] == "51580268"
    assert n["auction_at"].startswith("2026-11-12")
    assert n["notice_type"] == "oznamenie"
    assert n["venue"]
    assert n["case_key"] == "ncrd|1149/2026"


def test_movable_items_skipped():
    det = {"fields": {"Druh predmetu dražby": "Hnuteľná vec", "Spisová značka NCRdr": "1/2026",
                      "Dátum a čas vykonania zápisu v NCRdr": "01.10.2026 10:00:00"}, "documents": []}
    assert ncrd.to_notice({"act_id": "x", "number": "1/2026"}, det) is None


def test_pdf_text_broken_input():
    # PDF listiny z NCRD v repe nie sú (obsahujú osobné údaje) – overíme aspoň, že zlé PDF nespadne
    assert ncrd.pdf_to_text(b"toto nie je pdf") == ""


def test_empty_detail_is_error():
    import pytest
    with pytest.raises(ValueError):
        ncrd.to_notice({"act_id": "x", "number": "1/2026"}, {"fields": {}, "documents": []})
