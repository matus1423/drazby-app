# Geokódovanie (poloha na mape)

Overené 8. 10. 2026.

## Kataster ÚGKK – INSPIRE WFS (používame)

- Služba: `https://inspirews.skgeodesy.sk/geoserver/cp/ows` (WFS 1.1.0/2.0.0, GeoJSON výstup, bez kľúča).
- Vrstvy:
  - `cp:CP.CadastralZoning` – katastrálne územia (~3 500). Atribúty `label` (názov), `nationalCadastalZoningReference`
    (6-miestny kód k. ú., napr. Zvolen = `873705`), polygón hranice.
  - `cp:CP.CadastralParcel` – parcely registra **C**. Atribút `nationalCadastralReference` = `<kód k. ú.>_<číslo>.C`
    (napr. `842320_9238.C`), `referencePoint` (bod vnútri parcely), polygón, výmera.
- Filter sa posiela ako OGC XML v parametri `filter` (WFS 1.1.0), napr.
  `<Filter><PropertyIsEqualTo><PropertyName>nationalCadastralReference</PropertyName><Literal>842320_9238.C</Literal></PropertyIsEqualTo></Filter>`.
  Pri názve k. ú. sa skúša presná zhoda, potom `PropertyIsLike matchCase="false"`.
- **Parcely registra E** (pôvodný stav, „UO“) v službe nie sú → poloha = stred k. ú.
- Súradnice sú ETRS89 (EPSG:4258), pre mapu prakticky totožné s WGS84.

## Postup (scrapers/drazby/geocode.py)

1. k. ú. z oznámenia → kód k. ú. (cache `ku:<názov>`).
2. až 6 parciel registra C → body a polygóny (cache `parcel:<ref>`); bod = `referencePoint` prvej nájdenej.
3. ak parcela nie je → stred k. ú. (`precision = ku`).
4. ak chýba k. ú. → k. ú. s rovnakým názvom ako obec (`precision = obec`).
5. Rovnaký názov k. ú. vo viacerých okresoch → vyberie sa ten najbližší k obci z oznámenia.

## Nominatim (nepoužívame)

`https://nominatim.openstreetmap.org/robots.txt` zakazuje robotom `/search`. Kód je pripravený
(`USE_NOMINATIM`), ale vypnutý. Ak by bolo treba geokódovať adresy, vhodnejší je vlastný zoznam
obcí so súradnicami alebo Register adries (RA) ministerstva vnútra.

## ZBGIS / Portál ESKN

Mapový klient ZBGIS a nový Portál ESKN nemajú zdokumentované verejné API na vyhľadanie parcely podľa čísla;
INSPIRE WFS poskytuje to isté pre register C, preto sme pri ňom ostali.
