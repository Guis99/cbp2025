#!/usr/bin/env python3
"""Grouped-bar MPKI chart from results.csv.

  pip install matplotlib        # (in the .venv)
  python3 scripts/plot.py [results.csv] [mpki.png]
"""
import csv, sys
from collections import defaultdict

csv_in  = sys.argv[1] if len(sys.argv) > 1 else "results.csv"
out_png = sys.argv[2] if len(sys.argv) > 2 else "results/mpki.png"

data = defaultdict(dict)                       # data[predictor][trace] = mpki
for r in csv.DictReader(open(csv_in)):
    data[r["predictor"]][r["trace"]] = float(r["mpki"])

preds  = sorted(data)
traces = sorted({t for d in data.values() for t in d})
if not preds or not traces:
    sys.exit("no data in " + csv_in)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

x = list(range(len(traces)))
w = 0.8 / len(preds)
fig, ax = plt.subplots(figsize=(max(8, 1.4 * len(traces)), 5))
for i, p in enumerate(preds):
    ys = [data[p].get(t, 0.0) for t in traces]
    xs = [xi + i * w for xi in x]
    ax.bar(xs, ys, w, label=p)

ax.set_xticks([xi + 0.4 - w / 2 for xi in x])
ax.set_xticklabels(traces, rotation=30, ha="right")
ax.set_ylabel("MPKI (CondDirect)")
ax.set_title("Branch predictor MPKI by trace")
ax.legend(fontsize=8, ncol=2)
fig.tight_layout()
fig.savefig(out_png, dpi=120)
print(f"wrote {out_png}")
