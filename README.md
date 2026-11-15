# WAUG 2026 Results Dashboard

A Streamlit dashboard for the 15th West African University Games (WAUG 2026), hosted by Obafemi Awolowo University, Ile-Ife, 2–12 October 2026.

## Pages
- **Home**: overview of the Games, results at a glance, sports, participating countries and gallery.
- **Results Dashboard**: medal table, sports breakdown, top athletes, event results, event winners (gold, silver and bronze names for every event) and match scorelines.
- **About**: the organisers, data sources and methodology, credits.

## Data
Live from the AlliSports Data API (data.allimediahub.com): medal table, results (with winners), matches with live scores, and group tables.
Data: AlliSports Data. Results marked provisional are not yet confirmed by the WAUG Technical Committee.

If the API cannot be reached the app falls back to the saved snapshot in `data/` and says so on the page.
Football and basketball matches come from the live feed; other sports use the snapshot in `data/matches.csv` (5–11 Oct 2026).

### API key (keep it secret)
The key is read from `ALLISPORTS_KEY`. It is **never** written in the code and **must not** be committed to GitHub.

- **Locally:** copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and put your key in it (that file is git-ignored).
- **Streamlit Community Cloud:** app settings → *Secrets* → `ALLISPORTS_KEY = "asd_..."`.
- Or set an environment variable: `export ALLISPORTS_KEY=asd_...`

Limits: 60 requests/min and 10,000/day per key. Responses are cached (60 s for results, 30 s for matches), so a handful of requests per minute is typical. Use the **Refresh data** button to reload sooner.

## Run locally
```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

## Project structure
```
app.py                  # the whole app (Home, Results Dashboard, About)
requirements.txt
.streamlit/config.toml  # theme
data/
  medal_table.csv       # snapshot (fallback) ranked medal table
  medal_details.csv     # every medal: university, sport, event, athlete
  event_results.csv     # winning universities per event
  event_winners.csv     # gold / silver / bronze names per event
  matches.csv           # snapshot: 145 match scorelines, 5–11 Oct 2026 (used for sports the API does not carry)
prep_data.py            # builds medal_table.csv and medal_details.csv from the medal-table document
prep_winners.py         # builds event_winners.csv
prep_matches.py         # match data transcribed from the AlliSports Data results
```
`app.py` finds the snapshot CSVs in `data/` or next to itself.

## Data

## Credits
Designed and built by Adelerin Samuel.
