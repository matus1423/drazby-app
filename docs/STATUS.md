# Stav projektu (9. 10. 2026)

## Čo funguje

- **Zber z Obchodného vestníka** (cez Slovensko.Digital Datahub): dobrovoľné, exekučné a daňové dražby,
  vrátane opakovaných kôl, dodatkov, výsledkov, upustení a zmarení. Inkrementálne (od posledného behu).
- **Zber z NCRD** (notar.sk): po dňoch, slušne pomaly (5 s), pri obmedzení zo strany servera beh skončí
  a pokračuje nabudúce. Notárske záznamy sa párujú s OV.
- **Databáza** (SQLite) s históriou zmien (nové kolo, nižšia cena, zmena dátumu, zrušenie, výsledok)
  a deduplikáciou naprieč zdrojmi aj kolami. Surové XML sa ukladá → `reparse` / `rebuild` po oprave parsera.
- **Poloha z katastra ÚGKK**: presná parcela (bod + tvar parciel) pre register C, inak stred katastrálneho územia.
- **Web** (Vite + React + TypeScript + Tailwind + MapLibre): mapa so zhlukmi, zoznam, filtre (kraj, okres,
  typ nehnuteľnosti, druh dražby, cena, dátum, kolo, nadchádzajúce/minulé), detail s históriou a tvarom
  parcely, zdieľateľné odkazy, mobilné rozloženie, legenda. Upozornenie o informatívnom charaktere údajov.
- **Ochrana osobných údajov**: dátumy narodenia, rodné čísla, mená vlastníkov/dlžníkov a ich adresy sa na webe
  skrývajú; mená povinných z exekúcií sa vôbec neukladajú. Vzorky v repe sú prečistené.
- **Uložené hľadania** s e-mailovým upozornením (backend; bez SMTP sa e-maily ukladajú do `data/outbox/`).
- **Supabase**: migrácia (Postgres + PostGIS) a príkaz `pgsync` sú pripravené.
- **Testy**: 104 testov (pytest) na 72 reálnych oznámeniach z OV a vzorkách NCRD.

## Koľko sa stiahlo

| | počet |
|---|---|
| Dražby spolu | **560** (dobrovoľné 270, exekučné 279, daňové 11) |
| Oznámenia z Obchodného vestníka | 815 (posledných 150 dní) |
| Oznámenia z NCRD | 100 (beh ešte pokračoval) |
| Dražby potvrdené v oboch zdrojoch | 49 |
| Nadchádzajúce dražby | 133 |
| Poloha: presná parcela / k. ú. / obec / bez polohy | 317 / 209 / 8 / 26 |
| Záznamy v histórii zmien | 609 |

Exekučné dražby pochádzajú z dražobných vyhlášok v OV (SKE zakazuje robotov, pozri BLOCKERS).

## Dôležité: nočný beh na GitHube

Kataster ÚGKK a notar.sk z GitHub Actions (USA) nefungujú. Nočný beh preto:
- Obchodný vestník sťahuje normálne (hlavný zdroj),
- polohu berie z pribalených tabuliek (stred k. ú.; presná parcela, ak už bola nájdená),
- NCRD po niekoľkých prázdnych stránkach preskočí.
Presnejšie polohy a NCRD sa dajú doplniť lokálnym behom na Macu (`drazby ncrd`, `drazby geocode`).

## Prekážky

Pozri [BLOCKERS.md](BLOCKERS.md). Najdôležitejšie: SKE zakazuje roboty (riešené cez OV), NCRD obmedzuje
rýchlosť, Nominatim zakazuje roboty (poloha len z katastra), parcely registra E nemajú tvar.

## Kde to beží

- Web: **https://drazby-app.vercel.app** (Vercel, tím MADEROVCI, koreňový priečinok `web`)
- Kód: **https://github.com/matus1423/drazby-app** (verejné repo; história vývoja je v súkromnom
  `matus1423/drazby-app-archiv`, lebo pôvodné vzorky obsahovali osobné údaje)
- Nočný zber: GitHub Actions „Denný zber dražieb“ každú noc o 2:00 → commit dát → Vercel nasadí.

## Ako to spustím na počítači

```bash
cd ~/Projekty/drazby-app
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e '.[dev]'
.venv/bin/python -m drazby daily
cd web && npm install && npm run dev
```

## Čo treba spraviť ručne (nepovinné)

1. **E-mailové upozornenia**: v GitHub → Settings → Secrets doplniť `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`,
   `SMTP_PASSWORD`, `SMTP_FROM` a premennú `SITE_URL`. Uložené hľadania sa zatiaľ pridávajú príkazom
   `drazby search-add` (formulár na webe potrebuje databázu na serveri – napr. Supabase).
2. **Supabase**: založiť projekt, spustiť migráciu, doplniť secret `DATABASE_URL`.
3. **Oficiálny XML export OV** (registrácia poštou) – len ak by Datahub prestal fungovať.

## Nápady na ďalej

- Formulár „Upozorniť ma na nové dražby“ priamo na webe (cez Supabase).
- OCR pre naskenované listiny NCRD (dražby, ktoré sú len u notárov, nemajú cenu).
- Tvar parciel registra E (iný zdroj ako INSPIRE).
- Stabilnejšie kódy dražieb aj pri zmene prvého oznámenia.
