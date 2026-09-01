#!/usr/bin/env python3
"""Line charts of the COLLECT_DATA over-time series.

Reads results/<pred>__<trace>.series.csv (from sweep_full.sh) and writes one
PNG per metric, faceted by trace, one line per predictor.

  pip install matplotlib        # (in the .venv)
  python3 scripts/plot_series.py [results_dir]
"""
import csv, glob, os, sys
from collections import defaultdict

results = sys.argv[1] if len(sys.argv) > 1 else "results"
FRAC_METRICS = {"alloc_success_rate", "u0", "u1", "u2", "u3", "tag_alias_rate", "alias_rate", "idx_collision_rate"}

# runs[(pred, trace)] = {col: [values...], "window": [...]}
runs = {}
metrics = []
for path in sorted(glob.glob(os.path.join(results, "*.series.csv"))):
    name = os.path.basename(path)[:-len(".series.csv")]
    if "__" not in name:
        continue
    pred, trace = name.split("__", 1)
    rows = list(csv.DictReader(open(path)))
    if not rows:
        continue
    # prov_*/provmr_* provider bins are drawn by plot_provider.py.
    cols = [c for c in rows[0] if c not in ("window", "branches") and not c.startswith("prov")]
    metrics = cols  # same across files
    s = {c: [float(r[c]) for r in rows] for c in cols}
    s["window"] = [int(r["window"]) for r in rows]
    runs[(pred, trace)] = s

if not runs:
    sys.exit("no *.series.csv found in " + results + " (run sweep_full.sh first)")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

preds  = sorted({p for p, _ in runs})
traces = sorted({t for _, t in runs})

for metric in metrics:
    n = len(traces)
    fig, axes = plt.subplots(1, n, figsize=(4 * n, 3.6), squeeze=False, sharey=True)
    for j, tr in enumerate(traces):
        ax = axes[0][j]
        for p in preds:
            s = runs.get((p, tr))
            if s and metric in s:
                ax.plot(s["window"], s[metric], marker=".", ms=3, label=p)
        ax.set_title(tr, fontsize=9)
        ax.set_xlabel("window")
        ax.grid(True, alpha=0.3)
    axes[0][0].set_ylabel(metric)
    axes[0][0].legend(fontsize=7)
    if metric in FRAC_METRICS:
        axes[0][0].set_ylim(-0.02, 1.02)   # rates live in [0,1]; avoids degenerate single-point autoscale
    fig.suptitle(f"{metric} over time")
    fig.tight_layout()
    out = os.path.join(results, f"series_{metric}.png")
    fig.savefig(out, dpi=110)
    plt.close(fig)
    print("wrote", out)
