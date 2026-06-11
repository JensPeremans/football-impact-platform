# Football Impact Platform — PRODUCTIE

Dit is de ENIGE definitieve productieversie. Gebruik vanaf nu uitsluitend deze map.

## Starten
```
pip install -r requirements.txt
streamlit run app.py
```

## Standaard platform-admin
- Gebruiker: admin
- Wachtwoord: admin123
(Wijzig dit wachtwoord na de eerste login.)

## Rollen
- platform_admin : beheert alle clubs (Club Management → platform-overzicht + clubselector)
- club_admin     : beheert eigen club (teams + gebruikers)
- analyst / coach : data + dashboards binnen toegewezen teams

## Limieten (per club)
- Max. 3 teams
- Max. 3 gebruikers (club_admin telt mee)

## Bestanden
app.py, database.py, impact_engine.py, metrics.py, ui.py, pdf_parser.py,
physical_parser.py, utils.py, requirements.txt, football_impact.db,
.streamlit/config.toml, .streamlit/credentials.toml

## Recente features

### Visuele upgrade (UI/UX)
- **Dark theme** — professionele donkere uitstraling (`.streamlit/config.toml` + globale CSS via `ui.py`).
- **Nieuwe navigatie** — 6 logische groepen in de zijbalk (Dashboard, Spelers, Wedstrijden, Fysiek, Profielen, Beheer) met rol-gebaseerde zichtbaarheid.
- **Dashboard als startscherm** — cluboverzicht met KPI-kaarten, trial-status, snelle acties en recente wedstrijden.
- **Club branding** — instelbare `primary_color` per club (Club Management → kleurkiezer); kleur wordt doorgevoerd in thema en grafieken.
- **Card-based layouts** — consistente kaarten, hero-metric voor de Impact Score, badges en empty states.
- **Professionele grafieken** — alle Plotly-charts in dark theme met clubkleur-accent.
- **Component library** (`ui.py`) — herbruikbare componenten: `page_header`, `kpi_cards`, `hero_metric`, `empty_state`, `balance_bar`, `category_cards`, `badge`.

### Granulaire metric-level weging
- Per-metric gewichten (step 0.5, bereik 0–10) per veldpositie in de Profile Editor.
- **Profile Balance** (6 categorieën incl. Physical, validatie 35–40, target 37.5) met live feedback.
- Duaal scoringsmodel: **Impact Score** (5 technische categorieën, ná 35%-cap) en **Impact Score+** (= Impact Score + Physical Contribution, enkel bij beschikbare fysieke data).
- Keepers gebruiken het bestaande categorie-niveau model.
