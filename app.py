import inspect
import os
from html import escape as esc
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
.wg-foot{margin-top:3rem;border-top:6px solid #FFC72C;background:#000080;color:#fff;border-radius:0 0 22px 22px;padding:1.5rem 1.8rem;display:grid;grid-template-columns:1.4fr 1fr;gap:1.5rem}
.wg-foot b{font-family:'Fraunces',Georgia,serif;font-size:1.3rem}
.wg-foot small{color:rgba(255,255,255,.8)}
.wg-recs{display:grid;grid-template-columns:repeat(3,1fr);gap:.9rem;margin:1rem 0}
.wg-rec{border:1px solid rgba(128,128,128,.35);border-top:4px solid #FFC72C;border-radius:12px;padding:1rem 1.1rem}
.wg-rec span{display:block;text-transform:uppercase;letter-spacing:.08em;font-size:.72rem;opacity:.7;margin-bottom:.3rem}
.wg-rec b{display:block;font-family:'Fraunces',Georgia,serif;font-size:1.45rem;line-height:1.2}
.wg-rec small{display:block;margin-top:.4rem;opacity:.8}
.wg-champs{display:grid;grid-template-columns:repeat(3,1fr);gap:.9rem;margin:1rem 0}
.wg-champ{background:#000080;color:#fff;border-radius:14px;border-bottom:4px solid #FFC72C;padding:1rem 1.2rem}
.wg-champ span{display:block;color:#FFD34D;text-transform:uppercase;letter-spacing:.08em;font-size:.72rem;margin-bottom:.3rem}
.wg-champ b{display:block;font-family:'Fraunces',Georgia,serif;font-size:1.25rem;line-height:1.25}
.wg-champ small{display:block;margin-top:.5rem;color:rgba(255,255,255,.82)}
.wg-board{margin:1rem 0;border:1px solid rgba(128,128,128,.35);border-radius:14px;overflow:hidden}
.wg-row{display:grid;grid-template-columns:56px 1fr auto;gap:.8rem;align-items:center;padding:.8rem 1.1rem;border-bottom:1px solid rgba(128,128,128,.25)}
.wg-row:last-child{border-bottom:0}
.wg-row .pos{font-family:'Fraunces',Georgia,serif;font-weight:800;font-size:1.6rem;color:#B88700}
.wg-row .who b{display:block}
.wg-row .who small{opacity:.7}
.wg-row .meds span{display:inline-block;border:1px solid rgba(128,128,128,.4);border-radius:999px;padding:.15rem .6rem;margin-left:.3rem;font-size:.9rem}
.wg-stages{display:grid;grid-template-columns:repeat(3,1fr);margin:1.2rem 0}
.wg-stage{position:relative;padding-right:1.4rem}
.wg-stage::before{content:"";position:absolute;top:21px;left:48px;right:0;height:3px;background:rgba(128,128,128,.35)}
.wg-stage:last-child::before{display:none}
.wg-stage .dot{width:44px;height:44px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-family:'Fraunces',Georgia,serif;font-weight:800;color:#fff;position:relative;z-index:1;box-shadow:0 0 0 2px rgba(128,128,128,.4)}
.wg-stage.s1 .dot{background:#000080}.wg-stage.s2 .dot{background:#FFC72C;color:#000080}.wg-stage.s3 .dot{background:#000033}
.wg-stage span{display:block;margin-top:.9rem;text-transform:uppercase;letter-spacing:.08em;font-size:.72rem;opacity:.7}
.wg-stage h4{margin:.2rem 0 .35rem;font-family:'Fraunces',Georgia,serif;font-size:1.2rem}
.wg-stage p{margin:0;opacity:.85}
.wg-unis{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:.6rem;margin:.8rem 0}
.wg-uni{display:flex;align-items:center;gap:.7rem;border:1px solid rgba(128,128,128,.35);border-radius:12px;padding:.6rem .8rem}
.wg-uni img{width:30px;height:20px;object-fit:cover;border-radius:3px;box-shadow:0 0 0 1px rgba(128,128,128,.4)}
.wg-uni b{display:block;font-size:.85rem;color:#B88700}
.wg-uni span{font-size:.92rem;line-height:1.25}
div.stButton>button{background:#000080;color:#fff;border:0;border-radius:10px;font-weight:600;padding:.6rem 1rem}
div.stButton>button:hover{background:#FFC72C;color:#000080}
@media(max-width:800px){.wg-champs,.wg-recs{grid-template-columns:1fr}.wg-stages{grid-template-columns:1fr;gap:1.4rem}.wg-stage::before{display:none}.wg-hero,.wg-foot{grid-template-columns:1fr;padding:1.5rem}.wg-h1{font-size:2.2rem}.wg-nums{grid-template-columns:repeat(2,1fr)}
.wg-strip{grid-template-columns:1fr}.wg-strip div+div{border-left:0;border-top:1px solid rgba(128,128,128,.35)}}
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


def records(det, mt):
    """Highlights worked out from the results: (value, label, detail) cards."""
    out = []
    d = det.copy()
    d["medal"] = d.medal.astype(str)
    ind = d[~d.athlete.isin(["Team", "–"]) & ~d.athlete.str.contains("/|,", regex=True)]
    if not ind.empty:
        t = ind.groupby(["athlete", "abbr", "medal"]).size().unstack(fill_value=0).reindex(columns=["Gold", "Silver", "Bronze"], fill_value=0)
        t["Total"] = t.sum(axis=1)
        (name, abbr), r = next(iter(t.sort_values(["Gold", "Total"], ascending=False).iterrows()))
        out.append((name, "Most decorated athlete", f"{r.Gold} gold · {r.Silver} silver · {r.Bronze} bronze · {abbr}"))
    by_sport = d.groupby("sport").size().sort_values(ascending=False)
    n_events = d.groupby("sport").event.nunique()
    out.append((by_sport.index[0], "Sport with the most medals", f"{by_sport.iloc[0]} medals across {n_events[by_sport.index[0]]} events"))
    gold = d[d.medal == "Gold"].groupby(["abbr", "sport"]).size().sort_values(ascending=False)
    if not gold.empty:
        out.append((gold.index[0][0], "Most golds in a single sport", f"{gold.iloc[0]} gold medals in {gold.index[0][1]}"))
    if mt is not None and not mt.empty:
        fin = mt[(mt.status == "finished") & mt.score_a.notna() & mt.score_b.notna()].copy()
        fin["margin"] = (fin.score_a - fin.score_b).abs()
        for sport in ("Football", "Basketball"):
            g = fin[fin.sport == sport]
            if g.empty or g.margin.max() == 0:
                continue
            r = g.sort_values("margin", ascending=False).iloc[0]
            win, lose = (r.team_a, r.team_b) if r.score_a > r.score_b else (r.team_b, r.team_a)
            hi, lo = int(max(r.score_a, r.score_b)), int(min(r.score_a, r.score_b))
            out.append((f"{hi}–{lo}", f"Biggest {sport.lower()} win", f"{win} beat {lose}" + (f" · {r.stage}" if r.stage else "")))
        pens = fin[(fin.sport == "Football") & fin.pens_a.notna()]
        if len(pens):
            out.append((str(len(pens)), "Football matches settled on penalties", "After the score was level at full time"))
    return out


CODE_BY_NAME = {"Nigeria": "NG", "Ghana": "GH"}


@st.cache_data(ttl=300, show_spinner=False)
def load_universities():
    """Every university that took part: (code, name, country code). From the API, else from the saved medal table."""
    try:
        rows = api_get("universities")["data"]
        df = pd.DataFrame([{"code": r["code"], "name": r["name"], "country": r.get("country") or ""} for r in rows])
    except Exception:
        t = load()[0]
        df = pd.DataFrame({"code": t.abbr, "name": t.university, "country": t.country.map(lambda c: CODE_BY_NAME.get(c, c))})
    return df.sort_values("name").reset_index(drop=True)


def champions(det, mt):
    """Champions of the team sports, with the final's scoreline when the matches have it."""
    d = det.copy()
    d["medal"] = d.medal.astype(str)
    d = d[(d.athlete == "Team") & d.sport.isin(["Football", "Basketball", "Volleyball", "Handball"])]
    out = []
    for (sport, cat3), g in d.groupby(["sport", "cat3"]):
        gold = g[g.medal == "Gold"]
        if gold.empty:
            continue
        champ, code = gold.iloc[0].university, gold.iloc[0].abbr
        silver = g[g.medal == "Silver"]
        detail = f"Runner-up: {silver.iloc[0].university}" if not silver.empty else ""
        if mt is not None and not mt.empty:
            f = mt[(mt.sport == sport) & (mt.category == cat3) & (mt.stage.fillna("").str.strip().str.lower() == "final")
                   & (mt.status == "finished") & mt.score_a.notna()]
            f = f[((f.uni_a == code) & (f.winner == "A")) | ((f.uni_b == code) & (f.winner == "B"))]
            if not f.empty:
                r = f.iloc[0]
                opp = r.team_b if r.uni_a == code else r.team_a
                mine, theirs = (r.score_a, r.score_b) if r.uni_a == code else (r.score_b, r.score_a)
                pens = ""
                if pd.notna(r.pens_a) and pd.notna(r.pens_b):
                    pm, pt = (r.pens_a, r.pens_b) if r.uni_a == code else (r.pens_b, r.pens_a)
                    pens = f" (pens {int(pm)}–{int(pt)})"
                detail = f"Final: {int(mine)}–{int(theirs)}{pens} vs {opp}"
        out.append((f"{cat3}'s {sport.lower()}", champ, detail))
    return sorted(out)


def top_athletes(det, n=5):
    d = det.copy()
    d["medal"] = d.medal.astype(str)
    ind = d[~d.athlete.isin(["Team", "–"]) & ~d.athlete.str.contains("/|,", regex=True)]
    if ind.empty:
        return []
    t = ind.groupby(["athlete", "abbr", "medal"]).size().unstack(fill_value=0).reindex(columns=["Gold", "Silver", "Bronze"], fill_value=0)
    t["Total"] = t.sum(axis=1)
    t = t.sort_values(["Gold", "Total", "Silver"], ascending=False).head(n)
    return [(a, u, int(r.Gold), int(r.Silver), int(r.Bronze)) for (a, u), r in t.iterrows()]


def go(page, tab=None):
    """Quick link: open a page (and optionally a tab of the Results Dashboard)."""
    st.session_state["goto_tab"] = tab
    st.switch_page(page)


STAGES = [("Opening Phase", "Arrival & Accreditation",
           "Delegation arrivals, verification, technical meetings, training access, and the opening ceremony."),
          ("Competition Phase", "Preliminaries & Finals",
           "Team and individual competitions delivered across approved university and partner venues."),
          ("Closing Phase", "Finals & Farewell",
           "Championship finals, medal presentations, closing ceremony, and delegation departures.")]


def overview():
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


    # ---- quick links ----
    section("Quick links", "Find what you need")
    links = [("🏅 Medal table", "Medal table", "Rankings by gold, silver and bronze"),
             ("🥇 Event winners", "Event winners", "Names of every podium finisher"),
             ("⚽ Matches", "Matches", "Scorelines, group tables and knockouts"),
             ("📄 Report", "__report__", "Why the results look the way they do"),
             ("ℹ️ About", None, "The organisers and the data")]
    for col, (label, tab, note) in zip(st.columns(len(links)), links):
        if col.button(label, key=f"ql_{label}", width="stretch"):
            go(about_page if tab is None else report_page if tab == "__report__" else results_page, None if tab == "__report__" else tab)
        col.caption(note)

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

        det_, mt_ = load()[1], load_matches()[0]
        try:
            champs = champions(det_, mt_)
        except Exception:
            champs = []
        if champs:
            section("Champions", "Team sport champions", "The winners of the team sports at WAUG 2026.")
            html('<div class="wg"><div class="wg-champs">' + "".join(
                f'<div class="wg-champ"><span>🏆 {esc(e)}</span><b>{esc(u)}</b><small>{esc(dt)}</small></div>' for e, u, dt in champs) + "</div></div>")
        try:
            top5 = top_athletes(det_)
        except Exception:
            top5 = []
        if top5:
            section("Athletes", "Top 5 athletes", "Ranked by gold medals, then total medals.")
            html('<div class="wg"><div class="wg-board">' + "".join(
                f'<div class="wg-row"><div class="pos">{i}</div><div class="who"><b>{esc(a)}</b><small>{esc(u)}</small></div>'
                f'<div class="meds"><span>🥇 {g}</span><span>🥈 {sv}</span><span>🥉 {b}</span></div></div>'
                for i, (a, u, g, sv, b) in enumerate(top5, 1)) + "</div></div>")
            st.caption("Individual entries only. Names are as recorded, so spelling differences can lower an athlete's count.")

        try:
            recs = records(load()[1], load_matches()[0])
        except Exception:
            recs = []
        if recs:
            section("Highlights", "Records and highlights", "Worked out from the results data.")
            html('<div class="wg"><div class="wg-recs">' + "".join(
                f'<div class="wg-rec"><span>{esc(l)}</span><b>{esc(v)}</b><small>{esc(dt)}</small></div>' for v, l, dt in recs) + "</div></div>")

    # ---- key stages ----
    section("Programme overview", "Key Stages of the Games")
    html('<div class="wg"><div class="wg-stages">' + "".join(
        f'<div class="wg-stage s{i}"><div class="dot">{i}</div><span>{ph}</span><h4>{t}</h4><p>{d}</p></div>'
        for i, (ph, t, d) in enumerate(STAGES, 1)) + "</div></div>")

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

    # ---- participating universities ----
    try:
        unis = load_universities()
    except Exception:
        unis = pd.DataFrame()
    if not unis.empty:
        n_c = unis.country[unis.country != ""].nunique()
        section("Participating universities", "Universities at WAUG 2026",
                f"{len(unis)} universities from {n_c} {'country' if n_c == 1 else 'countries'} took part in the Games.")
        def flag(c):
            return f'<img src="https://flagcdn.com/w80/{c.lower()}.png" alt="">' if len(c) == 2 else ""
        html('<div class="wg"><div class="wg-unis">' + "".join(
            f'<div class="wg-uni">{flag(r.country)}<div><b>{esc(r.code)}</b><span>{esc(r["name"])}</span></div></div>'
            for _, r in unis.iterrows()) + "</div></div>")

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
.wg-stack{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:.7rem;margin:.8rem 0 1rem}
.wg-tool{border:1px solid rgba(128,128,128,.35);border-top:4px solid #FFC72C;border-radius:12px;padding:.8rem 1rem}
.wg-tool small{display:block;text-transform:uppercase;letter-spacing:.08em;font-size:.7rem;opacity:.7}
.wg-tool b{font-family:'Fraunces',Georgia,serif;font-size:1.05rem}
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

    tools = [("Language", "Python"), ("App framework", "Streamlit"), ("Data processing", "pandas"), ("Charts", "Plotly"),
             ("API requests", "Requests"), ("Data source", "AlliSports Data API"), ("Typefaces", "Fraunces and Inter (Google Fonts)"),
             ("Flag images", "FlagCDN"), ("Version control", "Git and GitHub"), ("Code editor", "PyCharm")]
    html('<div class="wg"><div class="wg-eye" style="margin-top:1.4rem">Built with</div><div class="wg-stack">' + "".join(
        f'<div class="wg-tool"><small>{esc(k)}</small><b>{esc(v)}</b></div>' for k, v in tools) + "</div></div>")


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


HOST_CODE = "OAU"   # host institution (the Games were held on the OAU campus)


def _ord(n):
    n = int(n)
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _pct(x, d=0):
    return f"{x * 100:.{d}f}%"


REPORT_CSS = """
<style>
.wg-rhero{background:linear-gradient(135deg,#000080 0%,#0b1a94 55%,#1c2ba8 100%);color:#fff;border-radius:22px;padding:2.2rem 2.4rem;border:1px solid rgba(255,255,255,.12)}
.wg-rhero .eyebrow{color:#FFD34D;font-weight:700;letter-spacing:.14em;text-transform:uppercase;font-size:.72rem}
.wg-rhero .wg-h1{font-size:2.5rem;margin:.9rem 0 .8rem;color:#fff;max-width:46rem}
.wg-rhero p{color:rgba(255,255,255,.88);font-size:1.05rem;line-height:1.65;max-width:46rem;margin:0}
.wg-kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:.9rem;margin:1.4rem 0 .6rem}
.wg-kpi{border:1px solid rgba(255,255,255,.22);border-radius:14px;padding:1rem 1.1rem;background:rgba(255,255,255,.06)}
.wg-kpi b{display:block;font-family:'Fraunces',Georgia,serif;font-size:2.2rem;color:#FFD34D;line-height:1.1}
.wg-kpi span{display:block;font-size:.9rem;margin-top:.3rem}
.wg-kpi small{display:block;margin-top:.7rem;font-size:.66rem;letter-spacing:.1em;text-transform:uppercase;opacity:.7}
.wg-by{font-size:.82rem;opacity:.8;margin-top:.6rem}
.wg-h2.big{font-size:2rem;margin-top:3.2rem}
.wg-callout{border-left:4px solid #FFC72C;background:rgba(255,199,44,.13);border-radius:0 12px 12px 0;padding:.9rem 1.1rem;margin:.6rem 0 1rem}
.wg-pill{display:inline-block;font-size:.66rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;padding:.14rem .6rem;border-radius:999px;margin-right:.5rem;vertical-align:middle}
.wg-pill.r{background:#000080;color:#fff}.wg-pill.m{border:1px solid #B88700;color:#B88700}.wg-pill.a{background:#FFC72C;color:#000080}
.wg-short{margin:.4rem 0;padding-left:0;list-style:none}
.wg-short li{margin:.8rem 0;line-height:1.6}
.wg-ct{font-weight:700;font-size:1.05rem;margin-top:1rem}
.wg-cs{font-size:.72rem;letter-spacing:.06em;text-transform:uppercase;opacity:.65;margin-bottom:.3rem}
.wg-note{border-left:3px solid #FFC72C;padding:.3rem .9rem;margin:.4rem 0 .3rem;font-size:.95rem}
.wg-note b{font-size:.66rem;letter-spacing:.12em;text-transform:uppercase;color:#B88700;margin-right:.5rem}
.wg-stats3{display:grid;grid-template-columns:repeat(3,1fr);gap:.9rem;margin:1rem 0}
.wg-st{border:1px solid rgba(128,128,128,.35);border-top:4px solid #6C8CFF;border-radius:12px;padding:1rem 1.1rem}
.wg-st.g{border-top-color:#FFC72C}.wg-st.n{border-top-color:#9CA3AF}
.wg-st b{display:block;font-family:'Fraunces',Georgia,serif;font-size:1.9rem}
.wg-st span{display:block;font-weight:600}
.wg-st small{display:block;opacity:.75;margin-top:.3rem}
.wg-team{display:flex;gap:1rem;align-items:flex-start;border:1px solid rgba(128,128,128,.35);border-radius:14px;padding:1rem 1.2rem;max-width:30rem}
.wg-team .av{width:46px;height:46px;border-radius:50%;background:#000080;color:#fff;display:flex;align-items:center;justify-content:center;font-weight:700;flex:none}
.wg-team b{font-family:'Fraunces',Georgia,serif;font-size:1.15rem}
.wg-team em{display:block;color:#B88700;font-style:normal;font-size:.85rem;font-weight:600;margin:.1rem 0 .3rem}
.wg-team p{margin:0;opacity:.85;font-size:.92rem}
.wg-fine{border-top:1px solid rgba(128,128,128,.35);margin-top:2.5rem;padding-top:1rem;font-size:.85rem;line-height:1.7;opacity:.9}
@media(max-width:800px){.wg-kpis,.wg-stats3{grid-template-columns:1fr}.wg-rhero{padding:1.4rem}.wg-rhero .wg-h1{font-size:1.9rem}}
</style>
"""
PILL = {"results": '<span class="wg-pill r">Results</span>', "matches": '<span class="wg-pill m">Matches</span>',
        "calc": '<span class="wg-pill a">Calculated</span>'}


def rsec(n, title, answer, anchor=None):
    a = f' id="{anchor}"' if anchor else ""
    html(f'<div class="wg"><div class="wg-h2 big"{a}>{n}. {esc(title)}</div><div class="wg-callout">{answer}</div></div>')


def chead(title, sub=""):
    html(f'<div class="wg"><div class="wg-ct">{esc(title)}</div><div class="wg-cs">{esc(sub)}</div></div>')


def rnote(text):
    html(f'<div class="wg"><div class="wg-note"><b>What it shows</b>{text}</div></div>')


def howto(text):
    with st.expander("How to read this chart"):
        st.write(text)


def report():
    html(HOME_CSS)
    html(ABOUT_CSS)
    html(REPORT_CSS)
    try:
        table, det, ev, meta = load()
        mt = load_matches()[0]
    except Exception as err:
        st.error(f"Could not load the data: {err}")
        return
    d = det.copy()
    d["medal"] = d.medal.astype(str)
    t = table.sort_values("rank").reset_index(drop=True)
    if len(t) < 3:
        st.info("Not enough results yet for the report.")
        return
    T = int(t.total.sum())
    t["share"] = t.total / T
    n_s = len(t)
    lead, run = t.iloc[0], t.iloc[1]
    n_sports = d.sport.nunique()
    E = esc

    # ---------- computations ----------
    top1, top3, top5 = t.share.iloc[0], t.share.head(3).sum(), t.share.head(5).sum()
    eff = 1 / float((t.share ** 2).sum())
    cum = pd.DataFrame({"Rank": range(1, n_s + 1), "School": t.abbr, "Cumulative share": t.share.cumsum()})
    k50 = int((cum["Cumulative share"] >= 0.5).idxmax()) + 1
    q = t.set_index("abbr")[["university", "total", "gold"]].join(d.groupby("abbr").sport.nunique().rename("sports")).reset_index()
    q["gold_rate"] = q.gold / q.total
    r_b = float(q.total.corr(q.sports))
    strength = "strong" if r_b >= 0.7 else "moderate" if r_b >= 0.4 else "weak"
    elig = q[q.total >= 10].sort_values(["gold_rate", "total"], ascending=False)
    best = elig.iloc[0] if not elig.empty else None
    lq = q[q.abbr == lead.abbr].iloc[0]
    cnt = d.groupby(["abbr", "sport"]).size().unstack(fill_value=0)
    diff = (cnt.loc[lead.abbr] - cnt.loc[run.abbr]).sort_values(ascending=False)
    gap = int(lead.total - run.total)
    ahead, behind, level = int((diff > 0).sum()), int((diff < 0).sum()), int((diff == 0).sum())
    adds_up = int(diff.sum()) == gap
    top_two = ", ".join(f"{s} (+{int(v)})" for s, v in diff.head(2).items() if v > 0)
    host = t[t.abbr == HOST_CODE]

    off = "Official (gold first)"
    alt = t[["abbr", "university", "rank", "gold", "silver", "bronze", "total"]].copy().rename(columns={"rank": off})
    alt["Total medals"] = alt.total.rank(method="min", ascending=False).astype(int)
    alt["Points (3-2-1)"] = (3 * alt.gold + 2 * alt.silver + alt.bronze).rank(method="min", ascending=False).astype(int)
    alt["Golds only"] = alt.gold.rank(method="min", ascending=False).astype(int)
    alt_cols = ["Total medals", "Points (3-2-1)", "Golds only"]
    delta = alt[alt_cols].sub(alt[off], axis=0).abs()
    moved3 = int((delta.max(axis=1) >= 3).sum())
    stable_k = 0
    for k in (1, 2, 3):
        if all(set(alt[alt[c] <= k].abbr) == set(alt[alt[off] <= k].abbr) for c in alt_cols):
            stable_k = k
        else:
            break
    changed = ""
    if stable_k < 3:
        nxt = alt[alt[off] == stable_k + 1].iloc[0]
        wc = max(alt_cols, key=lambda c: abs(int(nxt[c]) - stable_k - 1))
        changed = f"{nxt.abbr} is {_ord(stable_k + 1)} officially but {_ord(nxt[wc])} by {wc.lower()}."
    big = alt.loc[delta.max(axis=1).idxmax()] if delta.max().max() > 0 else None
    bigcol = max(alt_cols, key=lambda c: abs(int(big[c]) - int(big[off]))) if big is not None else None

    fin = mt[(mt.status == "finished") & mt.score_a.notna() & mt.score_b.notna()].copy() if not mt.empty else mt
    if not fin.empty:
        fin["margin"] = (fin.score_a - fin.score_b).abs()
    bb = fin[fin.sport == "Basketball"] if not fin.empty else fin
    fb = fin[fin.sport == "Football"] if not fin.empty else fin

    chk = d.groupby(["abbr", "medal"]).size().unstack(fill_value=0).reindex(columns=["Gold", "Silver", "Bronze"], fill_value=0)
    tt = t.set_index("abbr")[["gold", "silver", "bronze"]]
    bad = int((chk.reindex(tt.index, fill_value=0).values != tt.values).any(axis=1).sum())
    check = ("The medals counted event by event reproduce the official medal table exactly." if bad == 0
             else f"{bad} school(s) differ between the event-level medals and the medal table, which can happen while results are provisional.")
    n_prov = int((ev["Status"] != "official").sum()) if (meta["source"] == "api" and "Status" in ev) else None
    stab = ("The top three places hold under every scoring rule I tried." if stable_k == 3 else
            f"The top {stable_k} {'place holds' if stable_k == 1 else 'places hold'} under every scoring rule I tried; {_ord(stable_k + 1)} place does not.")

    # ---------- hero ----------
    updated = meta["generatedAt"][:10] if meta.get("generatedAt") else "November 2026"
    html(f"""
    <div class="wg"><div class="wg-rhero"><div class="eyebrow">WAUG 2026 · Results analysis · Obafemi Awolowo University, Ile-Ife</div>
    <div class="wg-h1">{E(lead.abbr)} won by being everywhere: {int(lead.total)} medals in {int(lq.sports)} sports, but only {_pct(lq.gold_rate)} were gold.</div>
    <p>I took the results of the 15th West Africa University Games and asked why the medal table looks the way it does, not only what it shows.
    I tested how concentrated the medals were, whether volume or quality won them, what decided the lead, whether the ranking rule matters and how
    competitive the team games were. {E(stab)}</p>
    <div class="wg-kpis">
    <div class="wg-kpi"><b>{_pct(top3)}</b><span>of all {T} medals went to just three schools</span><small>Results</small></div>
    <div class="wg-kpi"><b>r = {r_b:.2f}</b><span>link between the sports a school medalled in and its total medals</span><small>Calculated</small></div>
    <div class="wg-kpi"><b>{ahead} of {ahead + behind + level}</b><span>sports where {E(lead.abbr)} won more medals than {E(run.abbr)}</span><small>Results</small></div>
    </div></div></div>""")
    b1, b2, b3, _x = st.columns([1.1, 1.3, 1.3, 2])
    b1.markdown('<a href="#what-i-did" style="display:inline-block;background:#FFC72C;color:#000080;font-weight:700;padding:.5rem 1rem;border-radius:10px;text-decoration:none">Read the report ↓</a>',
                unsafe_allow_html=True)
    b2.page_link(results_page, label="Explore the dashboard", icon="📊")
    b3.download_button("Download the data", t[["rank", "university", "abbr", "gold", "silver", "bronze", "total"]].to_csv(index=False),
                       "waug_2026_medal_table.csv", "text/csv")
    html(f'<div class="wg"><div class="wg-by">By Adelerin Samuel · Data: AlliSports Data API · updated {E(updated)}</div></div>')

    # ---------- in short ----------
    html('<div class="wg"><div class="wg-h2 big" style="margin-top:2.2rem">In short</div></div>')
    shorts = [
        f"{PILL['results']}<b>The medals were concentrated.</b> {E(lead.university)} took {_pct(top1)} of the {T} medals, the top three took {_pct(top3)}, "
        f"and half of all medals were won by just {k50} school{'s' if k50 != 1 else ''}.",
        f"{PILL['calc']}<b>Breadth, not conversion.</b> Total medals follow the number of sports a school medalled in (r = {r_b:.2f}). {E(lead.abbr)} led on volume but only "
        f"{_pct(lq.gold_rate)} of its medals were gold" + (f"; {E(best.abbr)} converted {_pct(best.gold_rate)} of its podiums into gold." if best is not None and best.abbr != lead.abbr else "."),
        f"{PILL['results']}<b>The lead is broad.</b> {E(lead.abbr)} finished {gap} medals ahead of {E(run.abbr)} and won more medals in {ahead} of {ahead + behind + level} sports"
        + (f", most of all in {E(top_two)}." if top_two else "."),
        f"{PILL['calc']}<b>The ranking is {'robust' if stable_k == 3 else 'partly sensitive to the rule'}.</b> {E(stab)} {E(changed)}",
    ]
    if not bb.empty:
        shorts.append(f"{PILL['matches']}<b>Team games.</b> Basketball games had a median margin of {bb.margin.median():.0f} points over {len(bb)} games"
                      + (f"; {_pct((fb.margin <= 1).mean())} of football games were decided by a goal or less." if not fb.empty else "."))
    html('<div class="wg"><ul class="wg-short">' + "".join(f"<li>{s}</li>" for s in shorts) + "</ul></div>")

    # ---------- 1. what I did ----------
    rsec(1, "What I did", "I read the official results, checked them against the medal table, then asked five questions of the data.", anchor="what-i-did")
    st.write(f"The Games were held on the OAU campus in Ile-Ife from 2 to 12 October 2026. The medal table ranks {n_s} universities but does not say what produced "
             "that ranking. I took the results straight from the AlliSports Data feed, kept every figure traceable to a recorded result, and judged each finding "
             "by asking what else could explain it. I keep the official ranking separate from the alternative scoring rules I use as checks.")
    html(f"""<div class="wg"><div class="wg-stats3">
    <div class="wg-st"><b>{T}</b><span>Medals analysed</span><small>{len(ev)} events across {n_sports} sports, from the official results.</small></div>
    <div class="wg-st g"><b>{n_s}</b><span>Medal-winning schools</span><small>Ranked gold first, then silver, then bronze.</small></div>
    <div class="wg-st n"><b>{len(fin)}</b><span>Finished matches</span><small>Football and basketball from the feed, other sports from a saved snapshot.</small></div></div></div>""")
    with st.expander("Read more: how I collected and checked the data"):
        st.markdown("1. **Collected** the medal table, the event results (with the athletes on each podium) and the match scorelines from the AlliSports Data API.\n"
                    "2. **Filtered** out events that do not count towards the medal table and disputed events, so that totals match the official table.\n"
                    "3. **Standardised** athlete entries: team events are labelled as such, and entries with no name are marked as not listed.\n"
                    f"4. **Reconciled** the event-level medals with the medal table. {check}\n"
                    "5. **Joined** the match data: football and basketball come from the feed, and other sports use a saved snapshot of 5 to 11 October.")
        if n_prov is not None:
            st.caption(f"{n_prov} of {len(ev)} events were still provisional when this page was built.")

    # ---------- 2. concentration ----------
    rsec(2, "How concentrated were the medals?", f"{_pct(top3)} of all medals went to three schools, and the leader alone took {_pct(top1)}.")
    st.markdown(f"{PILL['results']} {n_s} schools won medals, but the concentration equals only about **{eff:.1f} equally sized schools**. "
                f"Half of all medals were won by the top {k50} school{'s' if k50 != 1 else ''}.", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        chead("How quickly the medals add up", "Cumulative share of all medals · schools ranked by medals")
        fig = px.line(cum, x="Rank", y="Cumulative share", markers=True, hover_name="School", color_discrete_sequence=["#FFC72C"])
        fig.add_hline(y=0.5, line_dash="dot", line_color="#9CA3AF", annotation_text="half of all medals")
        fig.update_layout(yaxis_tickformat=".0%", xaxis_title="School rank", yaxis_title=None, margin=dict(t=10))
        st.plotly_chart(fig, width="stretch")
        rnote(f"The top three hold {_pct(top3)} of medals and the top five {_pct(top5)}.")
        howto("Each point adds the next school's share of medals to the schools above it. The steeper the start, the more concentrated the medals.")
    with c2:
        chead("Who won what", "Medals by type · ten highest-ranked schools")
        top10 = t.head(10).melt(id_vars="abbr", value_vars=["gold", "silver", "bronze"], var_name="Medal", value_name="Count")
        top10["Medal"] = top10.Medal.str.capitalize()
        fig = px.bar(top10, y="abbr", x="Count", color="Medal", orientation="h", color_discrete_map=MEDAL_COLORS,
                     category_orders={"abbr": t.head(10).abbr.tolist()[::-1], "Medal": ["Gold", "Silver", "Bronze"]})
        fig.update_layout(yaxis_title=None, legend_title=None, margin=dict(t=10))
        st.plotly_chart(fig, width="stretch")
        rnote(f"{E(lead.abbr)} won {int(lead.gold)} gold, {int(lead.silver)} silver and {int(lead.bronze)} bronze; {_pct(lq.gold_rate)} of its medals were gold.")
        howto("Each bar is one school, split into gold, silver and bronze medals. Longer bars mean more medals in total.")

    # ---------- 3. volume or quality ----------
    rsec(3, "Did schools win through volume or quality?",
         f"Volume. Medals track breadth (r = {r_b:.2f}); {E(lead.abbr)} led on totals, not on the share of golds.")
    st.markdown(f"{PILL['calc']} For every school I compared total medals (volume), the share that were gold (quality) and the number of sports medalled in (breadth). "
                f"Across the {n_s} schools the correlation between breadth and total medals is **r = {r_b:.2f}**, a {strength} relationship.", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        chead("Volume against quality", "Each bubble is a school · size = sports medalled in")
        fig = px.scatter(q, x="total", y="gold_rate", size="sports", text="abbr", hover_name="university", color_discrete_sequence=["#6C8CFF"], size_max=32)
        fig.update_traces(textposition="top center")
        fig.update_layout(xaxis_title="Total medals", yaxis_title="Share of medals that were gold", yaxis_tickformat=".0%", margin=dict(t=10))
        st.plotly_chart(fig, width="stretch")
        rnote(f"{E(lead.abbr)} is far to the right (most medals) but low on the vertical axis ({_pct(lq.gold_rate)} gold).")
        howto("Right means more medals. Up means a larger share of those medals were gold. Bigger bubbles are schools that medalled in more sports.")
    with c2:
        chead("Who turned podiums into gold", "Share of medals that were gold · schools with 10 or more medals")
        if best is not None:
            e2 = elig.sort_values("gold_rate")
            fig = px.bar(e2, y="abbr", x="gold_rate", orientation="h", color_discrete_sequence=["#FFC72C"], text=e2.gold_rate.map(lambda v: f"{v:.0%}"))
            fig.update_layout(xaxis_tickformat=".0%", xaxis_title=None, yaxis_title=None, margin=dict(t=10))
            st.plotly_chart(fig, width="stretch")
            rnote(f"{E(best.abbr)} converted {_pct(best.gold_rate)} of its {int(best.total)} medals into gold.")
        else:
            st.caption("No school has 10 or more medals yet.")
        howto("Each bar is the share of a school's medals that were gold. A high bar means the school won the top step more often.")

    # ---------- 4. what decided the lead ----------
    rsec(4, f"What decided the lead of {lead.abbr} over {run.abbr}?",
         f"{ahead} of {ahead + behind + level} sports went to {E(lead.abbr)}, so the {gap}-medal lead is broad, not one big result.")
    st.markdown(f"{PILL['results']} I counted each school's medals in every sport and subtracted. "
                + ("The sport-by-sport differences add up exactly to the overall gap. " if adds_up else "")
                + (f"The biggest contributions came from {E(top_two)}. " if top_two else "")
                + (f"The host, {E(host.iloc[0].abbr)}, ranked {int(host.iloc[0]['rank'])} with {_pct(host.iloc[0].share)} of all medals." if not host.empty else ""),
                unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    dd = diff.reset_index()
    dd.columns = ["Sport", "Difference"]
    dd["Direction"] = dd.Difference.map(lambda v: f"{lead.abbr} ahead" if v > 0 else (f"{run.abbr} ahead" if v < 0 else "Level"))
    with c1:
        chead("Where the gap came from", f"Medals won by {lead.abbr} minus medals won by {run.abbr}")
        fig = px.bar(dd, x="Sport", y="Difference", color="Direction",
                     color_discrete_map={f"{lead.abbr} ahead": "#6C8CFF", f"{run.abbr} ahead": "#FFC72C", "Level": "#9CA3AF"})
        fig.update_layout(xaxis_title=None, legend_title=None, margin=dict(t=10))
        st.plotly_chart(fig, width="stretch")
        rnote(f"{E(lead.abbr)} was ahead in {ahead} sports, {E(run.abbr)} in {behind}, and {level} were level.")
        howto(f"A bar above zero is a sport where {lead.abbr} won more medals than {run.abbr}; below zero is the reverse.")
    with c2:
        chead("The two schools side by side", "Medals by sport")
        both = cnt.loc[[lead.abbr, run.abbr]].T.reset_index().melt(id_vars="sport", var_name="School", value_name="Medals")
        fig = px.bar(both, x="sport", y="Medals", color="School", barmode="group", color_discrete_sequence=["#6C8CFF", "#FFC72C"])
        fig.update_layout(xaxis_title=None, legend_title=None, margin=dict(t=10))
        st.plotly_chart(fig, width="stretch")
        rnote("The leader's bars are taller in most sports, so the lead does not depend on a single event.")
        howto("Each pair of bars is one sport. Compare the heights to see which school won more medals there.")

    # ---------- 5. scoring rule ----------
    rsec(5, "Does the ranking depend on the scoring rule?", stab)
    st.markdown(f"{PILL['calc']} I re-ranked every school under three alternatives: total medals, a 3-2-1 points system and golds only (ties share a rank). "
                + (f"{E(changed)} " if changed else "")
                + (f"{moved3} of {n_s} schools move three or more places under at least one alternative; the largest move is {E(big.abbr)}, "
                   f"{_ord(big[off])} officially but {_ord(big[bigcol])} by {E(bigcol.lower())}." if big is not None and moved3 else ""), unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        chead("Rank under each rule", "Ten highest-ranked schools")
        st.dataframe(alt.head(10)[["abbr", off] + alt_cols].rename(columns={"abbr": "School"}), hide_index=True, width="stretch")
        rnote("Schools that keep the same number across the row are unaffected by the choice of rule.")
        howto("Each row is a school. Each column is its rank under a different scoring rule. 1 is best.")
    with c2:
        chead("How much each school moves", "Rank by scoring rule · lower is better")
        long = alt.head(10).melt(id_vars="abbr", value_vars=[off] + alt_cols, var_name="Rule", value_name="Rank")
        fig = px.line(long, x="Rule", y="Rank", color="abbr", markers=True)
        fig.update_yaxes(autorange="reversed")
        fig.update_layout(legend_title=None, xaxis_title=None, margin=dict(t=10))
        st.plotly_chart(fig, width="stretch")
        rnote("Lines that cross show schools that swap places when the rule changes.")
        howto("Each line follows one school across the four rules. A flat line means its rank does not change.")

    # ---------- 6. team games ----------
    rsec(6, "How competitive were the team games?",
         (f"Basketball games were often one-sided (median margin {bb.margin.median():.0f} points)." if not bb.empty else "There are not enough finished matches yet."))
    st.markdown(f"{PILL['matches']} For finished football and basketball games I looked at the score margin. Football games level after normal time are shown separately because "
                "penalties then decide the winner.", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        if not bb.empty:
            chead("Basketball margins", f"Points between the teams · {len(bb)} games")
            fig = px.histogram(bb, x="margin", nbins=10, color_discrete_sequence=["#6C8CFF"])
            fig.update_layout(xaxis_title="Points margin", yaxis_title="Games", margin=dict(t=10))
            st.plotly_chart(fig, width="stretch")
            rnote(f"{_pct((bb.margin >= 20).mean())} of games were decided by 20 points or more.")
            howto("Each bar counts games with a margin in that range. Bars on the right are one-sided games.")
    with c2:
        if not fb.empty:
            chead("Football margins", f"Goals between the teams · {len(fb)} games")
            fig = px.histogram(fb, x="margin", nbins=6, color_discrete_sequence=["#FFC72C"])
            fig.update_layout(xaxis_title="Goals margin", yaxis_title="Games", margin=dict(t=10))
            st.plotly_chart(fig, width="stretch")
            rnote(f"{_pct((fb.margin <= 1).mean())} of games were decided by a single goal or were level at full time; {int(fb.pens_a.notna().sum())} went to penalties.")
            howto("Each bar counts games with that goal margin. A margin of 0 means the game was level after normal time.")

    # ---------- 7. try it yourself ----------
    rsec(7, "Try it yourself", "Change the points for each medal and see how the top of the table moves.")
    s1, s2, s3 = st.columns(3)
    gp = s1.slider("Points for gold", 1, 10, 3, key="rp_g")
    sp = s2.slider("Points for silver", 0, 10, 2, key="rp_s")
    bp = s3.slider("Points for bronze", 0, 10, 1, key="rp_b")
    pts = t.gold * gp + t.silver * sp + t.bronze * bp
    mine = pd.DataFrame({"School": t.abbr, "Official rank": t["rank"], "Your rank": pts.rank(method="min", ascending=False).astype(int), "Points": pts})
    mine["Places gained"] = mine["Official rank"] - mine["Your rank"]
    mine = mine.sort_values(["Your rank", "Official rank"])
    leaders = ", ".join(mine[mine["Your rank"] == 1].School)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Leader", leaders)
    m2.metric("Points for the leader", int(mine.Points.max()))
    m3.metric("Top 3 same as official", "Yes" if set(mine[mine["Your rank"] <= 3].School) == set(t.head(3).abbr) else "No")
    m4.metric("Schools moving 3+ places", int((mine["Places gained"].abs() >= 3).sum()))
    st.dataframe(mine.head(10), hide_index=True, width="stretch")

    # ---------- 8. limits ----------
    rsec(8, "What this does not show", "The results describe patterns. They cannot prove causes.")
    st.markdown("- **Association, not cause.** The link between breadth and medals does not show why. Home advantage cannot be tested without data on entries and team sizes.\n"
                "- **Match analysis is partial.** Only football and basketball come from the feed, and the sample is small.\n"
                "- **Results can still change.** Provisional results are not confirmed until the WAUG Technical Committee signs them off.\n"
                "- **Athlete counts are approximate.** Team events list no names and names are spelled in more than one way.")

    # ---------- 9. next steps ----------
    rsec(9, "What I would do next", "Four changes would make the next analysis much stronger.")
    st.markdown((f"1. **Show two rankings side by side.** The official gold-first table and a total-medals view differ in {_ord(stable_k + 1)} place, so both tell a reader something.\n"
                 if stable_k < 3 else "1. **Keep the gold-first table and publish a total-medals view beside it,** so readers can see the ranking holds.\n")
                + "2. **Record entries per school and per sport.** Without them, medals per entrant (efficiency) cannot be measured.\n"
                  "3. **Give every athlete an ID.** Counts would no longer depend on how a name is spelled.\n"
                  "4. **Record team members for team events,** so the athlete analysis can include them.")

    # ---------- 10. who built this ----------
    rsec(10, "Who built this", "One person built the analysis and the dashboard.")
    html('<div class="wg"><div class="wg-team"><div class="av">AS</div><div><b>Adelerin Samuel</b><em>Analysis & dashboard</em>'
         '<p>Collected the data from the AlliSports Data API, built the analysis and designed the dashboard.</p></div></div></div>')

    # ---------- appendix ----------
    html('<div class="wg"><div class="wg-h2 big">Appendix: method and detail</div></div>')
    with st.expander("A · What I measured, and why"):
        st.markdown("- **Medal share:** a school's medals divided by all medals. It shows who holds the medals.\n"
                    "- **Effective number of schools:** 1 divided by the sum of squared shares. It shows how many equally sized schools would give the same concentration.\n"
                    "- **Gold rate:** gold medals divided by total medals. It measures quality.\n"
                    "- **Breadth:** the number of sports a school won at least one medal in.\n"
                    "- **Correlation (r):** how closely two measures move together, from -1 to 1. It is an association, not a cause.\n"
                    "- **Rank under a rule:** each school's position when scored by a different rule, with ties sharing a rank.\n"
                    "- **Margin:** the absolute difference in score between the two teams in a finished game.")
    with st.expander("B · Decisions and checks"):
        for a, b in [("Data source", "Results, medals, winners and scorelines come from the AlliSports Data API, which marks results as provisional or official."),
                     ("Reconciliation", check),
                     ("Which events count", "Events that do not count towards the medal table, and disputed events, are excluded so totals match the official table."),
                     ("Ranking rule", "Gold first, then silver, then bronze, with equal medals sharing a rank. It follows the Games' own table and is tested against three alternatives."),
                     ("Athlete analysis", "Only individual entries are used. Team events list no names, and relays and doubles are excluded."),
                     ("Draws and penalties", "Draws are counted separately from wins and losses. A game settled on penalties is a win for the shoot-out winner."),
                     ("Match coverage", "Football and basketball come from the feed. Other sports use a saved snapshot of 5 to 11 October.")]:
            st.markdown(f"**{a}.** {b}")
    with st.expander("C · Full limitations"):
        st.markdown("- The analysis is descriptive. It cannot measure efficiency or prove causes.\n"
                    "- Medals counted here follow the official table, so events that do not count towards it are not included.\n"
                    "- Football and basketball come from the live feed. Other sports come from a snapshot of 5 to 11 October, so match analysis is limited to football and basketball.\n"
                    "- Some results may be provisional and can change.\n"
                    "- Athlete names are spelled in more than one way in the source, so an athlete's count can be slightly low.\n"
                    "- The match sample is small, so match findings describe these games and not Games in general.")
    with st.expander("D · Data sources and coverage"):
        st.markdown("- **AlliSports Data API** (data.allimediahub.com): medal table, event results with athletes, match scorelines, sports and universities.\n"
                    f"- **Fetched:** {E(meta['generatedAt'][:16].replace('T', ' ') + ' UTC') if meta.get('generatedAt') else 'from the saved snapshot'}. Responses are cached for about a minute.\n"
                    "- **Saved snapshot:** match results for 5 to 11 October for sports the feed does not carry, used only to fill those sports.")
    with st.expander("E · Full medal table"):
        st.dataframe(t[["rank", "university", "abbr", "gold", "silver", "bronze", "total"]].rename(columns={"rank": "Rank", "university": "University", "abbr": "Code"}),
                     hide_index=True, width="stretch")
    with st.expander("F · Ranking under every rule"):
        st.dataframe(alt[["abbr", "university", off] + alt_cols].rename(columns={"abbr": "Code", "university": "University"}), hide_index=True, width="stretch")

    html(f"""<div class="wg"><div class="wg-fine">
    <b>WAUG 2026 results report:</b> analysis of the medal table and match results of the 15th West Africa University Games, Obafemi Awolowo University, Ile-Ife.<br>
    <b>Built and researched by:</b> Adelerin Samuel.<br>
    <b>Data:</b> AlliSports Data API (data.allimediahub.com). Provisional results are not yet confirmed by the WAUG Technical Committee.<br>
    Analysis in Python (pandas); dashboard built with Streamlit and Plotly.</div></div>""")


def data_page():
    html(HOME_CSS)
    html(ABOUT_CSS)
    html("""<div class="wg"><div class="wg-band"><span class="wg-eyebrow">Data</span>
    <div class="wg-h1">The data behind the report</div></div>
    <div class="wg-lead">Every figure in the report comes from the files below. Download them to check the numbers or run your own analysis.</div></div>""")
    try:
        table, det, ev, meta = load()
        mt = load_matches()[0]
    except Exception as err:
        st.error(f"Could not load the data: {err}")
        return
    t = table.sort_values("rank")
    sets = [("Medal table", t[["rank", "university", "abbr", "gold", "silver", "bronze", "total"]], "waug_2026_medal_table.csv"),
            ("Every medal", det.assign(medal=det.medal.astype(str))[["university", "abbr", "medal", "sport", "event", "athlete"]], "waug_2026_medals.csv"),
            ("Event winners", build_winners(det), "waug_2026_event_winners.csv"),
            ("Matches", mt, "waug_2026_matches.csv")]
    for col, (name, df, fn) in zip(st.columns(len(sets)), sets):
        col.metric(name, f"{len(df):,} rows")
        col.download_button(f"Download {name.lower()}", df.to_csv(index=False), fn, "text/csv", key=f"dl_{fn}")
    section("Data dictionary", "What each column means")
    dd = {"Medal table": [("rank", "Official rank, gold first then silver then bronze"), ("university / abbr", "University name and short code"),
                          ("gold, silver, bronze, total", "Medal counts")],
          "Every medal": [("university / abbr", "Winning university"), ("medal", "Gold, Silver or Bronze"), ("sport / event", "Sport and event"),
                          ("athlete", "Athlete name, 'Team' for team events, or a dash when no name is listed")],
          "Event winners": [("sport / category / event", "Sport, Men/Women/Mixed and event name"), ("gold / silver / bronze", "Winners as 'Name (CODE)'; two bronzes are separated by a semicolon")],
          "Matches": [("date / time", "Date and time in Nigeria time (WAT)"), ("sport / category / stage", "Sport, Men/Women/Mixed and stage of the competition"),
                      ("team_a / team_b, score_a / score_b", "The two sides and their scores"), ("sets", "Set, quarter or half-time scores"),
                      ("pens_a / pens_b", "Penalty shoot-out scores when used"), ("winner / status", "A or B, and finished, live or scheduled")]}
    for name, rows in dd.items():
        with st.expander(name):
            st.dataframe(pd.DataFrame(rows, columns=["Column", "Meaning"]), hide_index=True, width="stretch")
    section("Sources and coverage", "Where the data comes from")
    st.markdown("- **AlliSports Data API** (data.allimediahub.com): medal table, results with athletes, football and basketball matches, sports and universities.\n"
                "- **Saved snapshot:** match results for 5 to 11 October for sports the feed does not carry.\n"
                f"- **Last fetched:** {meta['generatedAt'][:16].replace('T', ' ') + ' UTC' if meta.get('generatedAt') else 'from the saved snapshot'}.\n"
                "- Provisional results are not yet confirmed by the WAUG Technical Committee.")
    st.caption("Data: AlliSports Data.")


def results():
    try:
        table, det, ev, meta = load()
    except Exception as err:
        st.error(str(err))
        st.stop()
    if meta["source"] == "api":
        st.caption("Last updated " + meta["generatedAt"][:16].replace("T", " ") + " UTC"
                   + (" · includes provisional results" if meta["includesProvisional"] else ""))

    col_logo, col_title = st.columns([0.05, 0.95])

    with col_logo:
        st.image("waug-2026-logo.png", width=70)
    with col_title:
        st.title("West African University Games 2026")
    st.caption("Medal table and event results · data from the AlliSports Data API")

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

    tab_labels = ["Medal table", "Sports", "Athletes", "Events & data", "Event winners", "Matches"]
    goto = st.session_state.get("goto_tab")   # kept (not removed) so the tabs keep their identity on every rerun
    kw = {"default": goto} if goto in tab_labels and "default" in inspect.signature(st.tabs).parameters else {}
    tab1, tab2, tab4, tab5, tab7, tab6 = st.tabs(tab_labels, **kw)

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
report_page = st.Page(report, title="Report", icon="📄", default=True)
overview_page = st.Page(overview, title="Games overview", icon="🏟️", url_path="overview")
data_page_ = st.Page(data_page, title="Data", icon="🗂️", url_path="data")
results_page = st.Page(results, title="Dashboard", icon="📊", url_path="results")
about_page = st.Page(about, title="About", icon="ℹ️", url_path="about")
try:
    nav = st.navigation([report_page, results_page, overview_page, data_page_, about_page], position="top")
except TypeError:  # older Streamlit: navigation goes in the sidebar
    nav = st.navigation([report_page, results_page, overview_page, data_page_, about_page])
nav.run()
