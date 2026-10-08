import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scrapers"))
FIX = ROOT / "fixtures"


def load_ov(item_id: int) -> dict:
    meta = json.loads((FIX / "ov" / f"{item_id}.meta.json").read_text())
    meta["content"] = (FIX / "ov" / f"{item_id}.xml").read_text(encoding="utf-8")
    return meta


def all_ov() -> list[dict]:
    return [load_ov(int(p.stem)) for p in sorted((FIX / "ov").glob("*.xml"))]


@pytest.fixture
def store(tmp_path):
    from drazby.db import Store
    s = Store(tmp_path / "t.sqlite")
    yield s
    s.close()
