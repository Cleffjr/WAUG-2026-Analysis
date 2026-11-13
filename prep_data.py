"""Parse the extracted medal-table .doc text into two tidy CSVs.
Usage: extract-text <file>.doc > data/medal_table_raw.txt ; python prep_data.py"""
import re, pandas as pd
raw = open("data/medal_table_raw.txt", encoding="utf-8").read()
lines = raw.split("\n")

# ---- medal table (one long tab-separated line) ----
tbl_line = next(l for l in lines if l.startswith("Rank\tUniversity"))
rows = []
for r in tbl_line.split("\t\t")[1:]:
    c = r.split("\t")
    if len(c) == 6 and re.match(r"\d+(ST|ND|RD|TH)", c[0]):
        m = re.match(r"(.*) \(([^)]+)\)$", c[1])
        rows.append(dict(rank=int(re.match(r"\d+", c[0]).group()), university=m.group(1),
                         abbr=m.group(2), gold=int(c[2]), silver=int(c[3]), bronze=int(c[4]), total=int(c[5])))
pd.DataFrame(rows).to_csv("data/medal_table.csv", index=False)

# ---- per-school medal details (regex over the whole text: schools may share a line) ----
body = raw.split("MEDALS BY SCHOOL", 1)[1]
parts = re.split(r"\d+(?:ST|ND|RD|TH)\s+(.+?) \(([^)]+)\)\s", body)
det = []
for i in range(1, len(parts), 3):
    school = parts[i]
    for r in parts[i + 2].split("\t\t"):
        c = r.split("\t")
        c[0] = c[0].split("\n")[-1]
        if len(c) >= 4 and c[0] in ("Gold", "Silver", "Bronze"):
            det.append(dict(university=school, medal=c[0], sport=c[1], event=c[2], athlete=c[3].split("\n")[0]))
pd.DataFrame(det).to_csv("data/medal_details.csv", index=False)
print(len(rows), "schools,", len(det), "medal rows")
