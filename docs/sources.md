# Zdroje dát — výsledok prieskumu (Fáza 0, 8. 10. 2026)

Všetko overené priamo proti weboch dňa 2026-10-08.

## Súhrn a priorita

| # | Zdroj | Stav | Formát | Priorita |
|---|---|---|---|---|
| 1 | **Obchodný vestník cez Slovensko.Digital Datahub** | ✅ funguje | štruktúrované XML | **hlavný zdroj** |
| 2 | **NCRD (notar.sk)** | ✅ funguje | HTML + PDF (väčšinou skeny) | doplnkový, na kontrolu a deduplikáciu |
| 3 | SKE (ske.sk) | ⛔ zakázané robots.txt | HTML | **nesťahujeme** — dáta sú v OV |
| 4 | Daňové dražby | ✅ sú v OV (`OV_DRAZBA_SPRAVCA_DANE_*`) | XML | cez zdroj 1 |
| 5 | Konkurzné predaje | v OV ako ponukové konania správcov | XML | zatiaľ nie (sekundárne) |
| 6 | Kataster (ÚGKK INSPIRE / ZBGIS) | pozri `docs/geocoding.md` | WFS | obohatenie |

**Odporúčanie:** OV cez Datahub je jasne najlepší zdroj — obsahuje dobrovoľné
dražby (rovnaké ako NCRD), exekučné dražobné vyhlášky (rovnaké ako SKE) aj
daňové dražby, a to ako štruktúrované XML. Exekučné vyhlášky majú dokonca
kódy kraja/okresu/obce, k. ú., LV, čísla parciel a znaleckú cenu v samostatných
poliach. NCRD slúži na overenie úplnosti a ako záloha.

---

## 1. Obchodný vestník — Slovensko.Digital Datahub

- Endpoint: `https://datahub.ekosystem.slovensko.digital/api/data/ov/raw_issues/sync?since=<ISO čas>`
- Bez registrácie. Limit **60 požiadaviek/min na IP** (hlavička `x-ratelimit-*`).
- Stránkovanie cez hlavičku `Link: <...?last_id=…&since=…>; rel='next'`, 100 záznamov na stránku.
- Položka: `id, file_name, content (pôvodné XML), created_at, updated_at, bulletin_issue{year, number, published_at}`.
- `robots.txt` nič nezakazuje.
- Občas server zavrie spojenie (`RemoteProtocolError`) → retry s backoffom pomáha.
- Objem: ~800 podaní OV denne, z toho dražby ~5–10 denne.

### Typy podaní s dražbami (podľa `file_name`)

| file_name (bez prefixu a verzie) | Čo to je |
|---|---|
| `OV_DRAZBA_OZNAMENIE_DOBROVOLNA` | oznámenie o dobrovoľnej dražbe |
| `OV_DRAZBA_OZNAMENIE_DOBROVOLNA_OPAKOVANA` | opakovaná dobrovoľná dražba |
| `OV_DRAZBA_OZNAMENIE_DOBROVOLNA_DODATOK` | zmena / dodatok |
| `OV_DRAZBA_OZNAMENIE_DOBROVOLNA_UPUSTENIE` | upustenie od dražby (zrušená) |
| `OV_DRAZBA_OZNAMENIE_DOBROVOLNA_ZMARENIE` | zmarenie dražby |
| `OV_DRAZBA_OZNAMENIE_DOBROVOLNA_VYSLEDOK` | výsledok dražby (prebehla) |
| `OV_DRAZBA_OZNAMENIE_DOBROVOLNA_OPAKOVANA_VYSLEDOK` | výsledok opakovanej |
| `…MSSR_OV_Drazobna_vyhlaska` | exekučná dražobná vyhláška (formulár ÚPVS, namespace `http://schemas.gov.sk/form/00166073.MSSR_OV_Drazobna_vyhlaska/1.5`) |
| `OV_DRAZBA_SPRAVCA_DANE_*` | daňová dražba (správca dane) |

### Polia — dobrovoľná dražba (`<Drazba>`)
`Cislo` (číslo dražby, napr. `028/2026`), `Drazobnik/ObchodneMenoNazov`, `Drazobnik/Ico`,
`Navrhovatelia/…`, `Notar`, `KonanieMiesto`, `KonanieDatum`, `KonanieCas`, `Kolo`,
`Predmet` (HTML, dvojito escapované — k. ú., LV, parcely, súpisné č. sú vo voľnom texte),
`PredmetOpis` (HTML), `PredmetCenaSposobStanovenia`, `NajnizsiePodanie`
(text typu `78.200,- EUR (slovom: …)`), `MinimalnePrihodenie`, `Zabezpeka/Vyska`,
`ObhliadkaDatum`, `ObhliadkaMiesto`, `NajvyssiePodanie` (vo výsledku), `DovodUpustenia`.

### Polia — exekučná dražobná vyhláška (`<e:AuctionDecree>`)
`TypeOfProperty` (RealEstate/…), `DeclarationDate`, `NumberOfExecution` (napr. `278EX 150/22-371`),
`Order` (kolo: prvá/opakovaná), `ExecutorOffice/PersonData/Name`, `Date`, `Time`, `Place`,
`RealEstate/Item/{Region, County, Municipality}` **s kódmi** (`SK032`, `SK032B`, `SK032B518158`),
`CadastralUnit`, `FolioNumber` (LV), `Fields/{PlotType, PlotNumber, PlotSize, KindOfPlot}`,
`ValueOfPropertyDeterminedByExpert`, `Guarantee/AmountOfSecurity`, `Owner` (meno povinného —
**neukladáme**, pozri DECISIONS).

