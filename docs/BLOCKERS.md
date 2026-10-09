# Prekážky a dočasné riešenia

| # | Čo | Dopad | Dočasné riešenie | Čo treba spraviť |
|---|---|---|---|---|
| B1 | **ske.sk zakazuje roboty** (`robots.txt: Disallow: /`) | nemôžeme sťahovať zoznam exekučných dražieb priamo od SKE | exekučné dražobné vyhlášky berieme z Obchodného vestníka (tie isté podania) | nič; prípadne požiadať SKE o export dát |
| B2 | **Stará adresa NCRD** (`…/Dobrovoľnédražby.aspx`) vracia 502 | — | web notar.sk je nový (WordPress), používame `https://www.notar.sk/drazby/` | nič |
| B3 | **NCRD vracia max. 20 výsledkov** bez stránkovania | časť záznamov by mohla chýbať | dopyty po dňoch, pri 20 aj podľa typu úkonu; ak by aj tak bolo ≥ 20, zapíše sa varovanie do logu | nič |
| B4 | **PDF listiny NCRD sú väčšinou skeny** | cena a popis predmetu z NCRD sa nedajú prečítať | údaje berieme z OV; z PDF len ak má textovú vrstvu | voliteľne OCR (`tesseract-ocr-slk`) |
| B5 | **Parcely registra E nie sú v INSPIRE WFS** | pre pozemky „E“ nevieme presný polygón | poloha = stred katastrálneho územia | prípadne preskúmať ZBGIS/ESKN pre register E |
| B6 | **Supabase prístupy nie sú nastavené** | dáta sú v lokálnom SQLite | SQLite + statický JSON; migrácie a `pgsync` sú pripravené | doplniť `DATABASE_URL` (secrets) a spustiť migráciu |
| B7 | **Vercel projekt nie je založený** | appka nie je verejne dostupná | beží lokálne (`npm run dev`) | založiť projekt na Verceli (Root Directory = `web`) |
| B8 | **Oficiálny XML export OV (MS SR)** vyžaduje registráciu poštou | — | Datahub poskytuje to isté XML | nepovinné; ak Datahub prestane fungovať, vybaviť registráciu |
| B9 | **Homebrew Python 3.12 na tomto Macu nefunguje** (pyexpat vs. systémová libexpat) | pip/venv padal | `uv` so samostatným Pythonom 3.12 | nič |
| B10 | **Datahub občas zavrie spojenie** | jednotlivé dopyty zlyhajú | retry s exponenciálnym čakaním | nič |
| B11 | **Nominatim (OpenStreetMap) zakazuje roboty** v `robots.txt` pre `/search` | nevieme geokódovať adresy/obce mimo katastra | poloha z katastra (parcela alebo k. ú.); obec sa hľadá ako k. ú. | prípadne vlastný zoznam obcí so súradnicami (napr. z registra adries) |
| B12 | **notar.sk pri rýchlejších dopytoch vracia 503** | beh NCRD sa spomalí | pauza 3 s + opakovanie s čakaním | nič |
| B13 | **Plocha (Desktop) sa odpojila od iCloudu** a súbory z nej postupne mizli (8. 10. 2026 okolo 12:54) | rozpracované súbory zmizli | projekt presunutý do `~/Projekty/drazby-app`, všetko je na GitHube | skontrolovať v iCloud Drive priečinok „Plocha“; Gophi a ostatné projekty sú na GitHube |
| B14 | **Z GitHub Actions (servery v USA) neodpovedá kataster ÚGKK a notar.sk vracia prázdne stránky** | prvý nočný beh vyčerpal 2 h čakaním | pribalená tabuľka stredov všetkých 3 559 k. ú. (`scrapers/drazby/data/ku.json`) a už nájdených parciel (`parcels.json`); „istič“ – po 3 výpadkoch katastra / 5 prázdnych stránkach NCRD sa služba v tom behu vynechá; limit 25 min na krok | nové dražby z nočného behu majú polohu podľa k. ú.; presnú parcelu doplní lokálny `drazby geocode` (zo Slovenska), tabuľky sa obnovia `scrapers/tools/build_ku_table.py` |
