#!/usr/bin/env bash
# Full diagnostic sweep: MPKI logs + per-window time-series (COLLECT_DATA).
#
# Builds the *instrumented* binary (make COLLECT=1) and, per predictor x trace,
# emits two files:
#   results/<pred>__<trace>.log         MPKI (same as sweep.sh)
#   results/<pred>__<trace>.series.csv  windowed over-time stats
#
# Collection hooks now cover the TAGE variants (alloc/u-dist + tag false-match)
# AND the tagless bimodal/gshare/twolevel (alias_* columns). Perceptron and the
# reference carry no hooks, so they produce a .log but no .series.csv (expected).
#
# Env overrides: PREDICTORS, TRACES, N (inst cap; 0=full), WINDOW (branches/row),
#                JOBS, OUT.  Then:  python3 scripts/parse.py ; python3 scripts/plot_series.py
#
# NOTE: this leaves ./cbp as the COLLECT build. Run `make clean && make` to
# restore the fast MPKI sweep binary.
set -uo pipefail
cd "$(dirname "$0")/.."                     # -> cbp2025/

PREDICTORS="${PREDICTORS:-bimodal gshare twolevel perceptron tage tageimproved reference}"
TRACES="${TRACES:-$(ls traces/int/int_0_trace.gz  traces/int/int_1_trace.gz \
                       traces/fp/fp_0_trace.gz    traces/fp/fp_1_trace.gz \
                       traces/infra/infra_0_trace.gz 2>/dev/null)}"
N="${N:-0}"
WINDOW="${WINDOW:-1000000}"
JOBS="${JOBS:-$( (command -v nproc >/dev/null 2>&1 && nproc) || sysctl -n hw.ncpu )}"
OUT="${OUT:-results}"

[ -n "$TRACES" ] || { echo "no traces found (run pull_traces.sh first?)"; exit 1; }
mkdir -p "$OUT"

echo "building instrumented binary (make clean && make COLLECT=1)..."
make clean >/dev/null 2>&1
make COLLECT=1 >/dev/null 2>&1 || { echo "build failed"; exit 1; }
[ -x ./cbp ] || { echo "cbp missing after build"; exit 1; }

NFLAG=""; [ "$N" -gt 0 ] && NFLAG="-n $N"
export OUT NFLAG WINDOW

echo "predictors: $PREDICTORS"
echo "traces:     $(echo "$TRACES" | wc -w | tr -d ' ') file(s)   window: $WINDOW   jobs: $JOBS"
echo "cap:        $([ "$N" -gt 0 ] && echo "$N insts" || echo full)"
start=$(date +%s)

for p in $PREDICTORS; do
  for t in $TRACES; do
    printf '%s %s\n' "$p" "$t"
  done
done | xargs -P "$JOBS" -n2 bash -c '
    p="$1"; t="$2"; base=$(basename "$t" .gz)
    if COLLECT_OUT="$OUT/${p}__${base}.series.csv" COLLECT_WINDOW="$WINDOW" \
         ./cbp -p "$p" $NFLAG "$t" > "$OUT/${p}__${base}.log" 2>&1; then
      echo "  ok   ${p}__${base}"
    else
      echo "  FAIL ${p}__${base}"
    fi
  ' _

echo "elapsed: $(( $(date +%s) - start ))s   -> $OUT/"
echo "next:  python3 scripts/parse.py        # MPKI table/csv"
echo "       python3 scripts/plot_series.py   # over-time line charts"
echo "restore fast binary:  make clean && make"
