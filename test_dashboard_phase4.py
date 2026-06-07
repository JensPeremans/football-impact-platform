"""FASE 4 — handmatige testinstructies voor het Physical Dashboard."""

print(r"""
=== FASE 4 DASHBOARD VISUALISATIE — HANDMATIGE TESTS ===

Start: streamlit run app.py  →  ga naar 🏃 Physical / GPS

TEST 1 — TYPE FILTERS
  Wijzig de multiselect "Filter op type sessie" en controleer dat alleen
  sessies van de gekozen types (🏆/🏃/📂) verschijnen in de sessieselector
  én in het sessiebeheer.            VERWACHT: ✅ filter werkt

TEST 2 — SESSIE-LABELS MET ICONEN
  🏆 = wedstrijd, 🏃 = training, 📂 = ongelinkt in de selectbox en de
  sessiebeheer-expanders.            VERWACHT: ✅ juiste iconen

TEST 3 — VERDELING
  De caption "Verdeling: 🏆 x · 🏃 y · 📂 z" klopt met de database.

TEST 4 — KOPPELEN (ongelinkt/training → wedstrijd)
  Open een 📂/🏃 sessie in Sessiebeheer → "🔗 Koppel aan wedstrijd" →
  kies een wedstrijd → "✅ Koppelen". Sessie wordt 🏆, match_id gevuld.

TEST 5 — ONTKOPPELEN (wedstrijd → ongelinkt)
  Open een 🏆 sessie → "🔓 Ontkoppel". Sessie wordt 📂, match_id NULL.

TEST 6 — VERWIJDEREN
  Open sessie → "🗑️ Verwijder" → "✅ Ja, verwijderen". Records weg.
  "❌ Annuleer" laat de sessie staan.

TEST 7 — METRICS PER SELECTIE
  Kies een losse sessie of laat "Alle sessies (gefilterd)" staan; de KPI's,
  spelertabel en grafieken volgen de selectie/filter.

TEST 8 — MATCH DASHBOARD GPS-INDICATOR
  Ga naar 📊 Match Dashboard → kies een wedstrijd.
  Met gekoppelde GPS-data: "✅ GPS-data beschikbaar ...".
  Zonder: "ℹ️ Nog geen GPS-data gekoppeld ...".

TEST 9 — BESTAANDE DATA INTACT
  Oude physical data, PDF-import, impactscores en alle dashboards laden nog.

TEST 10 — MATCH/TRAINING SCHEIDING
  Filter op alleen 🏆 vs alleen 🏃 → metrics mengen niet automatisch.

=== DATABASE-VERIFICATIE (Python sqlite3) ===
import sqlite3
con = sqlite3.connect("football_impact.db"); con.row_factory = sqlite3.Row
for r in con.execute("SELECT session_type, COUNT(*) n FROM physical_data "
                     "GROUP BY session_type"):
    print(dict(r))
""")
