import copy
import json
from datetime import date

from conftest import all_ov
from drazby.db import effective_status
from drazby.sources import ov


def _notice(**kw):
    base = {
        "source": "ov", "source_id": "1", "source_label": "OV 1/2026", "source_url": "u", "published_at": "2026-09-01",
        "kind": "dobrovolna", "notice_type": "oznamenie", "auction_number": "10/2026",
        "case_key": "dd|12345678|10 2026", "auctioneer_name": "Dražobník s.r.o.", "auctioneer_ico": "12345678",
        "auction_at": "2026-10-10T10:00:00", "venue": "Hotel X, Nitra", "round": 1, "min_bid": 100000.0,
        "appraised_value": 100000.0, "deposit": 10000.0,
        "properties": [{"type": "byt", "obec": "Nitra", "ku": "Nitra", "okres": "Nitra", "kraj": "Nitriansky kraj",
                        "lv": ["123"], "parcels": []}],
    }
    base.update(kw)
    return base


def test_ingest_idempotent(store):
    n = _notice()
    assert store.ingest(n) == "new"
    assert store.ingest(copy.deepcopy(n)) == "same"
    assert store.con.execute("SELECT COUNT(*) FROM auctions").fetchone()[0] == 1


def test_changed_notice(store):
    store.ingest(_notice())
    assert store.ingest(_notice(min_bid=90000.0)) == "changed"


def test_repeated_round_new_number_merges_and_records_history(store):
    store.ingest(_notice())
    # 2. kolo: nové číslo dražby, nižšie najnižšie podanie, neskorší dátum, rovnaká nehnuteľnosť (k. ú. + LV)
    store.ingest(_notice(source_id="2", published_at="2026-10-20", notice_type="opakovana",
                         auction_number="10a/2026", case_key="dd|12345678|10a 2026",
                         auction_at="2026-11-20T10:00:00", round=2, min_bid=75000.0))
    assert store.con.execute("SELECT COUNT(*) FROM auctions").fetchone()[0] == 1
    a = store.con.execute("SELECT * FROM auctions").fetchone()
    assert a["round"] == 2 and a["min_bid"] == 75000.0 and a["auction_at"].startswith("2026-11-20")
    hist = {r["field"]: (r["old_value"], r["new_value"]) for r in store.con.execute("SELECT * FROM auction_history")}
    assert hist["min_bid"] == ("100000", "75000")
    assert hist["round"] == ("1", "2")
    assert "auction_at" in hist


def test_result_and_cancellation_status(store):
    store.ingest(_notice())
    store.ingest(_notice(source_id="3", notice_type="vysledok", published_at="2026-10-11",
                         highest_bid=120000.0, sold=True, min_bid=None, properties=[]))
    a = store.con.execute("SELECT * FROM auctions").fetchone()
    assert a["status"] == "prebehla" and a["highest_bid"] == 120000.0 and a["sold"] == 1
    assert a["min_bid"] == 100000.0  # výsledok neprepisuje pôvodné podanie


def test_cancellation(store):
    store.ingest(_notice())
    store.ingest(_notice(source_id="4", notice_type="upustenie", published_at="2026-10-01", properties=[]))
    assert store.con.execute("SELECT status FROM auctions").fetchone()[0] == "zrusena"


def test_cross_source_dedup_ncrd_ov(store):
    store.ingest(_notice())
    ncrd = _notice(source="ncrd", source_id="abc", source_label="NCRD 999/2026", case_key="ncrd|999/2026",
                   auction_number=None, auctioneer_name="DRAŽOBNÍK, s. r. o.", min_bid=None, appraised_value=None,
                   deposit=None, properties=[], notary="JUDr. Notár", published_at="2026-09-02")
    store.ingest(ncrd)
    assert store.con.execute("SELECT COUNT(*) FROM auctions").fetchone()[0] == 1
    a = store.con.execute("SELECT * FROM auctions").fetchone()
    srcs = {s["source"] for s in json.loads(a["sources"])}
    assert srcs == {"ov", "ncrd"}
    assert a["notary"] == "JUDr. Notár"         # NCRD doplní chýbajúce pole
    assert a["min_bid"] == 100000.0              # ale neprepíše údaje z OV


