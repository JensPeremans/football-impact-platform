# ⚽ Football Impact Data Platform (MVP)

Turn SciSports **Match Analysis (Player Version)** PDF reports into actionable
coaching insights. Upload PDFs → get instant player impact scores, rankings,
comparisons and evolution trends, all weighted by configurable playing styles.

## Features

- **Robust PDF parser** (`pdfplumber`) handling **two SciSports formats**:
  - *Version A* (older): `Forward Passes`, `Box Penetrations`, `Total xGoals`, decimal minutes, dashes for nulls.
  - *Version B* (newer): `Direct Passes`, `Box Receptions`, `Final 3rd Receptions`, `Forward Dribbles`, conditional `xG`.
  - Statistics normalised into canonical `metric_key`s, GK vs field players handled, season auto-derived from match date.
- **Impact Engine**: Total Impact, Impact/90, Impact/Action, Offensive & Defensive Efficiency, and 6 category impacts.
- **6 Impact categories** (Framework v1.0): Passing, Progression, Chance Creation, Finishing, Defending, Goalkeeping.
- **4 pre-configured playing-style profiles** with realistic weights: Possession Football, Direct Football, High Pressing, Chance Creation Focus.
- **6 Streamlit screens**: Upload & Overview, Match Dashboard, Player Profile, Player Comparison, Evolution Dashboard, Profile Editor.
- **Interactive Plotly visuals**: radar charts, line/area evolution charts, comparison bars, conditionally formatted tables.
- **SQLite** with foreign keys + indexes, multi-club ready schema.

## Project structure

| File | Purpose |
|------|---------|
| `app.py` | Streamlit UI (6 screens) |
| `database.py` | SQLite schema, init/seed, query helpers |
| `pdf_parser.py` | Two-version SciSports PDF parser |
| `impact_engine.py` | Impact score calculations |
| `metrics.py` | Metric catalog, categories, default profile weights |
| `utils.py` | Formatting + Plotly chart helpers |

## Setup & run

```bash
pip install -r requirements.txt
streamlit run app.py
```

The database (`football_impact.db`) and the 4 default profiles are created
automatically on first launch. Upload the SciSports PDFs on the first screen.

## Database schema

`clubs → style_profiles → metric_weights`, and
`teams → matches → player_match_stats → stat_values`, with `players` shared
across matches. Stats are stored as `(metric_key, value)` rows so new metrics
require no schema change.

## Notes
- Re-uploading the same match replaces its data (idempotent).
- The MVP runs single-club but the schema supports multiple clubs/profiles.
