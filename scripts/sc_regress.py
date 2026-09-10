#!/usr/bin/env python3
"""SC regression harness: compare a sweep_ti run against the latest pinned metrics.

Workflow (driven interactively by the operator):
  1. run the sweep (or reuse results/), extract per-trace CondDirect MPKI,
  2. compare against the LATEST pin in scripts/baselines/sc_history.json,
  3. if it BEATS the latest, the operator decides whether to pin it,
  4. optionally commit the code change first, then --pin writes the new entry.

Primary metric: SC-on CondDirect MPKI per trace (`on`), aggregated as the
geometric mean over traces common to both runs. Lower is better. `off` (baseline
TAGE) is recorded as an invariance guard: it must not move unless you changed
baseline TAGE, so a drift flags a leak out of the `_use_sc` path OR a config
(cap/window) mismatch that makes the comparison apples-to-oranges.

Robust to added traces: traces are auto-discovered from the log pairs in the
results dir; comparison is over the intersection with the pin, and cur-only
(new) / pin-only (missing) traces are reported, not errored.

Usage:
  scripts/sc_regress.py                       # extract results/, compare to latest pin
  scripts/sc_regress.py --run                 # run sweep_ti.sh (full) first, then compare
  scripts/sc_regress.py --run --cap 10000000  # capped run
  scripts/sc_regress.py --pin --note "..."    # append current metrics as a new pin
  scripts/sc_regress.py --show                # print the pin history

Only stdlib. Break%/overrides are shown when SC_STATS was compiled in, else "-".
"""
import argparse, json, math, os, re, subprocess, sys, datetime, glob

HERE = os.path.dirname(os.path.abspath(__file__))
CBP  = os.path.dirname(HERE)                       # -> cbp2025/
HISTORY = os.path.join(HERE, "baselines", "sc_history.json")
SWEEP   = os.path.join(HERE, "sweep_ti.sh")
OFF_PREFIX, ON_PREFIX = "tageimproved__", "tageimproved_sc__"
EPS = 1e-4                                          # float-print noise; sim is deterministic

# ---------------------------------------------------------------- log parsing
_COND = re.compile(r"^CondDirect\s+(\d+)\s+(\d+)\s+\S+\s+([\d.]+)")   # NumBr Misp mr mpki
_OVR  = re.compile(r"overrode (\d+) times")

def _parse_log(path):
    """Return (numbr, misp, mpki) from the CondDirect line, or None."""
    try:
        with open(path) as f:
            for line in f:
                m = _COND.match(line)
                if m:
                    return int(m.group(1)), int(m.group(2)), float(m.group(3))
    except FileNotFoundError:
        return None
    return None

def _parse_overrides(path):
    try:
        with open(path) as f:
            for line in f:
                m = _OVR.search(line)
                if m:
                    return int(m.group(1))
    except FileNotFoundError:
        pass
    return None

def extract(results_dir):
    """Auto-discover off/on log pairs -> {trace: metrics}."""
    out = {}
    for off_path in sorted(glob.glob(os.path.join(results_dir, OFF_PREFIX + "*.log"))):
        base = os.path.basename(off_path)[len(OFF_PREFIX):-len(".log")]
        on_path = os.path.join(results_dir, ON_PREFIX + base + ".log")
        if not os.path.exists(on_path):
            continue
        off, on = _parse_log(off_path), _parse_log(on_path)
        if not off or not on:
            continue
        off_numbr, off_misp, off_mpki = off
        on_numbr,  on_misp,  on_mpki  = on
        rec = {"off": off_mpki, "on": on_mpki,
               "delta_pct": (100.0 * (on_mpki - off_mpki) / off_mpki) if off_mpki else 0.0}
        ov = _parse_overrides(on_path)
        if ov is not None and ov > 0:
            net = on_misp - off_misp                 # breaks - fixes
            breaks = (ov + net) / 2.0
            rec.update(overrides=ov, breaks=round(breaks),
                       fixes=round(ov - breaks), break_pct=100.0 * breaks / ov)
        out[base] = rec
    return out

def geomean(xs):
    xs = [x for x in xs if x > 0]
    return math.exp(sum(math.log(x) for x in xs) / len(xs)) if xs else 0.0

