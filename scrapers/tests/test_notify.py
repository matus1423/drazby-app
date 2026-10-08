import email

from conftest import all_ov
from drazby.notify import add_search, matches, run_notifications
from drazby.sources import ov


def _a(**kw):
    base = {"id": 1, "kind": "dobrovolna", "status": "pripravovana", "auction_at": "2099-01-01T10:00:00",
            "kraj": "Žilinský kraj", "okres": "Martin", "obec": "Martin", "ku": "Martin", "property_type": "byt",
            "min_bid": 80000.0, "appraised_value": 90000.0, "round": 1, "title": "Byt", "auctioneer_name": "X"}
    base.update(kw)
    return base


def test_matches():
    assert matches(_a(), {"kraj": "Žilinský kraj", "types": ["byt"], "maxPrice": 100000})
    assert not matches(_a(), {"maxPrice": 50000})
    assert not matches(_a(), {"types": ["dom"]})
    assert not matches(_a(auction_at="2000-01-01"), {})          # minulé dražby neposielame
    assert matches(_a(), {"q": "martin"})
    assert not matches(_a(), {"round": "2+"})


def test_run_notifications_writes_outbox(store):
    sid = add_search(store, "test@example.com", {"kinds": ["exekucna"]}, "Exekúcie")
    store.con.execute("UPDATE saved_searches SET last_notified_at='2000-01-01' WHERE id=?", (sid,))
    for i in all_ov():
        store.ingest(ov.parse_item(i))
    store.commit()
    store.con.execute("UPDATE auctions SET auction_at='2099-01-01T10:00:00' WHERE kind='exekucna'")
    st = run_notifications(store)
    assert st["emails"] == 1 and st["new_matches"] >= 5
    eml = list((store.path.parent / "outbox").glob("*.eml"))
    assert eml
    msg = email.message_from_bytes(eml[0].read_bytes())
    assert msg["To"] == "test@example.com"
    # druhý beh už nič nové nepošle
    assert run_notifications(store)["emails"] == 0
