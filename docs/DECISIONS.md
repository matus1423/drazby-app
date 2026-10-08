# Rozhodnutia

Každé rozhodnutie: **čo**, **prečo**, **alternatívy**.

## D1 — Hlavný zdroj je Obchodný vestník cez Slovensko.Digital Datahub
- **Čo:** OV podania sťahujeme z `datahub.ekosystem.slovensko.digital/api/data/ov/raw_issues/sync`.
- **Prečo:** Vracia pôvodné štruktúrované XML (rovnaké ako oficiálny export MS SR), bez registrácie,
  bez časových okien. Obsahuje dobrovoľné, exekučné aj daňové dražby.
- **Alternatívy:** HTML scraping OV (ASP.NET, ViewState, horšia štruktúra); oficiálny XML export MS SR
  (vyžaduje registráciu poštou — pripravené na neskôr, formát je rovnaký).

## D2 — SKE (ske.sk) nesťahujeme
- **Čo:** Komoru exekútorov vynechávame úplne.
- **Prečo:** `robots.txt` má `Disallow: /` pre všetkých. Navyše ich zoznam vyhlášok odkazuje na
  `ov_podanie_id` — sú to kópie podaní z OV, ktoré už máme štruktúrovane.
- **Alternatívy:** Ignorovať robots.txt (neslušné, porušuje zadanie); požiadať SKE o export.

## D3 — NCRD sa pýtame po jednotlivých dňoch
- **Čo:** `notar.sk/drazby/` vracia max. 20 riadkov bez stránkovania → iterujeme deň po dni
  (−7 až +120 dní), pri 20 výsledkoch ešte podľa typu úkonu.
- **Prečo:** Jediný spôsob, ako dostať úplný zoznam. ~130 dopytov denne pri pauze 1,5 s = ~3 min.
- **Alternatívy:** Iterovať cez okresy (79×, aj tak by mohli byť >20); Playwright (netreba, je to GET).

## D4 — PDF listiny NCRD bez OCR
- **Čo:** Z PDF berieme text len ak ho PDF obsahuje (pdfplumber). Skeny (väčšina) neOCR-ujeme.
- **Prečo:** Rovnaké dražby sú v OV so štruktúrovanými údajmi; NCRD slúži hlavne na doplnenie
  notára, presného času a na kontrolu úplnosti. OCR (tesseract + slovenčina) je pomalé a nepresné na sumy.
- **Alternatívy:** `tesseract-ocr-slk` v GitHub Actions — dá sa doplniť, ak sa ukáže veľa dražieb len v NCRD
  (pozri štatistiku v STATUS.md).

## D5 — Model: oznámenia (notices) → dražby (auctions), nehnuteľnosti 1:N
- **Čo:** Každé podanie/úkon je `notice`. Dražba (`auction`) sa skladá z oznámení: nové kolo, dodatok,
  výsledok, upustenie upravia tú istú dražbu a zmeny sa zapíšu do `auction_history`.
  Nehnuteľnosti (`properties`) patria k dražbe 1:N.
- **Prečo:** Opakované kolá a zmeny sú tá istá dražba z pohľadu používateľa (história ceny).
  M:N väzba medzi dražbami a nehnuteľnosťami by bola užitočná len na spájanie rôznych dražieb tej istej
  nehnuteľnosti — to rieši deduplikácia (k. ú. + LV) priamo.
- **Alternatívy:** Každé kolo ako samostatná dražba + M:N `auction_properties` (pôvodný návrh).

## D6 — Kľúče na zoskupovanie
- Dobrovoľná: `IČO dražobníka + číslo dražby`. Opakované kolo s novým číslom sa pripojí cez
  deduplikáciu (rovnaký dražobník + prekryv k. ú. a LV).
- Exekučná: `exekútor + spisová značka bez poradového čísla písomnosti (278EX 150/22)` **+ k. ú. + LV**,
  lebo jedna exekúcia často draží viac nehnuteľností samostatne v ten istý deň.
