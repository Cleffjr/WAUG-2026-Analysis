import os
from pathlib import Path

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

st.set_page_config(
     page_title="WAUG 2026|West African University Games,OAU Ile-Ife",
     page_icon="waug-2026-logo.png",
     layout="wide",
     initial_sidebar_state="expanded"
)

HERE = Path(__file__).resolve().parent
# Run from the folder that holds the CSVs: next to app.py, or inside a "data" subfolder
os.chdir(HERE)
if not Path("medal_table.csv").exists() and Path("data", "medal_table.csv").exists():
    os.chdir(HERE / "data")

GOLD, SILVER, BRONZE = "#D4AF37", "#A8A9AD", "#CD7F32"
MEDAL_COLORS = {"Gold": GOLD, "Silver": SILVER, "Bronze": BRONZE}
# ---------- data layer: AlliSports Data API (with a saved snapshot as fallback) ----------
API_BASE = os.environ.get("ALLISPORTS_BASE", "https://data.allimediahub.com").rstrip("/")
SERIES, EDITION = "waug", "2026"
GENDER = {"men": "Men", "women": "Women", "mixed": "Mixed"}
CATEGORY_OLD = {"Men": "Male", "Women": "Female", "Mixed": "Mixed", "Other": "Other"}
COUNTRY_NAMES = {"NG": "Nigeria", "GH": "Ghana"}
SPORT_CODES = {"FBL": "Football", "BKB": "Basketball"}
# only used for the saved snapshot, when the live feed cannot be reached
GHANA = {"University of Ghana", "University of Cape Coast", "Kwame Nkrumah University of Science and Technology",
         "University for Development Studies", "University of Energy and Natural Resources"}


class ApiNotFound(RuntimeError):
    pass


def api_key():
    """The key lives in .streamlit/secrets.toml (ALLISPORTS_KEY) or an environment variable, never in the code."""
    try:
        key = st.secrets["ALLISPORTS_KEY"]
    except Exception:
        key = None
    return key or os.environ.get("ALLISPORTS_KEY")


def api_get(path, **params):
    key = api_key()
    if not key:
        raise RuntimeError("no API key found: add ALLISPORTS_KEY to .streamlit/secrets.toml")
    r = requests.get(f"{API_BASE}/api/{SERIES}/{EDITION}/{path}", headers={"x-api-key": key}, timeout=20,
                     params={k: v for k, v in params.items() if v is not None})
    if r.status_code == 401:
        raise RuntimeError("the API key was rejected (401)")
    if r.status_code == 404:
        raise ApiNotFound(path)
    if r.status_code == 429:
        raise RuntimeError(f"rate limit reached, retry in {r.headers.get('Retry-After', '60')} seconds")
    r.raise_for_status()
    return r.json()


def from_api():
    mt = api_get("medal-table")
    rs = api_get("results")
    table = pd.DataFrame([{
        "rank": r["rank"], "university": r["university"]["name"], "abbr": r["university"]["code"],
        "gold": r["medals"]["gold"], "silver": r["medals"]["silver"], "bronze": r["medals"]["bronze"],
        "total": r["medals"]["total"], "provisional": r.get("provisionalMedals", 0),
        "country": COUNTRY_NAMES.get(r["university"].get("country"), r["university"].get("country") or "Other")}
        for r in mt["data"]["rows"]])
    det_rows, ev_rows = [], []
    for e in rs["data"]:
        res = e.get("result")
        if not res or not e.get("countsInMedals", True) or res.get("status") == "disputed":
            continue
        cat3 = GENDER.get(e.get("gender"), "Other")
        name = e["category"]
        label = f"{cat3} {name}" if cat3 != "Other" else name
        slots = {}
        for m in res.get("medals", []):
            slots[m["slot"]] = m["university"]["name"]
            athlete = m.get("athleteName") or ("Team" if e.get("kind") == "team" else "–")
            det_rows.append(dict(university=m["university"]["name"], abbr=m["university"]["code"], medal=m["colour"].capitalize(),
                                 sport=e["sport"]["name"], event=label, event_name=name, cat3=cat3, category=CATEGORY_OLD[cat3],
                                 athlete=athlete, status=res.get("status", "")))
        ev_rows.append({"Sport": e["sport"]["name"], "Event": name, "Category": CATEGORY_OLD[cat3], "Gold": slots.get("gold", ""),
                        "Silver": slots.get("silver", ""), "Bronze I": slots.get("bronze_1") or slots.get("bronze", ""),
                        "Bronze II": slots.get("bronze_2", ""), "Updated Timestamp": res.get("updatedAt", ""), "Status": res.get("status", "")})
    det = pd.DataFrame(det_rows)
    det["country"] = det.university.map(table.set_index("university").country).fillna("Other")
    meta = {"source": "api", "generatedAt": rs.get("generatedAt", ""), "includesProvisional": bool(rs.get("includesProvisional")), "error": None}
    return table, det, pd.DataFrame(ev_rows), meta


def from_csv(err):
    table = pd.read_csv("medal_table.csv")
    det = pd.read_csv("medal_details.csv")
    ev = pd.read_csv("event_results.csv", encoding="utf-8-sig")
    country = lambda u: "Ghana" if u in GHANA else "Nigeria"
    table["country"] = table.university.map(country)
    det["country"] = det.university.map(country)
    det["abbr"] = det.university.map(table.set_index("university").abbr)
    first = det.event.str.split().str[0]
    det["cat3"] = first.where(first.isin(["Men", "Women", "Mixed"]), "Other")
    det["category"] = det.cat3.map(CATEGORY_OLD)
    det["event_name"] = det.event.where(det.cat3 == "Other", det.event.str.split(n=1).str[1])
    ev["Status"] = "snapshot"
    return table, det, ev, {"source": "snapshot", "generatedAt": "", "includesProvisional": False, "error": err}


@st.cache_data(ttl=60, show_spinner="Loading data from AlliSports Data…")
def load():
    """Medal table, medals (with athletes) and events: live from the API, or from the saved snapshot if the API fails."""
    try:
        table, det, ev, meta = from_api()
    except Exception as err:
        try:
            table, det, ev, meta = from_csv(str(err))
        except Exception:
            raise RuntimeError(f"Could not load data from the API ({err}) and no saved snapshot was found.")
    det["medal"] = pd.Categorical(det.medal, ["Gold", "Silver", "Bronze"], ordered=True)
    return table, det, ev, meta