### Odkaz na pôvodný zdroj
Datahub `id` nie je to isté ako `IdFormular` na webe OV, takže priamy odkaz na detail
na obchodnyvestnik.justice.gov.sk nevieme zostaviť. Ukladáme číslo vestníka a označenie
podania (napr. `OV 188/2026, X059085`) a odkaz na vyhľadávanie OV.

### Oficiálne XML z MS SR
Vyžaduje registráciu (poštou) a rolu „Export/Stiahnutie Xml podaní“, časové okno
pracovné dni 19:00–7:00 a víkendy. Datahub nám zatiaľ stačí — rovnaké XML.

---

## 2. NCRD — Notársky centrálny register dražieb

- Stará adresa `…/Dobrovoľnédražby.aspx` vracia **502** — web notar.sk je prerobený na WordPress.
- Nová adresa: **`https://www.notar.sk/drazby/`** — obyčajný GET formulár, **žiadny ViewState, Playwright netreba**.
- `robots.txt`: `Allow: /` (zakazuje len wp-admin a pluginy). Stránka má `noindex` (len pre vyhľadávače).
- Parametre: `actNumber1`, `actNumber2` (číslo/rok), `auctioneerName`, `auctioneerIdentifier` (IČO),
  `subjectCity` + `subjectRegionCode/DistrictCode/MunicipalityCode`, `AuctionActType`
  (`NEW_AUCTION`, `AUCTION_CHANGE_OR_ADDITION`, `AUCTION_RENOUNCEMENT`, `AUCTION_DEFEAT`,
  `AUCTION_INVALID`, `REPEATED_AUCTION`, `AUCTION_RESULT`), `auctionDateFrom`, `auctionDateTo` (YYYY-MM-DD),
  `venueCity…`, `auction-search=Hľadať`.
- **Výsledok je orezaný na 20 riadkov, bez stránkovania.** Riešenie: pýtať sa po jednotlivých dňoch
  (bežne 0–8 dražieb za deň); ak deň vráti 20, rozdeliť ešte podľa `AuctionActType`.
- Riadok výsledku: spisová zn. NCRdr (`1167/2026`), dražobník + IČO, navrhovateľ + IČO, typ úkonu,
  odkaz na pôvodné oznámenie (pri opakovaných/zmenách), dátum dražby. Odkaz `drazba?actId=<24 hex>`.
- Detail `https://www.notar.sk/drazba?actId=…`: notár, spisová zn., dátum zápisu, typ úkonu, dražobník (IČO, adresa),
  navrhovatelia, miesto konania (adresa), dátum a čas otvorenia, druh predmetu („Nehnuteľná vec“),
  súvisiace spisové značky, uverejnené listiny.
- **Limit:** pri dopytoch každých 1,5 s server po čase vracia `503` a potom `Retry-After: 3600` (hodinová
  prestávka). Preto: pauza 5 s, bez sťahovania PDF, a pri dlhom `Retry-After` beh skončí a pokračuje
  nabudúce (už spracované úkony sa nesťahujú znova).
- Listina (PDF): `https://www.notar.sk/listina/?actId=…&documentId=…&filename=….pdf`.
  **Väčšina PDF sú skeny bez textu** (5 z 8 vo vzorke) → cena a popis predmetu len cez OCR.
  Preto sa cena/predmet berie primárne z OV a NCRD sa páruje podľa čísla dražby + dražobníka + dátumu.

---

## 3. SKE — Slovenská komora exekútorov

- `https://www.ske.sk/robots.txt` → `User-agent: * / Disallow: /` — **automatizovaný prístup je zakázaný.**
- Zoznam `https://www.ske.sk/drazobne-vyhlasky/` odkazuje na `drazobna-vyhlaska-detail/?ov_podanie_id=…`
  — sú to teda **kópie podaní z Obchodného vestníka**, ktoré už máme cez Datahub.
- Rozhodnutie: SKE nesťahujeme (pozri `DECISIONS.md`, `BLOCKERS.md`).

---

## 4. Daňové dražby a konkurzy

- Daňové dražby: v OV ako `OV_DRAZBA_SPRAVCA_DANE_*` → spracúvame cez Datahub.
- Finančná správa ich zverejňuje aj na financnasprava.sk (úradná tabuľa) — netreba, OV stačí.
- Konkurzné predaje (ponukové konania správcov): v OV, oddiel Konkurzy a reštrukturalizácie,
  ako voľný text. Nie sú to dražby v pravom zmysle — zatiaľ nespracúvame.

## 5. Kataster

Pozri [`geocoding.md`](geocoding.md) – INSPIRE WFS ÚGKK funguje pre parcely registra C (bod aj polygón)
a pre katastrálne územia.

## 6. Datahub – stiahnutie jedného podania

`https://datahub.ekosystem.slovensko.digital/api/data/ov/raw_issues/<id>` vráti jedno podanie (rovnaký formát ako sync).
Používa sa pri `drazby reparse` a pri ukladaní nových testovacích vzoriek.
