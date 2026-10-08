"""Uložené hľadania a e-mailové upozornenia na nové dražby.

Uložené hľadanie = e-mail + filtre (rovnaké kľúče ako vo frontende, napr.
{"kraj": "Žilinský kraj", "types": ["byt", "dom"], "maxPrice": 120000}).

Pri každom behu sa pre každé aktívne hľadanie nájdu dražby, ktoré pribudli od
posledného upozornenia, zapíšu sa do `notifications` a pripraví sa e-mail:
- bez SMTP nastavení sa e-mail len uloží do `data/outbox/*.eml` (na kontrolu),
- s `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` a prepínačom `--send` sa odošle.
"""

from __future__ import annotations

import html
import json
import logging
import os
import smtplib
import unicodedata
from datetime import date
from email.message import EmailMessage
from pathlib import Path

from .db import Store, effective_status, now
from .export import KIND_LABELS, public_id
from .text import PROPERTY_TYPES

log = logging.getLogger(__name__)

SITE_URL = os.environ.get("SITE_URL", "https://drazby-app.vercel.app")


def _n(s: str | None) -> str:
    s = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def matches(a: dict, f: dict) -> bool:
    if f.get("kraj") and a["kraj"] != f["kraj"]:
        return False
    if f.get("okres") and a["okres"] != f["okres"]:
        return False
    if f.get("types") and (a["property_type"] or "ine") not in f["types"]:
        return False
    if f.get("kinds") and a["kind"] not in f["kinds"]:
        return False
    price = a["min_bid"] if a["min_bid"] is not None else a["appraised_value"]
    if f.get("minPrice") is not None and (price is None or price < f["minPrice"]):
        return False
    if f.get("maxPrice") is not None and (price is None or price > f["maxPrice"]):
        return False
    if f.get("round") == "1" and (a["round"] or 1) != 1:
        return False
    if f.get("round") == "2+" and (a["round"] or 1) < 2:
        return False
    if f.get("q"):
        hay = _n(" ".join(x for x in [a["title"], a["obec"], a["ku"], a["okres"], a["kraj"], a["auctioneer_name"]] if x))
        if not all(w in hay for w in _n(f["q"]).split()):
            return False
    return effective_status(a["status"], a["auction_at"]) in ("pripravovana", "odrocena")


def add_search(store: Store, email: str, filters: dict, name: str | None = None) -> int:
    cur = store.con.execute(
        "INSERT INTO saved_searches(email, name, filters, created_at, last_notified_at) VALUES(?,?,?,?,?)",
        (email, name, json.dumps(filters, ensure_ascii=False), now(), now()))
    store.commit()
    return cur.lastrowid


def _money(v):
    return "—" if v is None else f"{v:,.0f} €".replace(",", " ")


def render_email(search: dict, auctions: list[dict]) -> tuple[str, str, str]:
    name = search.get("name") or "Vaše hľadanie"
    subject = f"{len(auctions)} {'nová dražba' if len(auctions) == 1 else 'nové dražby'} – {name}"
    lines_txt, rows_html = [], []
    for a in auctions:
        url = f"{SITE_URL}/#id={public_id(a['group_key'])}"
        title = f"{PROPERTY_TYPES.get(a['property_type'] or 'ine')}, {a['obec'] or a['ku'] or a['okres'] or ''}"
        when = (a["auction_at"] or "")[:10]
        lines_txt.append(f"- {title} | {KIND_LABELS.get(a['kind'])} | {when} | {_money(a['min_bid'])}\n  {url}")
        rows_html.append(
            f"<tr><td style='padding:6px 8px'><a href='{url}'>{html.escape(title)}</a></td>"
            f"<td style='padding:6px 8px'>{when}</td><td style='padding:6px 8px;text-align:right'>"
            f"{_money(a['min_bid'])}</td></tr>")
    footer = ("Údaje majú len informatívny charakter a nie sú právne záväzné. "
              "Zdroj: Obchodný vestník, NCRD.")
    text = f"{name}\n\n" + "\n".join(lines_txt) + f"\n\n{footer}\n"
    body = (f"<h2 style='font-family:sans-serif'>{html.escape(name)}</h2>"
            f"<table style='font-family:sans-serif;border-collapse:collapse'>{''.join(rows_html)}</table>"
            f"<p style='font-family:sans-serif;color:#666;font-size:12px'>{footer}</p>")
    return subject, text, body


def run_notifications(store: Store, outdir: Path | None = None, dry_run: bool = True) -> dict:
    outbox = Path(store.path).parent / "outbox"
    stats = {"searches": 0, "new_matches": 0, "emails": 0, "sent": 0}
    searches = [dict(r) for r in store.con.execute("SELECT * FROM saved_searches WHERE active=1")]
    if not searches:
        return stats
    smtp_ok = all(os.environ.get(k) for k in ("SMTP_HOST", "SMTP_FROM"))
    for s in searches:
        stats["searches"] += 1
        f = json.loads(s["filters"])
        since = s["last_notified_at"] or s["created_at"]
        cands = [dict(r) for r in store.con.execute(
            "SELECT * FROM auctions WHERE first_seen > ? AND id NOT IN (SELECT auction_id FROM notifications WHERE search_id=?)",
            (since, s["id"]))]
        hits = [a for a in cands if matches(a, f)]
        if not hits:
            continue
        stats["new_matches"] += len(hits)
        ts = now()
        for a in hits:
            store.con.execute("INSERT OR IGNORE INTO notifications(search_id, auction_id, created_at) VALUES(?,?,?)",
                              (s["id"], a["id"], ts))
        subject, text, body = render_email(s, hits)
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = os.environ.get("SMTP_FROM", "drazby@localhost")
        msg["To"] = s["email"]
        msg.set_content(text)
        msg.add_alternative(body, subtype="html")
        stats["emails"] += 1
        if not dry_run and smtp_ok:
            with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587"))) as smtp:
                smtp.starttls()
                if os.environ.get("SMTP_USER"):
                    smtp.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
                smtp.send_message(msg)
            store.con.execute("UPDATE notifications SET sent_at=? WHERE search_id=? AND created_at=?", (ts, s["id"], ts))
            stats["sent"] += 1
        else:
            outbox.mkdir(parents=True, exist_ok=True)
            (outbox / f"{date.today()}_{s['id']}.eml").write_bytes(bytes(msg))
        store.con.execute("UPDATE saved_searches SET last_notified_at=? WHERE id=?", (ts, s["id"]))
    store.commit()
    return stats