# ---------------------------------------------------------------- history I/O
def load_history():
    if not os.path.exists(HISTORY):
        return {"meta": {"metric": "CondDirect on_mpki (SC enabled), geomean over common traces"},
                "history": []}
    with open(HISTORY) as f:
        return json.load(f)

def save_history(h):
    os.makedirs(os.path.dirname(HISTORY), exist_ok=True)
    with open(HISTORY, "w") as f:
        json.dump(h, f, indent=2)
        f.write("\n")

def git_state():
    def run(*a):
        try:
            return subprocess.check_output(["git", *a], cwd=CBP, stderr=subprocess.DEVNULL).decode().strip()
        except Exception:
            return ""
    return {"commit": run("rev-parse", "--short", "HEAD") or "unknown",
            "dirty": bool(run("status", "--porcelain"))}

# ---------------------------------------------------------------- compare
def compare(cur, pin_entry):
    """Return a dict describing cur vs the pinned entry (or None if no pin)."""
    cur_geo_all = geomean([m["on"] for m in cur.values()])
    if pin_entry is None:
        return {"verdict": "NO_BASELINE", "cur_geo_all": cur_geo_all,
                "new": sorted(cur), "missing": [], "rows": [], "leaks": []}
    pin = pin_entry["traces"]
    common = sorted(set(cur) & set(pin))
    new     = sorted(set(cur) - set(pin))
    missing = sorted(set(pin) - set(cur))
    rows, leaks = [], []
    for t in common:
        c, p = cur[t], pin[t]
        if abs(c["off"] - p["off"]) > EPS:
            leaks.append((t, p["off"], c["off"]))
        rows.append({"trace": t, "off": c["off"], "on": c["on"],
                     "pin_on": p["on"], "d_on": c["on"] - p["on"],
                     "delta_pct": c["delta_pct"]})
    cur_geo = geomean([cur[t]["on"] for t in common])
    pin_geo = geomean([pin[t]["on"] for t in common])
    if not common:
        verdict = "NO_COMMON"
    elif cur_geo < pin_geo - EPS:
        verdict = "BEATS"
    elif cur_geo > pin_geo + EPS:
        verdict = "WORSE"
    else:
        verdict = "SAME"
    return {"verdict": verdict, "cur_geo": cur_geo, "pin_geo": pin_geo,
            "cur_geo_all": cur_geo_all, "rows": rows, "new": new,
            "missing": missing, "leaks": leaks, "n_common": len(common)}

def print_report(cur, cmp, pin_entry, config):
    print("=" * 72)
    if pin_entry is None:
        print("SC regression: NO PIN YET — this run can become baseline #1")
    else:
        print(f"SC regression: current vs latest pin "
              f"[{pin_entry['date']} {pin_entry['commit']}"
              f"{' (dirty)' if pin_entry.get('dirty') else ''}]  «{pin_entry.get('note','')}»")
        pc = pin_entry.get("config", {})
        mm = "OK" if (pc.get("cap") == config["cap"] and pc.get("window") == config["window"]) else "MISMATCH"
        print(f"config: cap={config['cap']} window={config['window']}   "
              f"pin: cap={pc.get('cap')} window={pc.get('window')}   [{mm}]")
    print("-" * 72)
    hdr = f"{'trace':<18}{'off':>9}{'on':>9}"
    if pin_entry is not None:
        hdr += f"{'Δon':>10}{'on delta%':>11}"
    print(hdr)
    src = cmp["rows"] if pin_entry is not None else [{"trace": t, **cur[t]} for t in sorted(cur)]
    for r in src:
        line = f"{r['trace']:<18}{r['off']:>9.4f}{r['on']:>9.4f}"
        if pin_entry is not None:
            line += f"{r['d_on']:>+10.4f}{r['delta_pct']:>+10.2f}%"
        else:
            line += f"{r['delta_pct']:>+10.2f}%"
        print(line)
    if cmp["new"]:
        print(f"  new traces (no pin baseline): {', '.join(cmp['new'])}")
    if cmp.get("missing"):
        print(f"  missing (in pin, not run):    {', '.join(cmp['missing'])}")
    if cmp.get("leaks"):
        print("  ** OFF-INVARIANCE LEAK (baseline TAGE moved or config mismatch): **")
        for t, po, co in cmp["leaks"]:
            print(f"       {t}: off {po:.4f} -> {co:.4f}")
    print("-" * 72)
    if pin_entry is not None:
        d = 100.0 * (cmp["cur_geo"] - cmp["pin_geo"]) / cmp["pin_geo"] if cmp["pin_geo"] else 0.0
        print(f"geomean(on) over {cmp['n_common']} common: {cmp['cur_geo']:.4f}  "
              f"(pin {cmp['pin_geo']:.4f})  {d:+.2f}%")
    else:
        print(f"geomean(on) over {len(cur)} traces: {cmp['cur_geo_all']:.4f}")
    print(f"VERDICT: {cmp['verdict']}")
    print("=" * 72)

