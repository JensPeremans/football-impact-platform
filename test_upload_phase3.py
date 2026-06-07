"""FASE 3 — handmatige testinstructies voor de upload workflow.

Run: python test_upload_phase3.py  (print alleen instructies + verificatie-SQL)
"""

print(r"""
=== FASE 3 UPLOAD WORKFLOW — HANDMATIGE TESTS ===

Start de app:  streamlit run app.py
Ga naar:       🏃 Physical / GPS

TEST 1 — WEDSTRIJD-UPLOAD
-------------------------
1. Upload een XLSX/CSV met een datum die overeenkomt met een wedstrijd
   (bv. "Game Essevee - Club Brugge 25 Oktober 2025 ...xlsx" → 2025-10-25).
2. Kies: 🏆 Wedstrijd
3. Selecteer de voorgestelde wedstrijd uit de lijst.
4. Controleer het bevestigingsscherm (type, match-id, spelers, rijen, periodes).
5. Klik "💾 Fysieke data opslaan" → success-melding.
VERWACHT: session_type='match', match_id gevuld, session_name = wedstrijdlabel.

TEST 2 — TRAINING-UPLOAD
------------------------
1. Upload een CSV.
2. Kies: 🏃 Training, vul naam in (bv. "Training 19 April 2026").
3. Bevestig en sla op.
VERWACHT: session_type='training', match_id=NULL, session_name = ingevulde naam.

TEST 3 — ONGELINKTE UPLOAD
--------------------------
1. Upload een CSV.
2. Kies: 📂 Ongelinkt.
3. Bevestig en sla op.
VERWACHT: session_type='unlinked', match_id=NULL.

TEST 4 — WEDSTRIJD ZONDER MATCH
-------------------------------
1. Upload bestand met datum zonder bijbehorende wedstrijd.
2. Kies: 🏆 Wedstrijd → app meldt "geen wedstrijden gevonden" en valt
   automatisch terug op 📂 Ongelinkt.
VERWACHT: session_type='unlinked'.

TEST 5 — BESTAANDE DATA INTACT
------------------------------
1. Scroll naar Visualisatie + Sessiebeheer.
VERWACHT: bestaande 95 records / 4 sessies nog steeds zichtbaar.

=== DATABASE-VERIFICATIE (Python sqlite3) ===

import sqlite3
con = sqlite3.connect("football_impact.db"); con.row_factory = sqlite3.Row

# Per type
for r in con.execute("SELECT session_type, COUNT(*) n FROM physical_data "
                     "GROUP BY session_type"):
    print(dict(r))

# Wedstrijd-gekoppeld
for r in con.execute("SELECT match_id, session_name, COUNT(*) n FROM physical_data "
                     "WHERE session_type='match' GROUP BY match_id, session_name"):
    print(dict(r))

# Training
for r in con.execute("SELECT session_name, COUNT(*) n FROM physical_data "
                     "WHERE session_type='training' GROUP BY session_name"):
    print(dict(r))
""")
