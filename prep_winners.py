"""Build data/event_winners.csv (gold / silver / bronze names for every event) from the medal-table-with-winners .docx.
Usage: extract-text <file>.docx > data/medal_table_with_winners.txt ; python prep_winners.py"""
import re, pandas as pd

rows, school = [], None
for l in open("data/medal_table_with_winners.txt", encoding="utf-8"):
    h = re.match(r"\*\*\d+(?:ST|ND|RD|TH)\s+(.+?) \(([^)]+)\)\*\*", l)
    if h:
        school = h.group(1); continue
    m = re.match(r"\| \*\*(Gold|Silver|Bronze)\*\* \| (.*?) \| (.*?) \| (.*?) \|\s*$", l)
    if m and school:
        rows.append((school,) + m.groups())
d = pd.DataFrame(rows, columns=["university", "medal", "sport", "event", "athlete"])
abbr = pd.read_csv("data/medal_table.csv").set_index("university").abbr


def label(r):
    who = {"Team": "Team", "–": "Name not listed"}.get(r.athlete, r.athlete)
    return f"{who} ({abbr[r.university]})"


d["label"] = d.apply(label, axis=1)
d["category"] = d.event.str.split().str[0].where(d.event.str.split().str[0].isin(["Men", "Women", "Mixed"]), "Other")
d["event_name"] = d.event.where(d.category == "Other", d.event.str.split(n=1).str[1])
out = (d.groupby(["sport", "category", "event_name", "medal"])["label"].agg("; ".join).unstack("medal")
         .reindex(columns=["Gold", "Silver", "Bronze"]).fillna("").reset_index()
         .rename(columns={"event_name": "event", "Gold": "gold", "Silver": "silver", "Bronze": "bronze"}))
out.to_csv("data/event_winners.csv", index=False)
print(len(out), "events;", (out.gold == "").sum(), "without gold,", (out.silver == "").sum(), "without silver")