- Daňová: `daňový úrad + číslo daňového exekučného konania`.
- NCRD: `číslo pôvodného oznámenia NCRdr`; párovanie na OV podľa dražobníka (IČO) a dňa, pri viacerých
  kandidátoch podľa času a miesta.
- **Spresnené po kontrole reálnych dát (8. 10. večer):**
  - Pravidlo „rovnaký dražobník + rovnaký deň“ platí len **naprieč zdrojmi** (NCRD ↔ OV). V rámci OV
    rozhoduje kľúč – inak sa zlepili rôzne byty toho istého domu dražené v ten istý deň po 45 minútach.
  - Ďalšie kolo sa pripojí, len ak sú dražby od seba **14 až 366 dní**; poradie príchodu oznámení nehrá rolu.
  - Rovnaký deň + iný čas + iné číslo = iná dražba (aj pri zhode spisovej značky exekúcie).
  - Jedna dražba môže mať najviac **jeden spis NCRD**.
  - Exekútorov porovnávame bez titulov a bez ohľadu na poradie mena a priezviska („Marko Rus“ = „Rus Marko“).
  - Výsledok/upustenie/zmarenie nemení dátum dražby (týka sa staršieho kola).
  - História zmien zapisuje len zmeny v rámci toho istého zdroja (rozdiel NCRD vs. OV nie je zmena).

## D7 — Priorita zdrojov pri spájaní
- OV (štruktúrované) prepisuje NCRD; NCRD len dopĺňa chýbajúce polia (notár, čas, miesto).
- Oznámenia o výsledku/upustení/zmarení/dodatku neprepisujú popis, najnižšie podanie ani znaleckú cenu.

## D8 — Mená povinných (vlastníkov) neukladáme
- **Čo:** Exekučné vyhlášky obsahujú meno a adresu vlastníka (`Owner`). Do databázy ich nedávame.
- **Prečo:** Osobné údaje fyzických osôb (GDPR, minimalizácia). Pre vyhľadávanie dražieb netreba.
  Ostávajú len v surovom XML zdroja, ktoré si neukladáme celé (ukladáme vyparsované polia).
- **Alternatívy:** Ukladať a nezobrazovať — zbytočné riziko.

## D9 — Lokálne SQLite + statický JSON export pre frontend
- **Čo:** Scraper zapisuje do `data/drazby.sqlite`. Príkaz `export` vyrobí `web/public/data/auctions.json`
  (kompaktný zoznam) a `a/<id>.json` (detaily). Frontend číta statické súbory.
- **Prečo:** Supabase prístupy zatiaľ nie sú. Statické súbory fungujú na Verceli bez servera a sú rýchle
  (CDN). Pri ~1–3 tisíc dražbách je `auctions.json` pár stoviek kB (gzip menej).
- **Prechod na Supabase:** migrácie v `supabase/migrations/`, príkaz `python -m drazby pgsync` preleje
  SQLite do Postgresu (PostGIS). Frontend môže neskôr čítať pohľad `auctions_map`.
- **Alternatívy:** Rovno Supabase (chýbajú prístupy); API server (zbytočná prevádzka).

## D10 — Databáza v GitHub Actions cez cache
- **Čo:** `data/drazby.sqlite` sa medzi nočnými behmi prenáša cez `actions/cache`. Exportované JSON sa
  commitujú do repa → Vercel nasadí novú verziu.
- **Prečo:** Netreba externú databázu. Keď cache vypadne (7 dní nepoužitia), zber si DB postaví znova
  z Datahubu (`--days 150`), takže sa nič nestratí okrem histórie starších zmien.
- **Alternatívy:** Commitovať SQLite (repo by rástlo o MB denne); Supabase (po doplnení secrets sa
  `pgsync` spustí automaticky v rámci `daily`).

## D11 — Nočná automatika zatiaľ len ručne
- **Čo:** `daily.yml` má `schedule` zakomentovaný; spustiť sa dá ručne (Actions → Run workflow).
- **Prečo:** Zadanie: „workflow priprav, ale nespúšťaj“. Testy (`tests.yml`) bežia pri pushi — sú lacné
  a nič nenasadzujú.

