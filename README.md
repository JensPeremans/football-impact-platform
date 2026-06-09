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
app.py, database.py, impact_engine.py, metrics.py, pdf_parser.py,
physical_parser.py, utils.py, requirements.txt, football_impact.db,
.streamlit/config.toml, .streamlit/credentials.toml
