#!/usr/bin/env bash
# Sweep predictors x traces through the CBP simulator, one log per run.
#
#   Build first (clean = force relink after lib/ changes):
#       (cd cbp2025 && make clean && make)
#   Run:
#       scripts/sweep.sh
#
# Override via env vars:
#   PREDICTORS  space-separated list (default: all)
#   TRACES      space-separated .gz paths (default: a small int/fp/infra subset)
#   N           instruction cap for quick passes; 0 = full trace (default 0)
#   JOBS        parallelism (default: all cores; lower it if RAM-constrained)
#   OUT         output dir (default: results)
#
# Examples:
#   N=5000000 scripts/sweep.sh                          # fast capped pass
#   TRACES="$(ls traces/int/*.gz)" JOBS=8 scripts/sweep.sh
set -uo pipefail
cd "$(dirname "$0")/.."                    # -> cbp2025/

CBP=./cbp
[ -x "$CBP" ] || { echo "cbp not built. run: (cd cbp2025 && make clean && make)"; exit 1; }

PREDICTORS="${PREDICTORS:-bimodal gshare twolevel perceptron tage tageimproved reference}"
TRACES="${TRACES:-$(ls traces/int/int_0_trace.gz  traces/int/int_1_trace.gz \
                       traces/fp/fp_0_trace.gz    traces/fp/fp_1_trace.gz \
                       traces/infra/infra_0_trace.gz 2>/dev/null)}"
N="${N:-0}"
JOBS="${JOBS:-$( (command -v nproc >/dev/null 2>&1 && nproc) || sysctl -n hw.ncpu )}"
OUT="${OUT:-results}"

[ -n "$TRACES" ] || { echo "no traces found (run pull_traces.sh first?)"; exit 1; }
mkdir -p "$OUT"

NFLAG=""; [ "$N" -gt 0 ] && NFLAG="-n $N"
export CBP OUT NFLAG

echo "predictors: $PREDICTORS"
echo "traces:     $(echo "$TRACES" | wc -w | tr -d ' ') file(s)"
echo "jobs:       $JOBS   cap: $([ "$N" -gt 0 ] && echo "$N insts" || echo full)"
echo "output:     $OUT/"
start=$(date +%s)

# one line per (predictor, trace); xargs runs JOBS of them at a time
for p in $PREDICTORS; do
  for t in $TRACES; do
    printf '%s %s\n' "$p" "$t"
  done
done | xargs -P "$JOBS" -n2 bash -c '
    p="$1"; t="$2"; base=$(basename "$t" .gz)
    if $CBP -p "$p" $NFLAG "$t" > "$OUT/${p}__${base}.log" 2>&1; then
      echo "  ok   ${p}__${base}"
    else
      echo "  FAIL ${p}__${base}"
    fi
  ' _

echo "elapsed: $(( $(date +%s) - start ))s   logs -> $OUT/"
echo "next: python3 scripts/parse.py && python3 scripts/plot.py"