# ---------------------------------------------------------------- pin
def make_entry(cur, note, config, commit=None):
    # Prefer an operator-supplied commit hash (so we never invoke git); fall
    # back to a read-only git query only when none is given.
    if commit:
        commit_hash, dirty = commit, False
    else:
        g = git_state(); commit_hash, dirty = g["commit"], g["dirty"]
    common_all = geomean([m["on"] for m in cur.values()])
    n_pos = sum(1 for m in cur.values() if m["delta_pct"] < 0)
    return {"date": datetime.date.today().isoformat(),
            "commit": commit_hash, "dirty": dirty, "note": note,
            "config": config,
            "aggregate": {"geomean_on": round(common_all, 6),
                          "mean_delta_pct": round(sum(m["delta_pct"] for m in cur.values()) / len(cur), 4),
                          "n_traces": len(cur), "n_net_positive": n_pos},
            "traces": {t: {k: round(v, 6) if isinstance(v, float) else v
                           for k, v in m.items()} for t, m in cur.items()}}

# ---------------------------------------------------------------- sweep
def run_sweep(cap, window, traces):
    cmd = ["bash", SWEEP, "-s", "both", "-w", str(window)]
    if cap and int(cap) > 0:
        cmd += ["-n", str(cap)]
    for t in (traces or []):
        cmd += ["-t", t]
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, cwd=CBP, check=True)

# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true", help="run sweep_ti.sh before comparing")
    ap.add_argument("--cap", default="0", help="instruction cap for --run and to record (0=full)")
    ap.add_argument("--window", default="250000")
    ap.add_argument("--traces", nargs="*", help="trace shorthands for --run (default: sweep_ti's set)")
    ap.add_argument("--results", default=os.path.join(CBP, "results"))
    ap.add_argument("--pin", action="store_true", help="append current metrics as a new pin")
    ap.add_argument("--note", default="", help="note for the pin entry")
    ap.add_argument("--commit", default=None, help="commit hash to record (operator-supplied; avoids invoking git)")
    ap.add_argument("--show", action="store_true", help="print pin history and exit")
    args = ap.parse_args()

    hist = load_history()
    if args.show:
        for e in hist["history"]:
            print(f"{e['date']}  {e['commit']}{'*' if e.get('dirty') else ' '}  "
                  f"geo={e['aggregate']['geomean_on']:.4f}  "
                  f"{e['aggregate']['n_net_positive']}/{e['aggregate']['n_traces']} pos  "
                  f"cap={e['config'].get('cap')}  «{e['note']}»")
        return 0

    if args.run:
        run_sweep(args.cap, args.window, args.traces)

    cur = extract(args.results)
    if not cur:
        sys.exit(f"no off/on log pairs found in {args.results} (run the sweep first)")

    config = {"cap": ("full" if str(args.cap) in ("0", "") else int(args.cap)),
              "window": int(args.window)}
    latest = hist["history"][-1] if hist["history"] else None
    cmp = compare(cur, latest)

    if args.pin:
        hist["history"].append(make_entry(cur, args.note, config, args.commit))
        save_history(hist)
        print(f"pinned: {config}  geomean(on)={geomean([m['on'] for m in cur.values()]):.4f}  "
              f"-> {HISTORY}")
        return 0

    print_report(cur, cmp, latest, config)
    return {"BEATS": 0, "SAME": 0, "NO_BASELINE": 0, "NO_COMMON": 0,
            "WORSE": 3}.get(cmp["verdict"], 0) or (4 if cmp.get("leaks") else 0)

if __name__ == "__main__":
    sys.exit(main() or 0)
