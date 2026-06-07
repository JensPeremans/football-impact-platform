# Testrapport — Universele Physical / GPS Data Pijplijn

**Datum:** 7 juni 2026
**Module:** fysieke tracking-data (Catapult CSV + wedstrijd-XLSX)
**Belangrijk uitgangspunt:** deze pijplijn staat **volledig los** van de bestaande
impact-/SciSports-data. Er worden (nog) **geen benchmarks** berekend — enkel
uploaden, parsen, opslaan en visualiseren.

---

## 1. Wat is er gebouwd?

| Stap | Bestand | Status |
|------|---------|--------|
| STAP 1 — Universele parser | `physical_parser.py` (nieuw) | ✅ Klaar & getest |
| STAP 2 — Database-uitbreiding | `database.py` (aangepast) | ✅ Klaar & getest |
| STAP 3 — Dashboard-scherm | `app.py` (aangepast) | ✅ Klaar & getest |
| STAP 4 — Test met 4 bestanden | dit rapport | ✅ Klaar |

### STAP 1 — `physical_parser.py`
- **Aliassen-mapping** voor 28 velden: elke metriek heeft een lijst mogelijke
  bronkoppen (bv. `top_speed` ← "Top Speed", "Max Speed", "Maximum Speed").
- **Bestandstype-detectie** (`detect_file_type`): `catapult_csv` vs `game_xlsx`
  vs `unknown`, op basis van herkende kolommen + extensie.
- **Kolom-mapping-engine** (`map_columns`): hoofdletter-ongevoelig, koppelt
  bronkolommen aan de canonieke velden.
- **Normalisatie**:
  - snelheden → **km/u** (m/s × 3,6; reeds-km/u blijft km/u);
  - EDI → **percentage 0–100** (ratio ≤ 1,5 × 100);
  - spelersnamen → **Title Case** (met behoud van `D'Haene`, koppeltekens).
- `parse_physical_file()` → `(DataFrame, rapport)`; DataFrame bevat altijd alle
  standaardvelden + `data_source` + `raw_data`.
- `validate_and_warn()` → rapport met gevonden/ontbrekende metrieken + waarschuwingen.

### STAP 2 — `database.py`
- Nieuwe tabel **`physical_data`** (22 metriek-kolommen + context + `raw_data`),
  met `UNIQUE(player_name, session_name, period, data_source)` zodat
  her-importeren **idempotent** is.
- Optionele koppeling aan bestaande spelers (`player_id`, exacte naam) en
  wedstrijden (`match_id`); fysieke data mag ook **standalone** bestaan.
- CRUD: `save_physical_data`, `get_physical_data`, `list_physical_sessions`,
  `list_physical_players`, `get_player_physical_summary`,
  `physical_summary_counts`, `delete_physical_session`.

### STAP 3 — `app.py`
- Nieuw scherm **🏃 Physical / GPS** in de navigatie (de 7 bestaande schermen
  blijven ongewijzigd).
- Upload (.csv/.xlsx) → automatische herkenning → voorbeeldtabel +
  waarschuwingen → optioneel koppelen aan wedstrijd → opslaan.
- Visualisatie: filters (sessie / speler / periode), 4 KPI-kaarten,
  samenvattende tabel per speler, staafdiagram (afstandsverdeling) en
  spreidingsdiagram (topsnelheid vs. versnellingen). Plus sessiebeheer (verwijderen).

---

## 2. Testresultaten — 4 bronbestanden

Alle 4 aangeleverde bestanden zijn succesvol verwerkt en opgeslagen:

| Bestand | Type | Rijen | Spelers | Periodes |
|---------|------|-------|---------|----------|
| Game Essevee - Club Brugge 25 Oktober 2025 (...).xlsx | `game_xlsx` | 11 | 11 | Full Match |
| Single-Session Match Periods Report 01 Mar 26.csv | `catapult_csv` | 28 | 14 | First/Second Half |
| Single-Session Match Periods Report 28 Mar 26.csv | `catapult_csv` | 28 | 14 | First/Second Half |
| Single-Session Match Periods Report 19 Apr 26.csv | `catapult_csv` | 28 | 14 | First/Second Half |

**Database na import:** 95 records · 4 sessies · 27 unieke spelers.

### Verificaties
| Controle | Resultaat |
|----------|-----------|
| Snelheden in km/u | ✅ XLSX 27,62 → 27,62 km/u; CSV 8,0 m/s → 28,8 km/u |
| EDI → percentage | ✅ 0,16 → 16,0 % |
| Namen in Title Case | ✅ "Loris D'HAENE" → "Loris D'Haene" |
| Ontbrekende metrieken | ✅ worden `NULL` + waarschuwing in rapport |
| Idempotente her-import | ✅ blijft 95 records bij opnieuw inladen |
| Database gevuld | ✅ 95 rijen via `save_physical_data` |
| Dashboard rendert | ✅ scherm + alle filters zonder fouten (Streamlit AppTest) |
| Datum uit bestandsnaam | ✅ "25 Oktober 2025" → 2025-10-25; "01 Mar 26" → 2026-03-01 |

### Dashboard-rendering (AppTest, echte database)
- Kopstatistieken: Records 95 · Sessies 4 · Spelers 27.
- Geaggregeerde KPI's (alle data): totale afstand 394.486 m · sprintafstand
  3.396 m · topsnelheid 34,1 km/u · 2.491 versnellingen.
- Filtercombinaties (alle / per sessie / per speler / per periode) renderen
  foutloos; lege selecties tonen een nette melding.

---

## 3. Belangrijke ontwerpkeuzes
- **Geen automatische spelers-aanmaak**: fysieke namen worden alleen gekoppeld
  als de speler al bestaat (exacte naam), anders `player_id = NULL`. Zo blijven
  de twee pijplijnen strikt gescheiden.
- **`top_speed` = km/u** (canonieke weergave-eenheid); ruwe m/s blijft bewaard
  in `top_speed_ms`.
- **Geen `sessions`-tabel** nodig: de bestaande `matches`-tabel kan optioneel
  als sessie dienen; koppeling is niet verplicht.

---

## 4. Geleverde bestanden
- `physical_parser.py` (nieuw)
- `database.py` (uitgebreid met `physical_data` + CRUD)
- `app.py` (nieuw scherm 🏃 Physical / GPS)
- `PHYSICAL_PIPELINE_TESTRAPPORT.md` (dit rapport)

Alles is vastgelegd in git (commit "Add physical/GPS tracking pipeline ...").