def test_same_day_two_auctions_not_merged(store):
    """Ten istý dražobník, ten istý deň, iné číslo dražby → dve dražby."""
    store.ingest(_notice())
    store.ingest(_notice(source_id="5", auction_number="11/2026", case_key="dd|12345678|11 2026",
                         auction_at="2026-10-10T11:00:00",
                         properties=[{"type": "byt", "obec": "Nitra", "ku": "Nitra", "lv": ["999"]}]))
    assert store.con.execute("SELECT COUNT(*) FROM auctions").fetchone()[0] == 2


def test_executor_multiple_properties_same_case_are_separate(store):
    """Exekútor draží 4 rôzne LV v jednom konaní (278EX 150/22-370..373) → 4 dražby."""
    for i in all_ov():
        if "278EX 150/22" in i["content"]:
            store.ingest(ov.parse_item(i))
    assert store.con.execute("SELECT COUNT(*) FROM auctions").fetchone()[0] == 4


def test_fixtures_ingest(store):
    for i in all_ov():
        store.ingest(ov.parse_item(i))
    n = store.con.execute("SELECT COUNT(*) FROM auctions").fetchone()[0]
    assert 30 <= n <= len(all_ov())
    assert store.con.execute("SELECT COUNT(*) FROM auctions WHERE kraj IS NULL").fetchone()[0] == 0


def test_effective_status():
    assert effective_status("pripravovana", "2026-01-01", date(2026, 2, 1)) == "prebehla"
    assert effective_status("pripravovana", "2026-03-01", date(2026, 2, 1)) == "pripravovana"
    assert effective_status("zrusena", "2026-01-01", date(2026, 2, 1)) == "zrusena"


def test_reparse_replaces_wrong_properties(store):
    bad = _notice(properties=[{"type": "byt", "obec": "Okresný úrad, katastrálny odbor", "ku": "Okresný úrad",
                               "okres": "Správa katastra", "lv": ["1", "2"], "parcels": [{"number": "1"}]}])
    store.ingest(bad)
    good = _notice(properties=[{"type": "byt", "obec": "Nitra", "ku": "Nitra", "okres": "Nitra", "lv": ["123"]}])
    assert store.ingest(good) == "changed"
    p = store.con.execute("SELECT * FROM properties").fetchone()
    assert p["obec"] == "Nitra"


def test_raw_items_roundtrip(store):
    store.save_raw("ov", {"id": 5, "file_name": "X-OV_DRAZBA_OZNAMENIE_DOBROVOLNA-v-2.xml", "content": "<x/>",
                          "bulletin_issue": {"number": 1, "year": 2026}})
    items = list(store.iter_raw("ov"))
    assert items[0]["content"] == "<x/>" and items[0]["bulletin_issue"]["year"] == 2026


def test_rounds_merge_in_any_order(store):
    """Novšie kolo môže prísť skôr ako staršie – aj tak je to jedna dražba."""
    store.ingest(_notice(source_id="20", published_at="2026-10-01", notice_type="opakovana", auction_number="10a/2026",
                         case_key="dd|12345678|10a 2026", auction_at="2026-11-20T10:00:00", round=2, min_bid=75000.0))
    store.ingest(_notice(source_id="21", published_at="2026-09-01"))
    assert store.con.execute("SELECT COUNT(*) FROM auctions").fetchone()[0] == 1
    a = store.con.execute("SELECT * FROM auctions").fetchone()
    assert a["round"] == 2 and a["min_bid"] == 75000.0  # staršie oznámenie neprepíše novšie kolo


def test_executor_name_order_does_not_matter(store):
    def ex(sid, name, num, day):
        return _notice(source_id=sid, kind="exekucna", auctioneer_name=name, auctioneer_ico=None,
                       auction_number=num, case_key=ov._executor_case_key(name, num), auction_at=day,
                       published_at=day[:10])
    store.ingest(ex("30", "Súdny exekútor JUDr. Marko Rus", "278EX 150/22-327", "2026-07-02T10:00:00"))
    store.ingest(ex("31", "Súdny exekútor JUDr. Rus Marko", "278EX 150/22-372", "2026-11-19T10:00:00"))
    assert store.con.execute("SELECT COUNT(*) FROM auctions").fetchone()[0] == 1


