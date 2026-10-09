"""Vyrobí scrapers/drazby/data/ku.json – stredy všetkých katastrálnych území z WFS ÚGKK.

Spúšťa sa ručne (zo Slovenska; z GitHub Actions služba neodpovedá):
    .venv/bin/python scrapers/tools/build_ku_table.py
"""

import json
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from drazby.geocode import WFS, centroid  # noqa: E402
from drazby.http import USER_AGENT  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "drazby" / "data" / "ku.json"
PAGE = 100


def main():
    rows = {}
    start = 0
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=180) as c:
        while True:
            q = {"service": "WFS", "version": "2.0.0", "request": "GetFeature", "outputFormat": "application/json",
                 "typeNames": "cp:CP.CadastralZoning", "count": PAGE, "startIndex": start, "sortBy": "nationalCadastalZoningReference"}
            for attempt in range(4):
                try:
                    d = c.get(f"{WFS}?{urlencode(q)}").json()
                    break
                except Exception as e:
                    print("retry", start, e, file=sys.stderr)
                    time.sleep(10 * (attempt + 1))
            else:
                raise SystemExit(f"nepodarilo sa stiahnuť od {start}")
            feats = d.get("features") or []
            for f in feats:
                p = f["properties"]
                cen = centroid(f.get("geometry"))
                if cen:
                    rows[p["nationalCadastalZoningReference"]] = [p["label"], round(cen[1], 5), round(cen[0], 5)]
            print(start, len(feats), len(rows), file=sys.stderr)
            if len(feats) < PAGE:
                break
            start += PAGE
            time.sleep(0.5)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(dict(sorted(rows.items())), ensure_ascii=False, separators=(",", ":")))
    print(f"{len(rows)} k. ú. → {OUT}")


if __name__ == "__main__":
    main()
