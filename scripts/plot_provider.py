#!/usr/bin/env python3
"""Stacked-area proportion of the provider over time, binned by history length.

Reads results/<pred>__<trace>.series.csv and, for predictors carrying the
prov_h* columns (the TAGE variants), draws one stacked-area chart per
(trace, predictor): x = window, y = fraction of predictions served by each
history-length bin (stacks to ~1). Binning by history length -- not logical
bank -- lets TAGE and TAGEImproved be compared on a fair axis even though their
bank geometries differ.

  pip install matplotlib        # (in the .venv)
  python3 scripts/plot_provider.py [results_dir]
"""
import csv, glob, os, sys

results = sys.argv[1] if len(sys.argv) > 1 else "results"

# Column order == stacking order (shortest history at the bottom).
BINS   = ["prov_h0", "prov_h4", "prov_h8", "prov_h16", "prov_h32", "prov_h64",
          "prov_h128", "prov_h256", "prov_h512", "prov_h1024", "prov_h1024p"]
LABELS = ["base(0)", "1-4", "5-8", "9-16", "17-32", "33-64",
          "65-128", "129-256", "257-512", "513-1024", "1025+"]

# Coarse history-length groups for the mispredict bar/lift views, aggregated
# from the fine BINS above (edit freely). (label, [fine-bin indices], color).
GROUPS = [
    ("base",    [0],          "#4caf50"),   # hl 0  (green)
    ("1-16",    [1, 2, 3],    "#e5534b"),   # small histories (red)
    ("17-64",   [4, 5],       "#5b8def"),   # (blue)
    ("65-256",  [6, 7],       "#8b5cf6"),   # (purple)
    ("257+",    [8, 9, 10],   "#f5c542"),   # long histories (yellow)
]

# runs[(pred, trace)] = {bin: [values...], "window": [...]}
runs = {}
for path in sorted(glob.glob(os.path.join(results, "*.series.csv"))):
    name = os.path.basename(path)[:-len(".series.csv")]
    if "__" not in name:
        continue
    pred, trace = name.split("__", 1)
    rows = list(csv.DictReader(open(path)))
    if not rows or BINS[0] not in rows[0]:
        continue  # predictor without provider data (tagless / reference)
    s = {b: [float(r[b]) for r in rows] for b in BINS}
    if not any(any(v) for v in s.values()):
        continue  # all-zero -> nothing provided (skip)
    s["window"] = [int(r["window"]) for r in rows]
    s["branches"] = [float(r["branches"]) for r in rows]
    # per-bin miss rate (provmr_*), if the run carries it (older CSVs may not).
    mrcol = {b: b.replace("prov_", "provmr_", 1) for b in BINS}
    if all(mrcol[b] in rows[0] for b in BINS):
        s["mr"] = {b: [float(r[mrcol[b]]) for r in rows] for b in BINS}
    runs[(pred, trace)] = s

if not runs:
    sys.exit("no provider (prov_h*) data in " + results + " (run sweep_full.sh first)")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

preds  = sorted({p for p, _ in runs})
traces = sorted({t for _, t in runs})
cmap   = plt.get_cmap("viridis")
colors = [cmap(i / (len(BINS) - 1)) for i in range(len(BINS))]

nrows, ncols = len(traces), len(preds)
fig, axes = plt.subplots(nrows, ncols, figsize=(5 * ncols, 3.0 * nrows),
                         squeeze=False)
for r, tr in enumerate(traces):
    for c, pr in enumerate(preds):
        ax = axes[r][c]
        s = runs.get((pr, tr))
        if not s:
            ax.set_visible(False)
            continue
        x = s["window"]
        ax.stackplot(x, *[s[b] for b in BINS], colors=colors, labels=LABELS)
        ax.set_ylim(0, 1)
        ax.set_xlim(min(x), max(x))
        ax.set_title(f"{pr} / {tr}", fontsize=9)
        if c == 0:
            ax.set_ylabel("provider fraction")
        if r == nrows - 1:
            ax.set_xlabel("window")

handles, labels = axes[0][0].get_legend_handles_labels()
fig.legend(handles, labels, title="history len", loc="center right", fontsize=7)
fig.suptitle("provider distribution over time (binned by history length)")
fig.tight_layout(rect=[0, 0, 0.9, 1])
out = os.path.join(results, "series_provider_stacked.png")
fig.savefig(out, dpi=110)
print("wrote", out)
plt.close(fig)

# --- companion view: per-bin fractions as lines on a LOG y-axis. Stacking hides
# the small (long-history) bins; log lines make a 0.002->0.02 move legible and
# comparable across time and across predictors. Zero-valued windows are masked
# (gaps) since log has no zero.
FLOOR = 1e-4
fig2, axes2 = plt.subplots(nrows, ncols, figsize=(5 * ncols, 3.0 * nrows),
                           squeeze=False, sharey=True)