def build_winners(det):
    """One row per event with the gold, silver and bronze winners ('Name (UNI)')."""
    d = det.copy()
    d["medal"] = d.medal.astype(str)
    who = d.athlete.fillna("–").replace({"–": "Name not listed"})
    d["label"] = who + " (" + d.abbr + ")"
    return (d.groupby(["sport", "cat3", "event_name", "medal"])["label"].agg("; ".join).unstack("medal")
              .reindex(columns=["Gold", "Silver", "Bronze"]).fillna("").reset_index()
              .rename(columns={"cat3": "category", "event_name": "event", "Gold": "gold", "Silver": "silver", "Bronze": "bronze"}))


MATCH_COLS = ["date", "time", "sport", "category", "event_name", "stage", "team_a", "uni_a", "score_a", "team_b", "uni_b", "score_b",
              "sets", "pens_a", "pens_b", "winner", "status", "venue", "match_id", "event_id", "source"]


def from_api_matches():
    names = dict(SPORT_CODES)
    try:
        names.update({x["code"]: x["name"] for x in api_get("sports")["data"]})
    except Exception:
        pass
    resp = api_get("matches")
    rows = []
    for m in resp["data"]["matches"]:
        sport = names.get(m.get("sport"), m.get("sport"))
        evn = m.get("event") or ""
        cat = "Men" if evn.startswith("Men") else "Women" if evn.startswith("Women") else "Mixed"
        local = pd.to_datetime(m.get("startsAt"), utc=True, errors="coerce") + pd.Timedelta(hours=1)   # Nigeria time (WAT)
        sc = m.get("score") or m.get("awarded") or {}
        pen = m.get("penalties") or {}
        ps = m.get("periodScores") or []
        if ps:
            sets = " ".join(f"{p['period']} {p['home']}-{p['away']}" for p in ps)
        elif m.get("halfTime"):
            sets = f"HT {m['halfTime']['home']}-{m['halfTime']['away']}"
        else:
            sets = ""
        if m.get("extraTime"):
            sets = (sets + " · extra time").strip(" ·")
        rows.append(dict(
            date=local.tz_localize(None).normalize() if pd.notna(local) else pd.NaT,
            time=local.strftime("%H:%M") if pd.notna(local) else "", sport=sport, category=cat, event_name=evn,
            stage=m.get("phase") or "", team_a=m["home"]["name"], uni_a=m["home"]["code"], score_a=sc.get("home"),
            team_b=m["away"]["name"], uni_b=m["away"]["code"], score_b=sc.get("away"), sets=sets,
            pens_a=pen.get("home"), pens_b=pen.get("away"), winner={"home": "A", "away": "B"}.get(m.get("winner")),
            status=m.get("status", "scheduled"), venue=m.get("venue") or "", match_id=m.get("id"), event_id=m.get("eventId"), source="api"))
    df = pd.DataFrame(rows, columns=MATCH_COLS)
    return df, {"generatedAt": resp.get("generatedAt", ""), "includesProvisional": bool(resp.get("includesProvisional"))}


def read_snapshot_matches():
    if not Path("matches.csv").exists():
        return pd.DataFrame(columns=MATCH_COLS)
    m = pd.read_csv("matches.csv", dtype={"sets": str}).fillna({"sets": ""})
    m["date"] = pd.to_datetime(m.date)
    m["time"], m["status"], m["venue"] = "", "finished", ""
    m["match_id"], m["event_id"], m["source"] = None, None, "snapshot"
    m["event_name"] = m.category + "'s " + m.sport.str.lower()
    return m[MATCH_COLS]


@st.cache_data(ttl=30, show_spinner=False)
def load_matches():
    """Matches: live from the API (football and basketball). Sports the feed does not carry come from the saved snapshot."""
    meta = {"error": None, "generatedAt": "", "includesProvisional": False}
    api = None
    try:
        api, info = from_api_matches()
        meta.update(info)
    except Exception as err:
        meta["error"] = str(err)
    snap = read_snapshot_matches()
    if api is not None and not api.empty:
        snap = snap[~snap.sport.isin(api.sport.unique())]
    parts = [x for x in (api, snap) if x is not None and not x.empty]
    df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=MATCH_COLS)
    return df, meta


@st.cache_data(ttl=60, show_spinner=False)
def load_competition(event_id):
    return api_get(f"events/{event_id}/competition")


BASE = "https://waug.oauife.edu.ng/"
IMG = BASE + "images/"

SPORTS = [("🏃", "Athletics"), ("⚽", "Football"), ("🏀", "Basketball"), ("🏊", "Swimming"), ("🏐", "Volleyball"),
          ("🥊", "Boxing"), ("🏋", "Weightlifting"), ("🥋", "Judo"), ("🦵", "Taekwondo"), ("🏓", "Table Tennis"),
          ("🏸", "Badminton"), ("🎾", "Tennis"), ("🤾", "Handball"), ("🚴", "Cycling"), ("🤼", "Wrestling"), ("🏉", "Rugby")]
COUNTRIES = [("bj", "Benin"), ("bf", "Burkina Faso"), ("cv", "Cabo Verde"), ("ci", "Côte d'Ivoire"), ("gm", "The Gambia"),
             ("gh", "Ghana"), ("gn", "Guinea"), ("gw", "Guinea-Bissau"), ("lr", "Liberia"), ("ml", "Mali"),
             ("mr", "Mauritania"), ("ne", "Niger"), ("ng", "Nigeria"), ("sn", "Senegal"), ("sl", "Sierra Leone"), ("tg", "Togo")]
GALLERY = [("hero-sports-1.jpg", "Student-athletes competing at a university sports event"),
           ("opening-81.jpg", "Opening ceremony: athletes waving flags during the parade"),
           ("opening-63.jpg", "Opening ceremony: athletes marching on the track"),
           ("opening-112.jpg", "Opening ceremony: University of Ilesa delegation"),
           ("opening-109.jpg", "Opening ceremony: Team UENR"),
           ("opening-22.jpg", "Opening ceremony: Team UENR with the Ghana flag")]
