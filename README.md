# Dražby nehnuteľností SK

Každý deň zbiera dražby nehnuteľností na Slovensku z verejných registrov, spojí ich do jednej
databázy a ukáže na mape a v zozname s filtrami.

- **Zdroje:** Obchodný vestník (dobrovoľné, exekučné a daňové dražby — cez
  [Slovensko.Digital Datahub](https://ekosystem.slovensko.digital/sluzby/datahub)),
  Notársky centrálny register dražieb (notar.sk), kataster ÚGKK (poloha a tvar parcely).
- **Podrobnosti o zdrojoch:** [docs/sources.md](docs/sources.md) · rozhodnutia: [docs/DECISIONS.md](docs/DECISIONS.md)
  · prekážky: [docs/BLOCKERS.md](docs/BLOCKERS.md) · stav: [docs/STATUS.md](docs/STATUS.md)

## Štruktúra

| Priečinok | Čo tam je |
|---|---|
| `scrapers/drazby/` | Python: sťahovanie (`sources/ov.py`, `sources/ncrd.py`), databáza (`db.py`), deduplikácia, geokódovanie, export, upozornenia |
| `scrapers/tests/` | testy (pytest) na reálnych vzorkách z `fixtures/` |
| `fixtures/` | uložené skutočné oznámenia z OV (XML) a NCRD (HTML, PDF) |
| `web/` | webová appka (Vite + React + TypeScript + Tailwind + MapLibre) |
| `web/public/data/` | exportované dáta pre web (`auctions.json`, `a/<id>.json`, `meta.json`) |
| `supabase/migrations/` | schéma pre Supabase (Postgres + PostGIS) |
| `.github/workflows/` | nočný zber (`daily.yml`, zatiaľ len ručne) a testy (`tests.yml`) |
| `data/` | lokálna SQLite databáza (nie je v gite) |

## Spustenie na počítači

Potrebuješ [uv](https://docs.astral.sh/uv/) (Python) a Node.js.

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e '.[dev]'
```

```bash
.venv/bin/python -m drazby daily
```

To spraví všetko: stiahne nové podania z OV (pri prvom behu 120 dní dozadu, cca 20 min), NCRD,
nájde polohy v katastri a vyexportuje dáta do `web/public/data/`. Jednotlivé kroky:

```bash
.venv/bin/python -m drazby ov          # Obchodný vestník (inkrementálne)
.venv/bin/python -m drazby ncrd        # notári: −7 až +120 dní
.venv/bin/python -m drazby geocode     # poloha z katastra
.venv/bin/python -m drazby export      # JSON pre web
.venv/bin/python -m drazby stats       # prehľad databázy
.venv/bin/python -m drazby reparse     # po oprave parsera: prečíta uložené podania OV znova
.venv/bin/python -m drazby rebuild     # po zmene deduplikácie: poskladá všetky dražby nanovo
```

Web:

```bash
cd web && npm install && npm run dev
```

Testy:

```bash
.venv/bin/python -m pytest
```

## Uložené hľadania a upozornenia

```bash
.venv/bin/python -m drazby search-add --email ja@example.com --name "Byty Žilina" --filters '{"kraj":"Žilinský kraj","types":["byt"],"maxPrice":150000}'
```

Pri každom `daily` sa nájdu nové dražby pre každé hľadanie. Bez SMTP nastavení sa e-mail len uloží
do `data/outbox/*.eml`. S nastaveniami nižšie a prepínačom `--send` sa odošle.

## Nočná automatika (GitHub Actions)

`.github/workflows/daily.yml` je pripravený, ale **zatiaľ sa spúšťa len ručne**
(GitHub → Actions → „Denný zber dražieb“ → Run workflow). Na zapnutie každú noc o 2:00 odkomentuj
v súbore riadky `schedule:` a `- cron: ...`.

Workflow si databázu prenáša cez cache, vyexportované JSON commitne do repa a Vercel nasadí novú verziu.

### Secrets (GitHub → Settings → Secrets and variables → Actions)

Všetky sú **nepovinné** — bez nich všetko beží zo SQLite a statických súborov.

| Názov | Načo |
|---|---|
| `DATABASE_URL` | Supabase Postgres (`postgresql://postgres:…@db.<projekt>.supabase.co:5432/postgres`) — dáta sa po každom behu prelejú (`pgsync`) |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | odosielanie upozornení e-mailom |
| premenná `SITE_URL` | adresa webu v e-mailoch (napr. `https://drazby-app.vercel.app`) |

## Supabase

1. Založ projekt na supabase.com.
2. V SQL editore spusti `supabase/migrations/20261008000000_init.sql`.
3. Pridaj secret `DATABASE_URL` (pozri vyššie). Lokálne: `DATABASE_URL=… .venv/bin/python -m drazby pgsync`.

## Vercel

Nový projekt z repa `matus1423/drazby-app`, **Root Directory = `web`**. Ostatné nastavenia sú vo
`web/vercel.json`. Každý push na `main` (aj nočný commit dát) nasadí novú verziu.

## Upozornenie

Údaje majú len informatívny charakter, nie sú právne záväzné. Zdroj: Obchodný vestník, NCRD, ÚGKK SR.
