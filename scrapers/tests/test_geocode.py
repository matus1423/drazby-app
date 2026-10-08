from drazby import geocode as G

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
