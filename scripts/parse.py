#!/usr/bin/env python3
"""Parse cbp sweep logs -> CSV.

Reads results/<predictor>__<trace>.log (as produced by sweep.sh), pulls the
CondDirect measurement line, and writes results.csv. Pure stdlib.

  python3 scripts/parse.py [results_dir] [out.csv]
"""
import csv, glob, os, re, sys
from collections import defaultdict

results_dir = sys.argv[1] if len(sys.argv) > 1 else "results"
out_csv     = sys.argv[2] if len(sys.argv) > 2 else "results.csv"

# e.g.  CondDirect          386769      16528   4.2734%   5.7478
cond = re.compile(r"CondDirect\s+(\d+)\s+(\d+)\s+([\d.]+)%\s+([\d.]+)")
inst = re.compile(r"instructions\s*=\s*(\d+)")

rows = []
for path in sorted(glob.glob(os.path.join(results_dir, "*.log"))):
    name = os.path.basename(path)[:-4]            # strip ".log"
    if "__" not in name:
        continue
    predictor, trace = name.split("__", 1)
    text = open(path, errors="replace").read()
    m = cond.search(text)
    if not m:
        print(f"WARN  no CondDirect line in {name} (crashed / incomplete?)", file=sys.stderr)
        continue
    numbr, mispbr, mr, mpki = m.groups()
    im = inst.search(text)
    rows.append(dict(predictor=predictor, trace=trace,
                     instructions=(im.group(1) if im else ""),
                     numbr=numbr, mispbr=mispbr, mr=mr, mpki=mpki))

with open(out_csv, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["predictor", "trace", "instructions",
                                      "numbr", "mispbr", "mr", "mpki"])
    w.writeheader()
    w.writerows(rows)

print(f"wrote {len(rows)} rows -> {out_csv}")

# text summary: mean MPKI per predictor (best first)
agg = defaultdict(list)
for r in rows:
    agg[r["predictor"]].append(float(r["mpki"]))
if agg:
    print("\nmean MPKI per predictor:")
    for p in sorted(agg, key=lambda k: sum(agg[k]) / len(agg[k])):
        v = agg[p]
        print(f"  {p:<14} {sum(v)/len(v):8.3f}   (n={len(v)})")