HOME_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,800&family=Inter:wght@400;500;600&display=swap');
.wg{font-family:'Inter',system-ui,sans-serif}
.wg a{text-decoration:none}
.wg-hero{background:linear-gradient(135deg,#000080 0%,#0b1a94 60%,#1c2ba8 100%);color:#fff;border-radius:28px;padding:2.6rem 2.8rem;display:grid;grid-template-columns:1.4fr 1fr;gap:2rem;align-items:center;
 border-bottom:6px solid #FFC72C}
.wg-eyebrow{display:inline-block;color:#FFD34D;font-weight:600;font-size:.88rem;letter-spacing:.04em;border-bottom:2px solid #FFC72C;padding-bottom:.2rem}
.wg-h1{font-family:'Fraunces',Georgia,serif;font-weight:800;font-size:3.2rem;line-height:1.04;margin:1rem 0 .8rem;color:#fff}
.wg-hero p{font-size:1.08rem;line-height:1.6;color:rgba(255,255,255,.88);margin:0;max-width:34rem}
.wg-blob{background:radial-gradient(circle at 30% 25%,#FFFFFF 0%,#EADFC6 70%);border-radius:50%;aspect-ratio:1/1;display:flex;align-items:center;justify-content:center;
 box-shadow:0 0 0 10px rgba(255,199,44,.35);max-width:340px;margin:0 auto}
.wg-blob img{width:82%;height:82%;object-fit:contain}
.wg-strip{display:grid;grid-template-columns:repeat(3,1fr);margin:1.1rem 0 0;border:1px solid rgba(128,128,128,.35);border-radius:16px}
.wg-strip div{padding:1rem 1.4rem;text-align:center}
.wg-strip div+div{border-left:1px solid rgba(128,128,128,.35)}
.wg-strip b{display:block;font-family:'Fraunces',Georgia,serif;font-size:1.7rem;color:#B88700}
.wg-strip span{font-size:.82rem;opacity:.75;text-transform:uppercase;letter-spacing:.08em}
.wg-sec{display:flex;align-items:baseline;gap:.9rem;margin:3rem 0 .3rem;border-bottom:1px solid rgba(128,128,128,.35);padding-bottom:.5rem}
.wg-num{font-family:'Fraunces',Georgia,serif;font-weight:800;color:#B88700;font-size:1.1rem}
.wg-eye{font-size:.78rem;text-transform:uppercase;letter-spacing:.1em;opacity:.7}
.wg-h2{font-family:'Fraunces',Georgia,serif;font-weight:800;font-size:1.75rem;line-height:1.2;margin:.7rem 0 .3rem}
.wg-sub{opacity:.8;margin:0 0 1rem;max-width:46rem}
.wg-nums{display:grid;grid-template-columns:repeat(4,1fr);gap:1rem;margin:1rem 0}
.wg-nums div{border-left:4px solid #FFC72C;padding:.2rem 0 .2rem .9rem}
.wg-nums b{display:block;font-family:'Fraunces',Georgia,serif;font-size:2rem}
.wg-nums span{font-size:.85rem;opacity:.75}
.wg-podium{display:flex;gap:.8rem;align-items:flex-end;margin:1rem 0}
.wg-pod{flex:1;border-radius:14px 14px 0 0;padding:1rem;color:#17262B}
.wg-pod .m{font-size:1.6rem;display:block}
.wg-pod small{display:block;margin-top:.3rem;opacity:.85}
.wg-pod.p1{background:#F2D36B;min-height:190px}.wg-pod.p2{background:#D9DEE2;min-height:150px}.wg-pod.p3{background:#E3B48C;min-height:125px}
.wg-host{display:grid;grid-template-columns:70px 1fr;gap:1rem;padding:1.1rem 0;border-bottom:1px solid rgba(128,128,128,.3)}
.wg-host .n{font-family:'Fraunces',Georgia,serif;font-size:2.4rem;font-weight:800;color:#B88700;line-height:1}
.wg-host h4{margin:0 0 .25rem;font-size:1.1rem}
.wg-host p{margin:0;opacity:.82}
.wg-chips{display:flex;flex-wrap:wrap;gap:.55rem;margin:.6rem 0}
.wg-chip{display:inline-flex;align-items:center;gap:.45rem;background:#000080;border:1.5px solid #000080;color:#fff;border-radius:999px;padding:.4rem .95rem;font-weight:500;font-size:.95rem}
.wg-chip img{width:24px;height:24px;border-radius:50%;object-fit:cover;box-shadow:0 0 0 1px rgba(128,128,128,.4)}
.wg-chip.c{background:rgba(0,0,128,.12);border-color:#FFC72C;color:inherit}
.wg-quote{font-family:'Fraunces',Georgia,serif;font-size:1.55rem;line-height:1.4;padding:1.2rem 0 1.2rem 1.6rem;margin:1.2rem 0;border-left:6px solid #FFC72C;position:relative}
.wg-quote small{display:block;margin-top:.8rem;font-family:'Inter',sans-serif;font-size:.9rem;opacity:.75}
.wg-mosaic{display:grid;grid-template-columns:repeat(4,1fr);grid-auto-rows:150px;gap:.6rem;margin-top:.8rem}
.wg-mosaic img{width:100%;height:100%;object-fit:cover;border-radius:14px;display:block}
.wg-mosaic img:first-child{grid-column:span 2;grid-row:span 2}
.wg-foot{margin-top:3rem;border-top:6px solid #FFC72C;background:#000080;color:#fff;border-radius:0 0 22px 22px;padding:1.5rem 1.8rem;display:grid;grid-template-columns:1.4fr 1fr;gap:1.5rem}
.wg-foot b{font-family:'Fraunces',Georgia,serif;font-size:1.3rem}
.wg-foot small{color:rgba(255,255,255,.8)}
@media(max-width:800px){.wg-hero,.wg-foot{grid-template-columns:1fr;padding:1.5rem}.wg-h1{font-size:2.2rem}.wg-nums{grid-template-columns:repeat(2,1fr)}
 .wg-mosaic{grid-template-columns:repeat(2,1fr)}.wg-strip{grid-template-columns:1fr}.wg-strip div+div{border-left:0;border-top:1px solid rgba(128,128,128,.35)}}
</style>
"""

_n = {"i": 0}


def html(s):
    """Render an HTML snippet (strips indentation and blank lines so Markdown doesn't treat it as code)."""
    st.markdown("\n".join(l.strip() for l in s.split("\n") if l.strip()), unsafe_allow_html=True)


def section(eyebrow, title, sub=None):
    _n["i"] += 1
    html(f'<div class="wg"><div class="wg-sec"><span class="wg-num">{_n["i"]:02d}</span><span class="wg-eye">{eyebrow}</span></div>'
         f'<div class="wg-h2">{title}</div>' + (f'<div class="wg-sub">{sub}</div>' if sub else "") + "</div>")


def home():
    html(HOME_CSS)
    _n["i"] = 0

    # ---- hero ----
    html(f"""
    <div class="wg"><section class="wg-hero"><div>
      <span class="wg-eyebrow">2–12 October 2026 | Obafemi Awolowo University, Ile-Ife</span>
      <div class="wg-h1">West African University Games 2026</div>
      <p>University sport. Regional pride. One West Africa. WAUG 2026 brought student-athletes, officials, and institutions
      to Ile-Ife for ten days of competition, culture, friendship, and fair play.</p>
    </div><div class="wg-blob"><img src="{IMG}waug-2026-landing-mascot.png" alt="WAUG 2026 mascot holding a torch"></div></section>
    <div class="wg-strip"><div><b>2–12 Oct</b><span>Games Dates</span></div><div><b>Ile-Ife</b><span>Host City</span></div>
    <div><b>2026</b><span>Games Edition</span></div></div></div>
    """)

    # ---- results at a glance (from the app's own data) ----
    try:
        table_, _, ev_, _ = load()
        n_matches = len(load_matches()[0])
    except Exception:
        table_ = None
    if table_ is not None:
        section("Results at a glance", "The Games in numbers", "Calculated from the data loaded in this dashboard.")
        html(f"""<div class="wg"><div class="wg-nums">
        <div><b>{int(table_.total.sum())}</b><span>Medals awarded</span></div><div><b>{len(ev_)}</b><span>Medal events</span></div>
        <div><b>{len(table_)}</b><span>Universities on the medal table</span></div><div><b>{n_matches}</b><span>Matches recorded</span></div>
        </div></div>""")
        t = table_.sort_values("rank").head(3).reset_index(drop=True)
        pods = ""
        for idx, cls, emoji in [(1, "p2", "🥈"), (0, "p1", "🥇"), (2, "p3", "🥉")]:
            r = t.iloc[idx]
            pods += (f'<div class="wg-pod {cls}"><span class="m">{emoji}</span><b>{r.university}</b>'
                     f'<small>{r.gold} gold · {r.silver} silver · {r.bronze} bronze · {r.total} total</small></div>')
        html(f'<div class="wg"><div class="wg-podium">{pods}</div></div>')
        st.page_link(results_page, label="Open the full results dashboard", icon="🏅")

    # ---- official announcement ----
    section("Official Announcement", "15th West Africa University Games")
    a, b = st.columns([2, 3])
    a.image(IMG + "waug-2026-announcement.jpeg", caption="Official announcement poster")
    b.write("WAUG 2026 took place at Obafemi Awolowo University, Ile-Ife, Nigeria, from 2 to 12 October 2026, bringing universities "
            "across West Africa together under one regional sporting spirit.")

    # ---- about ----
    section("About WAUG 2026", "Where West Africa Meets Through University Sport")
    a, b = st.columns([2, 3])
    a.image(IMG + "waug-2026-mascot.jpeg", caption="Official mascot in blue and gold sportswear")
    b.write("WAUG 2026 brought university communities together through disciplined competition and a shared commitment to the "
            "development of student-athletes across West Africa.")
    b.write("Hosted by Obafemi Awolowo University from 2 to 12 October 2026, the Games placed sporting excellence alongside education, "
            "culture, respect, and regional cooperation.")
    b.write("The mascot and logo presented the Games as both a modern sporting event and a proud expression of "
            "Yoruba heritage in Ile-Ife.")

    # ---- mascot & logo ----
    section("Mascot & Logo Approved", "A Cultural Emblem for a Regional Games")
    st.write("The Local Organising Committee officially approved the WAUG 2026 mascot and logo, a major step in "
             "preparations for the Games at Obafemi Awolowo University, Ile-Ife.")
    st.write("The mascot draws from West African culture and the Yoruba heritage of Ile-Ife. It features the Olokun head, a symbol of "
             "wealth, prosperity, and the sea in Yoruba mythology, with the Opele divination chain and cowries adding meanings of "
             "wisdom, prestige, and shared identity.")
    html('<div class="wg"><div class="wg-quote">“These symbols are not just emblems; they are the embodiment of our rich cultural '
         'heritage and the unifying spirit of WAUG.”<small>Prof. E.O. Akinfala, Chairman of the LOC and Deputy Vice Chancellor '
         '(Administration), OAU</small></div></div>')

    # ---- host ----
    section("The Host", "Obafemi Awolowo University, Ile-Ife",
            "Set within one of Nigeria's most distinguished university communities, WAUG 2026 carried the formal character of a major "
            "academic occasion while delivering the energy of regional sport and the cultural depth of Ile-Ife.")
    rows = [("01", "Academic Setting", "A university environment shaped by scholarship, leadership, culture, and public service."),
            ("02", "Regional Welcome", "An invitation to universities across West Africa to gather in friendship, shared heritage, and disciplined competition."),
            ("03", "Sporting Excellence", "A platform for student-athletes to compete with honour and represent their institutions with pride.")]
    html('<div class="wg">' + "".join(f'<div class="wg-host"><div class="n">{n}</div><div><h4>{t}</h4><p>{d}</p></div></div>' for n, t, d in rows) + "</div>")

    # ---- sports ----
    section("Sports Disciplines", "A Broad Programme of Competition",
            "Athletes competed across a broad programme that included athletics, football, basketball, swimming, "
            "and other individual and team events.")
    html('<div class="wg"><div class="wg-chips">' + "".join(f'<span class="wg-chip">{e} {n}</span>' for e, n in SPORTS) + "</div></div>")

    # ---- countries ----
    section("Participating Countries", "West Africa Represented at WAUG 2026",
            "Universities and student-athletes from across West Africa were expected in Ile-Ife for the Games.")
    html('<div class="wg"><div class="wg-chips">' + "".join(
        f'<span class="wg-chip c"><img src="https://flagcdn.com/w80/{c}.png" alt="Flag of {n}">{n}</span>' for c, n in COUNTRIES) + "</div></div>")

    # ---- gallery ----
    section("Gallery", "Moments from Ile-Ife")
    html('<div class="wg"><div class="wg-mosaic">' + "".join(f'<img src="{IMG}{f}" alt="{alt}" title="{alt}">' for f, alt in GALLERY) + "</div></div>")

    # ---- footer ----
    html("""
    <div class="wg"><div class="wg-foot"><div>
      <b>WAUG 2026</b><br>The 2026 West African University Games, hosted by Obafemi Awolowo University in Ile-Ife, Nigeria.<br>
      <i>Excellence • Friendship • Fair play</i>
    </div><div><small>Host: Obafemi Awolowo University, Ile-Ife, Osun State, Nigeria<br>
      © 2026 West African University Games. Content from waug.oauife.edu.ng</small></div></div></div>
    """)


def winners_tab():
    try:
        w = build_winners(load()[1])
    except Exception as err:
        st.error(f"Could not load the winners: {err}")
        return

    st.subheader("Event winners")
    st.write("Who stood on the podium in every event, from the AlliSports Data results.")
    c = st.columns(4)
    sport = c[0].multiselect("Sport", sorted(w.sport.unique()), key="w_sport")
    cat = c[1].multiselect("Category", ["Men", "Women", "Mixed"], key="w_cat")
    uni = c[2].text_input("University (abbr.), e.g. OAU, UG-GH", key="w_uni")
    name = c[3].text_input("Athlete name", key="w_name")

    v = w.copy()
    if sport: v = v[v.sport.isin(sport)]
    if cat: v = v[v.category.isin(cat)]
    for text in (uni, name):
        if text:
            t = text.lower()
            v = v[v[["gold", "silver", "bronze"]].apply(lambda r: t in " ".join(r).lower(), axis=1)]

    k = st.columns(3)
    k[0].metric("Events shown", len(v))
    k[1].metric("Sports", v.sport.nunique())
    k[2].metric("Medals listed", int(sum(len([x for x in col.split("; ") if x]) for col in v[["gold", "silver", "bronze"]].values.ravel())))

    show = v.rename(columns={"sport": "Sport", "category": "Category", "event": "Event",
                             "gold": "🥇 Gold", "silver": "🥈 Silver", "bronze": "🥉 Bronze"})
    st.dataframe(show, hide_index=True, width="stretch", height=560)
    st.caption("Each entry shows the athlete and their university. Team events show \"Team\" because the official table lists no names; "
               "where two bronze medals were awarded in an event, both are shown. "
               "Provisional results are not yet confirmed by the WAUG Technical Committee. Data: AlliSports Data.")
    st.download_button("Download event winners (CSV)", v.to_csv(index=False), "waug_2026_event_winners.csv", "text/csv")


ABOUT_CSS = """
<style>
.wg-band{background:linear-gradient(135deg,#000080 0%,#0b1a94 60%,#1c2ba8 100%);color:#fff;border-radius:22px;padding:2rem 2.4rem;border-bottom:6px solid #FFC72C}
.wg-band .wg-h1{font-size:2.6rem;margin:.6rem 0 .2rem}
.wg-lead{font-size:1.12rem;line-height:1.7;margin:1.4rem 0 .8rem;max-width:52rem}
.wg-partners{display:grid;grid-template-columns:repeat(3,1fr);gap:.8rem;margin:1rem 0}
.wg-partner{border:1px solid rgba(128,128,128,.35);border-top:4px solid #FFC72C;border-radius:12px;padding:.9rem 1.1rem}
.wg-partner small{display:block;text-transform:uppercase;letter-spacing:.08em;font-size:.72rem;opacity:.7}
.wg-partner b{font-family:'Fraunces',Georgia,serif;font-size:1.05rem}
.wg-role{display:grid;grid-template-columns:200px 1fr;gap:1.2rem;padding:1.2rem 0;border-bottom:1px solid rgba(128,128,128,.3)}
.wg-role .r{font-family:'Fraunces',Georgia,serif;font-weight:800;color:#B88700;font-size:1.1rem;line-height:1.3}
.wg-role h4{margin:0 0 .15rem;font-size:1.1rem}
.wg-role .t{opacity:.75;font-size:.92rem;margin-bottom:.5rem}
.wg-role p{margin:0;opacity:.85}
.wg-sub a{color:#B88700;text-decoration:underline !important;font-weight:600}
.wg-foot a{color:#FFD34D !important;text-decoration:underline !important}
@media(max-width:800px){.wg-partners{grid-template-columns:1fr}.wg-role{grid-template-columns:1fr;gap:.3rem}.wg-band .wg-h1{font-size:2rem}}
</style>
"""


def about():
    html(HOME_CSS)
    html(ABOUT_CSS)
    _n["i"] = 0

    html("""
    <div class="wg"><div class="wg-band"><span class="wg-eyebrow">About</span>
    <div class="wg-h1">The organisers</div></div>
    <div class="wg-lead">The 2026 West African University Games (WAUG) were organized by Obafemi Awolowo University (OAU), Ile-Ife,
    in collaboration with the West African University Sports Federation (WAUSF) and the Nigerian University Games Association (NUGA).
    The 15th edition of the Games took place on the OAU campus from October 2 to October 12, 2026.</div>
    <div class="wg-partners">
      <div class="wg-partner"><small>Host</small><b>Obafemi Awolowo University (OAU), Ile-Ife</b></div>
      <div class="wg-partner"><small>In collaboration with</small><b>West African University Sports Federation (WAUSF)</b></div>
      <div class="wg-partner"><small>In collaboration with</small><b>Nigerian University Games Association (NUGA)</b></div>
    </div></div>
    """)

    section("Leadership", "Host & Local Organising Committee (LOC) Leadership",
            "The host institution appointed a dedicated Local Organising Committee led by senior university officials to oversee "
            "facilities, logistics, security, and hospitality.")
    roles = [
        ("LOC Chairman", "Professor E. O. Akinfala", "Deputy Vice-Chancellor (Administration), OAU",
         "Chaired the committee responsible for venue preparations, accommodation, and event execution."),
        ("Host University Leadership", "Professor Adebayo Simeon Bamire<br>Rt. Hon. Ambassador Adejare Bello",
         "Vice-Chancellor, OAU<br>Pro-Chancellor and Governing Council Chairman",
         "Spearheaded institutional backing and stakeholder coordination."),
        ("Principal University Officers", "Professor A. O. Aderonmu<br>Professor Akanni Akinyemi",
         "Deputy Vice-Chancellor (Academic)<br>Deputy Vice-Chancellor (Research, Innovation and Development)",
         "Also supported local planning alongside university deans, directors, and student volunteers."),
    ]
    html('<div class="wg">' + "".join(
        f'<div class="wg-role"><div class="r">{r}</div><div><h4>{n}</h4><div class="t">{t}</div><p>{d}</p></div></div>'
        for r, n, t, d in roles) + "</div>")

    section("Data & methodology", "Where the numbers come from",
            "Data: AlliSports Data (data.allimediahub.com). Official WAUG website: <a href='https://waug.oauife.edu.ng' target='_blank' rel='noopener noreferrer'>waug.oauife.edu.ng</a>.")
    items = [
        ("Data credit", "All results, medal counts, winners and match scorelines on this dashboard are provided by AlliSports Data "
         "(Alli Media Hub), at data.allimediahub.com."),
        ("Live feed", "The medal table, event results, winners and match scorelines are loaded from the AlliSports Data feed and "
         "refreshed about every minute. The medal table is calculated from the recorded results."),
        ("Result status", "Provisional results were entered at the venue and are not yet confirmed. Official results are confirmed by "
         "the WAUG Technical Committee. Disputed events are left out of the medal table until settled."),
        ("Ranking", "Universities are ranked by gold medals first, then silver, then bronze. Universities with the same medals share "
         "a rank and the next rank is skipped (1, 1, 3)."),
        ("Matches", "Football and basketball matches come from the feed, with scores and group tables. Matches in sports the "
         "feed does not carry yet, such as tennis, table tennis and badminton, come from a saved snapshot of results for 5 to 11 October 2026."),
        ("Known limits", "Team events list no athlete names, and athlete names are spelled as recorded, so an athlete's count may be "
         "slightly low. If the feed is unavailable, the dashboard shows a saved copy of the results."),
    ]
    html('<div class="wg">' + "".join(
        f'<div class="wg-role"><div class="r">{t}</div><div><p>{d}</p></div></div>' for t, d in items) + "</div>")

    section("Credits", "Built by")
    html("""
    <div class="wg"><div class="wg-foot"><div>
      <b>Adelerin Samuel</b><br>Designed and built this dashboard.
    </div><div><small>Data: AlliSports Data (data.allimediahub.com)<br>Official WAUG website: <a href="https://waug.oauife.edu.ng" target="_blank" rel="noopener noreferrer">waug.oauife.edu.ng</a></small></div></div></div>
    """)


STATUS_LABEL = {"finished": "✅ Full time", "live": "🔴 Live", "scheduled": "🕒 Upcoming"}


def scoreline(r):
    if pd.isna(r.score_a) or pd.isna(r.score_b):
        return f"{r.team_a}  vs  {r.team_b}"
    pens = f" (pens {int(r.pens_a)}–{int(r.pens_b)})" if pd.notna(r.pens_a) and pd.notna(r.pens_b) else ""
    a = ("✅ " if r.winner == "A" else "") + r.team_a
    b = r.team_b + (" ✅" if r.winner == "B" else "")
    return f"{a}  {int(r.score_a)}–{int(r.score_b)}  {b}{pens}"


def api_match_line(m):
    sc, pen = m.get("score") or {}, m.get("penalties") or {}
    mid = f"{sc['home']}–{sc['away']}" if sc.get("home") is not None else "vs"
    pens = f" (pens {pen['home']}–{pen['away']})" if pen.get("home") is not None else ""
    return f"{m['home']['name']}  {mid}  {m['away']['name']}{pens}"


def competition_section(mt):
    st.markdown("##### Group tables and knockout rounds")
    ev_api = mt[(mt.source == "api") & mt.event_id.notna()].drop_duplicates("event_id")
    if ev_api.empty:
        st.caption("Group tables are not available.")
        return
    names = dict(zip(ev_api.event_id, ev_api.event_name))
    eid = st.selectbox("Team event", list(names), format_func=lambda x: names[x], key="m_comp")
    try:
        comp = load_competition(eid)["data"]
    except ApiNotFound:
        st.info("No group table has been set up for this event yet.")
        return
    except Exception as err:
        st.info("Group tables are not available for this event.")
        return
    for grp in comp.get("groups", []):
        st.markdown(f"**{grp['name']}**" + (" · complete" if grp.get("complete") else ""))
        rows = [{"Pos": r.get("position"), "Team": r["team"]["name"], "P": r.get("played"), "W": r.get("won"), "D": r.get("drawn"),
                 "L": r.get("lost"), "For": r.get("goalsFor"), "Against": r.get("goalsAgainst"), "GD": r.get("goalDifference"),
                 "Pts": r.get("points"), "": "✅ qualifies" if r.get("qualifies") else ("🔴 live" if r.get("live") else "")}
                for r in grp.get("rows", [])]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        for note in grp.get("notes", []):
            st.caption(note)
    tb = (comp.get("rules") or {}).get("tieBreakers")
    if tb:
        st.caption("Tie-breakers, in order: " + ", ".join(tb))
    for rd in comp.get("rounds", []):
        st.markdown(f"**{rd['name']}**")
        for m in rd.get("matches", []):
            st.write("• " + api_match_line(m))


def matches_tab():
    mt, meta = load_matches()
    st.subheader("Matches played and scorelines")
    if meta.get("generatedAt") and not meta.get("error"):
        st.caption("Data: AlliSports Data · updated " + meta["generatedAt"][:16].replace("T", " ") + " UTC. "
                   "Football and basketball come from the feed; other sports are from a saved snapshot of 5–11 October.")
    else:
        st.caption("Data: AlliSports Data")
    if mt.empty:
        st.info("No match data available yet.")
        return
    c = st.columns(5)
    sp_sel = c[0].multiselect("Sport ", sorted(mt.sport.unique()), key="m_sport")
    cat_sel = c[1].multiselect("Category ", ["Men", "Women", "Mixed"], key="m_cat")
    uni_sel = c[2].multiselect("University (abbr.)", sorted(set(mt.uni_a) | set(mt.uni_b)), key="m_uni")
    st_sel = c[3].multiselect("Status", list(STATUS_LABEL.values()), key="m_status")
    q = c[4].text_input("Search player / stage", key="m_q")

    g = mt.copy()
    if sp_sel: g = g[g.sport.isin(sp_sel)]
    if cat_sel: g = g[g.category.isin(cat_sel)]
    if uni_sel: g = g[g.uni_a.isin(uni_sel) | g.uni_b.isin(uni_sel)]
    if st_sel: g = g[g.status.map(STATUS_LABEL).isin(st_sel)]
    if q:
        ql = q.lower()
        g = g[g.apply(lambda r: ql in f"{r.team_a} {r.team_b} {r.stage} {r.uni_a} {r.uni_b}".lower(), axis=1)]
    if g.empty:
        st.info("No matches match these filters.")
        return

    played = g[g.status != "scheduled"]
    team_g = played[played.sport.isin(["Football", "Basketball", "Handball"])]
    k = st.columns(4)
    k[0].metric("Matches", len(g))
    k[1].metric("Sports", g.sport.nunique())
    k[2].metric("Days", g.date.nunique())
    k[3].metric("Goals / points scored (team sports)", int(team_g.score_a.fillna(0).sum() + team_g.score_b.fillna(0).sum()))
    live = g[g.status == "live"]
    for _, r in live.iterrows():
        st.error(f"🔴 LIVE · {r.sport} · {scoreline(r)}")

    c1, c2 = st.columns(2)
    per_day = g.dropna(subset=["date"]).groupby(["date", "sport"]).size().reset_index(name="Matches")
    per_day["Day"] = per_day.date.dt.strftime("%d %b")
    fig = px.bar(per_day, x="Day", y="Matches", color="sport", title="Matches per day",
                 category_orders={"Day": per_day.sort_values("date").Day.unique().tolist()})
    fig.update_layout(xaxis_title=None, legend_title=None)
    c1.plotly_chart(fig, width="stretch")

    fin = g[g.status == "finished"]
    res = pd.concat([
        pd.DataFrame({"Uni": fin.uni_a, "Result": fin.winner.map({"A": "Won", "B": "Lost"}).fillna("Drawn")}),
        pd.DataFrame({"Uni": fin.uni_b, "Result": fin.winner.map({"A": "Lost", "B": "Won"}).fillna("Drawn")})])
    if not res.empty:
        wl = res.groupby(["Uni", "Result"]).size().unstack(fill_value=0).reindex(columns=["Won", "Drawn", "Lost"], fill_value=0)
        wl = wl.assign(T=wl.sum(axis=1)).sort_values(["Won", "Drawn", "T"], ascending=False).head(15)
        fig = px.bar(wl.reset_index().melt(id_vars=["Uni", "T"], value_vars=["Won", "Drawn", "Lost"], var_name="Result", value_name="Matches"),
                     y="Uni", x="Matches", color="Result", orientation="h", title="Wins, draws and losses (top 15)",
                     color_discrete_map={"Won": "#000080", "Drawn": "#FFC72C", "Lost": "#9CA3AF"},
                     category_orders={"Uni": wl.index.tolist()[::-1]})
        fig.update_layout(yaxis_title=None, legend_title=None)
        c2.plotly_chart(fig, width="stretch")

    st.markdown("##### Results")
    view = g.sort_values(["date", "time", "sport"], ascending=[False, False, True]).copy()
    view["Match"] = view.apply(scoreline, axis=1)
    view["Date"] = view.date.dt.strftime("%a %d %b")
    view["Status"] = view.status.map(STATUS_LABEL)
    show = view[["Date", "time", "sport", "category", "stage", "Match", "sets", "Status"]].rename(
        columns={"time": "Time (WAT)", "sport": "Sport", "category": "Category", "stage": "Stage", "sets": "Detail"})
    st.dataframe(show, hide_index=True, width="stretch", height=480)
    st.caption("✅ marks the winner. Detail shows set scores (team listed first), quarters or half-time. "
               "Football draws in knockout games are decided on penalties. Results marked live or provisional can still change. "
               "Data: AlliSports Data.")
    competition_section(mt)


def results():
    try:
        table, det, ev, meta = load()
    except Exception as err:
        st.error(str(err))
        st.stop()
    if meta["source"] == "api":
        st.caption("Data: AlliSports Data · updated " + meta["generatedAt"][:16].replace("T", " ") + " UTC"
                   + (" · includes provisional results" if meta["includesProvisional"] else ""))
    else:
        st.caption("Data: AlliSports Data")

    col_logo, col_title = st.columns([0.05, 0.95])

    with col_logo:
        st.image("waug-2026-logo.png", width=70)
    with col_title:
        st.title("West African University Games 2026")
    st.caption("Medal table and event results · built from the official medal-table document and the event-results export")

    # ---------- sidebar filters ----------
    with st.sidebar:
        st.header("Filters")
        sports = st.multiselect("Sport", sorted(det.sport.unique()))
        cats = st.multiselect("Category", ["Male", "Female", "Mixed"])
        countries = st.multiselect("Country", sorted(det.country.unique()))
        st.caption("Country comes from the AlliSports Data feed.")
        if st.button("Refresh data"):
            st.cache_data.clear()
            st.rerun()

    f = det.copy()
    if sports: f = f[f.sport.isin(sports)]
    if cats: f = f[f.category.isin(cats)]
    if countries: f = f[f.country.isin(countries)]

    # ---------- KPIs ----------
    by_school = f.groupby(["university", "medal"], observed=True).size().unstack(fill_value=0).reindex(columns=["Gold", "Silver", "Bronze"], fill_value=0)
    by_school["Total"] = by_school.sum(axis=1)
    by_school = by_school.sort_values(["Gold", "Silver", "Bronze"], ascending=False)

    k = st.columns(4)
    k[0].metric("Medals shown", len(f))
    k[1].metric("Gold", int((f.medal == "Gold").sum()))
    k[2].metric("Universities with medals", f.university.nunique())
    k[3].metric("Leader (by gold)", by_school.index[0] if len(by_school) else "–")

    tab1, tab2, tab4, tab5, tab7, tab6 = st.tabs(["Medal table", "Sports", "Athletes", "Events & data", "Event winners", "Matches"])

    # ---------- 1. medal table ----------
    with tab1:
        long = by_school.reset_index().melt(id_vars=["university", "Total"], value_vars=["Gold", "Silver", "Bronze"], var_name="Medal", value_name="Count")
        order = by_school.index.tolist()[::-1]
        fig = px.bar(long, y="university", x="Count", color="Medal", orientation="h", color_discrete_map=MEDAL_COLORS,
                     category_orders={"university": order, "Medal": ["Gold", "Silver", "Bronze"]}, height=max(420, 26 * len(order) + 120))
        fig.update_layout(yaxis_title=None, xaxis_title="Medals", legend_title=None, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, width="stretch")
        show = by_school.reset_index().rename(columns={"university": "University"})
        show.insert(0, "Rank", range(1, len(show) + 1))
        st.dataframe(show, hide_index=True, width="stretch")

    # ---------- 2. sports ----------
    with tab2:
        c1, c2 = st.columns([1, 1])
        sp = f.groupby(["sport", "medal"], observed=True).size().reset_index(name="Count")
        sp_order = f.sport.value_counts().index.tolist()[::-1]
        fig = px.bar(sp, y="sport", x="Count", color="medal", orientation="h", color_discrete_map=MEDAL_COLORS,
                     category_orders={"sport": sp_order}, title="Medals awarded by sport", height=480)
        fig.update_layout(yaxis_title=None, legend_title=None)
        c1.plotly_chart(fig, width="stretch")
        cat = f.groupby(["sport", "category"]).size().reset_index(name="Count")
        fig = px.bar(cat, x="sport", y="Count", color="category", title="Medals by category",
                     color_discrete_map={"Male": "#2563EB", "Female": "#DB2777", "Mixed": "#7C3AED", "Other": "#6B7280"})
        fig.update_layout(xaxis_title=None, legend_title=None, height=480)
        c2.plotly_chart(fig, width="stretch")

        st.subheader("Who wins what: medals by university and sport")
        heat = f.pivot_table(index="university", columns="sport", values="medal", aggfunc="count", fill_value=0)
        heat = heat.loc[by_school.index.intersection(heat.index)]
        fig = px.imshow(heat, aspect="auto", color_continuous_scale="YlOrBr", text_auto=True, height=max(420, 26 * len(heat) + 140))
        fig.update_layout(xaxis_title=None, yaxis_title=None, coloraxis_showscale=False, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, width="stretch")

    # ---------- 4. athletes ----------
    with tab4:
        ind = f[(f.athlete != "Team") & (f.athlete != "–") & ~f.athlete.str.contains("/|,|\\d\\.", regex=True)].copy()
        ind["athlete"] = ind.athlete.str.replace(r"\s*\(Board \d\)", "", regex=True).str.strip()
        top = ind.groupby(["athlete", "university", "medal"], observed=True).size().unstack(fill_value=0).reindex(columns=["Gold", "Silver", "Bronze"], fill_value=0)
        top["Total"] = top.sum(axis=1)
        top = top.sort_values(["Gold", "Total"], ascending=False).reset_index().head(15)
        long = top.melt(id_vars=["athlete", "university", "Total"], value_vars=["Gold", "Silver", "Bronze"], var_name="Medal", value_name="Count")
        fig = px.bar(long, y="athlete", x="Count", color="Medal", orientation="h", color_discrete_map=MEDAL_COLORS,
                     category_orders={"athlete": top.athlete.tolist()[::-1]}, hover_data=["university"], height=520,
                     title="Top 15 individual athletes (singles-style entries)")
        fig.update_layout(yaxis_title=None, legend_title=None)
        st.plotly_chart(fig, width="stretch")
        st.caption("Team, relay and doubles entries are excluded. Names are as written in the source and the same athlete is sometimes spelled differently, so counts may be slightly low.")

    # ---------- 5. events & data ----------
    with tab5:
        ev_f = ev.copy()
        if sports: ev_f = ev_f[ev_f.Sport.isin(sports)]
        if cats: ev_f = ev_f[ev_f.Category.isin(cats)]
        st.subheader("Event results")
        q = st.text_input("Search events or universities")
        cols = ["Sport", "Event", "Category", "Gold", "Silver", "Bronze I", "Bronze II"]
        ev_f = ev_f[cols].fillna("")
        if q:
            ev_f = ev_f[ev_f.apply(lambda r: q.lower() in " ".join(r.astype(str)).lower(), axis=1)]
        st.dataframe(ev_f, hide_index=True, width="stretch", height=380)

        st.subheader("Data checks")
        ev_counts = pd.DataFrame({"gold": ev.Gold.value_counts(), "silver": ev.Silver.value_counts(),
                                  "bronze": pd.concat([ev["Bronze I"], ev["Bronze II"]]).value_counts()}).fillna(0).astype(int)
        tt = table.set_index("university")[["gold", "silver", "bronze"]]
        match = ev_counts.reindex(tt.index, fill_value=0).equals(tt)
        st.write(f"- Medal table: **{table.total.sum()}** medals across **{len(table)}** universities.")
        st.write(f"- Event results: **{len(ev)}** events, **{int(ev_counts.values.sum())}** medals; "
                 f"per-university counts {'match' if match else 'do not match'} the medal table.")
        if meta["source"] == "api":
            pend = int((ev["Status"] != "official").sum())
            st.write(f"- Latest result update: **{ev['Updated Timestamp'].max()}** (UTC). {pend} of {len(ev)} events are still provisional.")
        else:
            st.write(f"- Latest event update in the snapshot: **{ev['Updated Timestamp'].max()}**.")
        st.download_button("Download filtered medals (CSV)", f.to_csv(index=False), "waug_2026_medals_filtered.csv", "text/csv")


    # ---------- 7. event winners ----------
    with tab7:
        winners_tab()

    # ---------- 6. matches ----------
    with tab6:
        matches_tab()


# ---------- navigation ----------
home_page = st.Page(home, title="Home", icon="🏠", default=True)
results_page = st.Page(results, title="Results Dashboard", icon="🏅", url_path="results")
about_page = st.Page(about, title="About", icon="ℹ️", url_path="about")
try:
    nav = st.navigation([home_page, results_page, about_page], position="top")
except TypeError:  # older Streamlit: navigation goes in the sidebar
    nav = st.navigation([home_page, results_page, about_page])
nav.run()