for r, tr in enumerate(traces):
    for c, pr in enumerate(preds):
        ax = axes2[r][c]
        s = runs.get((pr, tr))
        if not s:
            ax.set_visible(False)
            continue
        x = s["window"]
        for b, lab, col in zip(BINS, LABELS, colors):
            y = [v if v > 0 else float("nan") for v in s[b]]
            if all(v != v for v in y):        # all-NaN (bin never provided) -> skip
                continue
            ax.plot(x, y, color=col, label=lab, lw=1.3, marker=".", ms=3)
        ax.set_yscale("log")
        ax.set_ylim(FLOOR, 1.0)
        ax.set_xlim(min(x), max(x))
        ax.grid(True, which="both", alpha=0.25)
        ax.set_title(f"{pr} / {tr}", fontsize=9)
        if c == 0:
            ax.set_ylabel("provider fraction (log)")
        if r == nrows - 1:
            ax.set_xlabel("window")

# legend from the subplot with the most bins drawn (base always provides)
h2, l2 = max((ax.get_legend_handles_labels() for ax in axes2.flat if ax.get_visible()),
             key=lambda hl: len(hl[0]), default=([], []))
fig2.legend(h2, l2, title="history len", loc="center right", fontsize=7)
fig2.suptitle("provider distribution over time (log scale, per history-length bin)")
fig2.tight_layout(rect=[0, 0, 0.9, 1])
out2 = os.path.join(results, "series_provider_log.png")
fig2.savefig(out2, dpi=110)
print("wrote", out2)
plt.close(fig2)

# --- view #3: MR-colored stacked bands. Band THICKNESS = provider share (as in
# the stacked plot), band COLOR = that bin's miss rate this window (RdYlGn_r:
# green = accurate, red = inaccurate). One picture of where the prediction load
# sits AND whether it is healthy -- a fat red band is a provider carrying a lot
# of traffic badly; a fat green band is load handled well. Needs provmr_* data.
mr_runs = {k: v for k, v in runs.items() if "mr" in v}
if not mr_runs:
    print("skip mr-band plot: no provmr_* columns (re-run sweep with the updated build)")
else:
    import numpy as np
    from matplotlib import colors as mcolors, cm as mcm
    MRMAP = plt.get_cmap("RdYlGn_r")
    # one shared normalization -> colors comparable across subplots/predictors.
    allmr = [mr for s in mr_runs.values()
             for b in BINS
             for sh, mr in zip(s[b], s["mr"][b]) if sh > 0]
    vmax = max(allmr) if allmr else 0.5
    vmax = max(vmax, 1e-3)
    norm = mcolors.Normalize(0.0, vmax)

    fig3, axes3 = plt.subplots(nrows, ncols, figsize=(5 * ncols, 3.0 * nrows),
                               squeeze=False)
    for r, tr in enumerate(traces):
        for c, pr in enumerate(preds):
            ax = axes3[r][c]
            s = runs.get((pr, tr))
            if not s or "mr" not in s:
                ax.set_visible(False)
                continue
            x = np.asarray(s["window"], float)
            share = np.asarray([s[b] for b in BINS])        # (nbins, nwin)
            mr    = np.asarray([s["mr"][b] for b in BINS])  # (nbins, nwin)
            cum = np.vstack([np.zeros(len(x)), np.cumsum(share, axis=0)])
            nb, nw = share.shape
            for bi in range(nb):
                lo, hi = cum[bi], cum[bi + 1]
                for wi in range(nw - 1):
                    if (hi[wi] - lo[wi]) <= 0 and (hi[wi + 1] - lo[wi + 1]) <= 0:
                        continue  # zero-thickness segment -> nothing to draw
                    ax.fill_between(x[wi:wi + 2], lo[wi:wi + 2], hi[wi:wi + 2],
                                    color=MRMAP(norm(mr[bi, wi])), linewidth=0)
            # label bands that are visibly thick at the right edge (color != identity)
            for bi in range(nb):
                if cum[bi + 1, -1] - cum[bi, -1] >= 0.03:
                    ax.text(x[-1], (cum[bi, -1] + cum[bi + 1, -1]) / 2,
                            " " + LABELS[bi], va="center", ha="left", fontsize=6)
            ax.set_ylim(0, 1)
            ax.set_xlim(x.min(), x.max())
            ax.set_title(f"{pr} / {tr}", fontsize=9)
            if c == 0:
                ax.set_ylabel("provider share (thickness)")
            if r == nrows - 1:
                ax.set_xlabel("window")

    sm = mcm.ScalarMappable(norm=norm, cmap=MRMAP)
    sm.set_array([])
    fig3.subplots_adjust(right=0.88)
    cbar = fig3.colorbar(sm, ax=axes3.ravel().tolist(), fraction=0.025, pad=0.02)
    cbar.set_label("bin miss rate")
    fig3.suptitle("provider share (band thickness) colored by miss rate (band color)")
    out3 = os.path.join(results, "series_provider_mrband.png")
    fig3.savefig(out3, dpi=110)
    print("wrote", out3)
    plt.close(fig3)