def test_two_ncrd_auctions_same_day_not_glued_to_one(store):
    """Dražobník má v ten istý deň dve dražby; NCRD bez času sa nesmie obe nalepiť na tú istú z OV."""
    store.ingest(_notice())
    base = dict(source="ncrd", auction_number=None, min_bid=None, appraised_value=None, deposit=None,
                properties=[], auction_at="2026-10-10", published_at="2026-09-02")
    store.ingest(_notice(source_id="n1", case_key="ncrd|1/2026", source_label="NCRD 1/2026", **base))
    store.ingest(_notice(source_id="n2", case_key="ncrd|2/2026", source_label="NCRD 2/2026", **base))
    rows = store.con.execute("SELECT auction_id, COUNT(*) c FROM notices WHERE source='ncrd' GROUP BY auction_id").fetchall()
    assert all(r["c"] == 1 for r in rows)


def test_same_day_units_same_lv_stay_separate(store):
    """Viac bytov v jednom dome (rovnaké LV), dražby v ten istý deň po 45 min → samostatné dražby."""
    for i, t in enumerate(["09:00", "09:45", "10:30"]):
        store.ingest(_notice(source_id=f"u{i}", auction_number=f"5{i}/2026", case_key=f"dd|12345678|5{i} 2026",
                             auction_at=f"2026-10-10T{t}:00"))
    assert store.con.execute("SELECT COUNT(*) FROM auctions").fetchone()[0] == 3


def test_executor_same_case_same_lv_same_day_separate(store):
    def ex(sid, num, at):
        name = "Súdny exekútor JUDr. Marko Rus"
        return _notice(source_id=sid, kind="exekucna", auctioneer_name=name, auctioneer_ico=None, auction_number=num,
                       case_key=ov._executor_case_key(name, num), auction_at=at)
    store.ingest(ex("e1", "278EX 150/22-10", "2026-10-10T09:00:00"))
    store.ingest(ex("e2", "278EX 150/22-11", "2026-10-10T11:00:00"))
    assert store.con.execute("SELECT COUNT(*) FROM auctions").fetchone()[0] == 2
    store.ingest(ex("e3", "278EX 150/22-30", "2026-12-10T09:00:00"))   # ďalšie kolo
    assert store.con.execute("SELECT COUNT(*) FROM auctions").fetchone()[0] == 2


def test_result_does_not_move_date(store):
    store.ingest(_notice())
    store.ingest(_notice(source_id="r", notice_type="vysledok", published_at="2026-10-12",
                         auction_at="2026-06-01T10:00:00", properties=[]))
    assert store.con.execute("SELECT auction_at FROM auctions").fetchone()[0] == "2026-10-10T10:00:00"


def test_executor_same_case_different_lv_same_day_separate(store):
    """Exekútor draží v jeden deň 3 rôzne LV v rôznych k. ú. (110EX 685/19) → 3 dražby."""
    name = "Súdny exekútor JUDr. Rudolf Dulina"
    for i, (t, ku, lv) in enumerate([("09:00", "Kevice", "176"), ("11:00", "Jazernica", "331"), ("14:00", "Mošovce", "898")]):
        store.ingest(_notice(source_id=f"d{i}", kind="exekucna", auctioneer_name=name, auctioneer_ico=None,
                             auction_number="110EX 685/19", case_key=ov._executor_case_key(name, "110EX 685/19"),
                             auction_at=f"2026-07-16T{t}:00",
                             properties=[{"type": "pozemok", "ku": ku, "obec": ku, "lv": [lv]}]))
    assert store.con.execute("SELECT COUNT(*) FROM auctions").fetchone()[0] == 3


def test_public_id_survives_rebuild(store, tmp_path):
    """Odkaz na dražbu (#id=…) musí ostať rovnaký aj po prestavaní databázy."""
    from drazby.export import export
    for i in all_ov():
        store.ingest(ov.parse_item(i))
    store.commit()
    out1 = json.loads((export(store, tmp_path / "e1") and (tmp_path / "e1" / "auctions.json")).read_text())
    store.con.execute("DELETE FROM auction_history"); store.con.execute("DELETE FROM properties")
    store.con.execute("DELETE FROM notices"); store.con.execute("DELETE FROM auctions")
    for i in all_ov():
        store.ingest(ov.parse_item(i))
    store.commit()
    out2 = json.loads((export(store, tmp_path / "e2") and (tmp_path / "e2" / "auctions.json")).read_text())
    assert {a["id"] for a in out1} == {a["id"] for a in out2}
    assert all(isinstance(a["id"], str) and len(a["id"]) == 10 for a in out1)
    assert (tmp_path / "e2" / "a" / f"{out2[0]['id']}.json").exists()
