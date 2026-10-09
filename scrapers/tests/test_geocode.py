import json

import pytest

from drazby import geocode as G


@pytest.fixture(autouse=True)
def no_bundled_table(tmp_path, monkeypatch):
    """Testy kreslia vlastný kataster; pribalenú tabuľku k. ú. vypneme (okrem testu, ktorý si ju nastaví)."""
    monkeypatch.setattr(G, "KU_TABLE", tmp_path / "nie-je.json")
    monkeypatch.setattr(G, "PARCEL_TABLE", tmp_path / "nie-je-p.json")
    G._ku_table.cache_clear()
    G._parcel_table.cache_clear()
    yield
    G._ku_table.cache_clear()
    G._parcel_table.cache_clear()

SQUARE = {"type": "Polygon", "coordinates": [[[18.0, 48.0], [18.2, 48.0], [18.2, 48.2], [18.0, 48.2], [18.0, 48.0]]]}


def test_centroid():
    lng, lat = G.centroid(SQUARE)
    assert round(lng, 6) == 18.1 and round(lat, 6) == 48.1
    assert G.centroid(None) is None


def test_simplify_keeps_shape():
    ring = [[18.0, 48.0], [18.000001, 48.0], [18.2, 48.0], [18.2, 48.2], [18.0, 48.0]]
    assert G.simplify_ring(ring) == [[18.0, 48.0], [18.2, 48.0], [18.2, 48.2], [18.0, 48.0]]


class FakeGeocoder(G.Geocoder):
    """Kataster bez internetu: k. ú. 'Zvolen' má kód 873705, parcela 100/1 existuje."""

    def __init__(self, store):
        super().__init__(store)
        self.calls = []

    def _get_json(self, client, url):
        self.calls.append(url)
        if "CadastralZoning" in url:
            if "Zvolen" in url:
                return {"features": [{"properties": {"label": "Zvolen", "nationalCadastalZoningReference": "873705"},
                                      "geometry": SQUARE}]}
            return {"features": []}
        feats = []
        for ref in ("873705_100/1.C", "873705_100/2.C"):
            if ref in url:
                feats.append({"properties": {"nationalCadastralReference": ref,
                                             "referencePoint": {"coordinates": [19.1, 48.57]}}, "geometry": SQUARE})
        if feats:
            return {"features": feats}
        return {"features": []}


def test_locate_parcel_then_ku(store):
    g = FakeGeocoder(store)
    r = g.locate({"ku": "Zvolen", "obec": "Zvolen", "parcels": [{"register": "C", "number": "100/1"}]})
    assert r["precision"] == "parcela" and r["lat"] == 48.57 and r["geom"]["type"] == "Polygon"
    # parcela registra E sa v katastri nehľadá → stred k. ú.
    r = g.locate({"ku": "Zvolen", "obec": "Zvolen", "parcels": [{"register": "E", "number": "5"}]})
    assert r["precision"] == "ku" and round(r["lat"], 3) == 48.1
    # druhýkrát sa už k. ú. nepýta (cache)
    n = len(g.calls)
    g.locate({"ku": "Zvolen", "parcels": []})
    assert len(g.calls) == n
    assert g.locate({"ku": "Neexistuje", "obec": "Neexistuje", "parcels": []}) is None
    g.close()


def test_multiple_parcels_become_multipolygon(store):
    g = FakeGeocoder(store)
    r = g.locate({"ku": "Zvolen", "parcels": [{"register": "C", "number": "100/1"}, {"register": "C", "number": "100/2"},
                                             {"register": "C", "number": "999"}]})
    assert r["precision"] == "parcela"
    assert r["geom"]["type"] == "MultiPolygon" and len(r["geom"]["coordinates"]) == 2
    g.close()


def test_parcels_in_one_request(store):
    g = FakeGeocoder(store)
    g.locate({"ku": "Zvolen", "parcels": [{"number": "100/1"}, {"number": "100/2"}, {"number": "5"}]})
    parcel_calls = [u for u in g.calls if "CadastralParcel" in u]
    assert len(parcel_calls) == 1          # všetky parcely jedným dopytom
    g.locate({"ku": "Zvolen", "parcels": [{"number": "100/1"}, {"number": "5"}]})
    assert len([u for u in g.calls if "CadastralParcel" in u]) == 1   # nenájdené aj nájdené sú v cache
    g.close()


def test_bundled_ku_table_without_internet(store, tmp_path, monkeypatch):
    t = tmp_path / "ku.json"
    t.write_text(json.dumps({"873705": ["Zvolen", 48.57, 19.12]}))
    monkeypatch.setattr(G, "KU_TABLE", t)
    G._ku_table.cache_clear()

    class Offline(G.Geocoder):
        def _get_json(self, client, url):
            raise AssertionError("nemá ísť na internet pre k. ú.")
    g = Offline(store)
    r = g.locate({"ku": "Zvolen", "parcels": [{"register": "E", "number": "1"}]})
    assert r == {"lat": 48.57, "lng": 19.12, "precision": "ku"}
    g.close()


def test_circuit_breaker_stops_calling_dead_service(store, tmp_path, monkeypatch):
    t = tmp_path / "ku.json"
    t.write_text(json.dumps({"873705": ["Zvolen", 48.57, 19.12]}))
    monkeypatch.setattr(G, "KU_TABLE", t)
    G._ku_table.cache_clear()
    g = G.Geocoder(store)
    calls = []

    def dead(url, **kw):
        calls.append(url)
        raise TimeoutError("timed out")
    monkeypatch.setattr(g.wfs, "get", dead)
    for i in range(10):
        r = g.locate({"ku": "Zvolen", "parcels": [{"register": "C", "number": str(100 + i)}]})
        assert r["precision"] == "ku"          # stále aspoň stred k. ú.
    assert len(calls) == G.MAX_FAILURES        # po pár výpadkoch sa kataster už nevolá
    g.close()


def test_bundled_parcels(store, tmp_path, monkeypatch):
    k = tmp_path / "ku.json"
    k.write_text(json.dumps({"873705": ["Zvolen", 48.57, 19.12]}))
    pt = tmp_path / "p.json"
    pt.write_text(json.dumps({"873705_7/1.C": [48.5, 19.1, SQUARE]}))
    monkeypatch.setattr(G, "KU_TABLE", k)
    monkeypatch.setattr(G, "PARCEL_TABLE", pt)
    G._ku_table.cache_clear(); G._parcel_table.cache_clear()

    class Offline(G.Geocoder):
        def _get_json(self, client, url):
            raise AssertionError("nemá ísť na internet")
    g = Offline(store)
    r = g.locate({"ku": "Zvolen", "parcels": [{"number": "7/1"}]})
    assert r["precision"] == "parcela" and r["lat"] == 48.5 and r["geom"] == SQUARE
    g.close()