# --- view #4: mispredicts over time as STACKED BARS, coarse history groups.
# Bar height = total mispredicts that epoch (varies over time); segments = each
# group's mispredict count. Reconstructed from the CSV: miss_count[bin] =
# provmr[bin] * prov[bin] * branches (branches = providers that window).
def group_miss_mass(s):
    """per-bin miss mass (∝ miss count / window), keyed by fine bin."""
    return {b: np.asarray(s[b]) * np.asarray(s["mr"][b]) for b in BINS}

if mr_runs:
    fig4, axes4 = plt.subplots(nrows, ncols, figsize=(5 * ncols, 3.0 * nrows),
                               squeeze=False)
    for r, tr in enumerate(traces):
        for c, pr in enumerate(preds):
            ax = axes4[r][c]
            s = runs.get((pr, tr))
            if not s or "mr" not in s:
                ax.set_visible(False)
                continue
            x = np.asarray(s["window"], float)
            br = np.asarray(s["branches"], float)
            mm = group_miss_mass(s)                     # miss mass per fine bin
            bottom = np.zeros(len(x))
            for lab, idxs, col in GROUPS:
                gcount = sum(mm[BINS[i]] for i in idxs) * br   # miss counts
                ax.bar(x, gcount, bottom=bottom, width=1.0, color=col,
                       label=lab, edgecolor="none")
                bottom += gcount
            ax.set_xlim(x.min() - 0.5, x.max() + 0.5)
            ax.set_ylim(0, None)
            ax.set_title(f"{pr} / {tr}", fontsize=9)
            if c == 0:
                ax.set_ylabel("mispredicts / epoch")
            if r == nrows - 1:
                ax.set_xlabel("window")
    h4, l4 = axes4[0][0].get_legend_handles_labels()
    fig4.legend(h4, l4, title="history len", loc="center right", fontsize=8)
    fig4.suptitle("mispredicts over time by history-length group (raw counts)")
    fig4.tight_layout(rect=[0, 0, 0.9, 1])
    out4 = os.path.join(results, "series_provider_mispred_counts.png")
    fig4.savefig(out4, dpi=110)
    print("wrote", out4)
    plt.close(fig4)

# --- view #5: mispredict LIFT = (group's share of mispredicts) / (group's share
# of providers). >1 means the group owns a bigger slice of the mispredicts than
# of the predictions -- i.e. disproportionately responsible, correcting for how
# often it provides. (Equivalently: group miss rate / overall miss rate.)
if mr_runs:
    fig5, axes5 = plt.subplots(nrows, ncols, figsize=(5 * ncols, 3.0 * nrows),
                               squeeze=False, sharey=True)
    for r, tr in enumerate(traces):
        for c, pr in enumerate(preds):
            ax = axes5[r][c]
            s = runs.get((pr, tr))
            if not s or "mr" not in s:
                ax.set_visible(False)
                continue
            x = np.asarray(s["window"], float)
            prov = {b: np.asarray(s[b]) for b in BINS}
            mm = group_miss_mass(s)
            total_mm = sum(mm[b] for b in BINS)          # per-window miss mass
            for lab, idxs, col in GROUPS:
                gprov = sum(prov[BINS[i]] for i in idxs)  # provider share
                gmm = sum(mm[BINS[i]] for i in idxs)      # group miss mass
                with np.errstate(divide="ignore", invalid="ignore"):
                    miss_share = np.where(total_mm > 0, gmm / total_mm, np.nan)
                    lift = np.where(gprov > 0, miss_share / gprov, np.nan)
                ax.plot(x, lift, color=col, label=lab, lw=1.5, marker=".", ms=3)
            ax.axhline(1.0, color="k", lw=0.8, ls="--", alpha=0.6)
            ax.set_yscale("log")
            ax.set_xlim(x.min(), x.max())
            ax.grid(True, which="both", alpha=0.25)
            ax.set_title(f"{pr} / {tr}", fontsize=9)
            if c == 0:
                ax.set_ylabel("mispredict lift (miss share / prov share)")
            if r == nrows - 1:
                ax.set_xlabel("window")
    h5, l5 = axes5[0][0].get_legend_handles_labels()
    fig5.legend(h5, l5, title="history len", loc="center right", fontsize=8)
    fig5.suptitle("mispredict lift  (>1 = group causes more misses than its provider share)")
    fig5.tight_layout(rect=[0, 0, 0.9, 1])
    out5 = os.path.join(results, "series_provider_mispred_lift.png")
    fig5.savefig(out5, dpi=110)
    print("wrote", out5)
    plt.close(fig5)