## D12 — Geokódovanie: parcela (ÚGKK INSPIRE) → k. ú. → obec ako k. ú.
- **Čo:** Pre parcely registra C hľadáme presnú parcelu vo WFS `inspirews.skgeodesy.sk/geoserver/cp/ows`
  (identifikátor `<kód k. ú.>_<číslo>.C`), dostaneme bod aj polygón. Inak stred k. ú., inak stred k. ú.
  s rovnakým názvom ako obec. Všetko sa cachuje v tabuľke `geocache`.
- **Nominatim nepoužívame:** jeho `robots.txt` zakazuje `/search` robotom. Kód je pripravený, ale vypnutý
  (`USE_NOMINATIM = False`). Dražby bez k. ú. aj obce ostanú v zozname, len bez bodu na mape.
- **Prečo:** INSPIRE služba je verejná, bez kľúča, s presnou geometriou. Register E (pôvodný stav)
  v nej nie je — tam ostáva stred k. ú.
- **Alternatívy:** ZBGIS REST (iné rozhranie, podobné dáta); Portál ESKN (bez verejného API).

## D13 — Frontend: Vite + React + TS + Tailwind + MapLibre (OpenFreeMap)
- **Čo:** Mapa MapLibre GL s klastrami (GeoJSON source `cluster: true`), podklad OpenFreeMap „positron“
  (zadarmo, bez kľúča). Filtre sa držia v adrese (`#kraj=…&typ=byt`), takže sa dajú zdieľať odkazom.
- **Alternatívy:** Leaflet + markercluster (pomalší pri tisíckach bodov), Mapbox (kľúč, platené).

## D14 — Hnuteľné veci vynechávame
- NCRD úkony s „Druh predmetu dražby“ ≠ nehnuteľná vec preskakujeme (autá, stroje…).

## D15 — k. ú. ako náhrada obce
- Keď text uvádza len katastrálne územie, berieme ho aj ako obec (väčšinou sa zhodujú). Okres sa doplní
  zo spojenia „Okresný úrad X, katastrálny odbor“, ak inde chýba.

## D16 — Python cez `uv`
- Homebrew Python 3.12 na tomto Macu padá (pyexpat nesedí so systémovou libexpat) → `uv venv --python 3.12`
  si stiahne samostatný Python. V GitHub Actions sa používa `actions/setup-python`.

## D17 — Surové podania sa ukladajú, dražby sa dajú poskladať nanovo
- **Čo:** XML z OV sa ukladá do `raw_items`. `drazby reparse` prečíta podania znova aktuálnym parserom,
  `drazby rebuild` poskladá všetky dražby nanovo (v poradí zverejnenia). Polohy ostávajú v `geocache`.
- **Prečo:** Parser a deduplikácia sa budú zlepšovať; bez surových dát by sa staré záznamy nedali opraviť.
- **Pozor:** `rebuild` zmení čísla (id) dražieb – odkazy typu `#id=123` prestanú sedieť. Pred spustením
  verejnej verzie OK; neskôr by bolo treba stabilné id (napr. z `group_key`).

## D18 — NCRD pomaly a bez PDF
- notar.sk po sérii dopytov každých 1,5 s vrátil `Retry-After: 3600`. Teraz pauza 5 s, PDF sa nesťahujú
  (väčšinou skeny), pri dlhom `Retry-After` beh skončí a pokračuje nabudúce. Prázdna stránka detailu
  (počas preťaženia) sa neuloží a skúsi sa znova.

## D19 — Geokódovanie parciel jedným dopytom
- WFS katastra odpovedá ~4 s na dopyt bez ohľadu na počet parciel → všetky parcely nehnuteľnosti
  (max. 6) sa pýtajú jedným dopytom s `<Or>`. Nenájdené parcely sa tiež cachujú.
