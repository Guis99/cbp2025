#!/usr/bin/env bash
# Focused instrumented sweep for TAGEImproved only, with a statistical-corrector
# (SC) on/off toggle so you can A/B the corrector against the baseline.
#
# Builds the COLLECT_DATA binary and runs ./cbp -p tageimproved over one or more
# traces, emitting for each (variant x trace):
#   results/<label>__<trace>.log         MPKI
#   results/<label>__<trace>.series.csv  windowed over-time stats
# where <label> is "tageimproved" (SC off) or "tageimproved_sc" (SC on) so the
# plot scripts overlay the two as separate series automatically. Skips the full
# sweep_full.sh predictor grid.
#
# Usage:
#   scripts/sweep_ti.sh [-s on|off|both] [-n INSTS] [-t TRACE]... [-w WINDOW] [-o OUT] [-j JOBS] [-k]
#
#   -s MODE    statistical corrector: off | on | both  (default both)
#   -n INSTS   instruction cap; 0/omitted = full trace
#   -t TRACE   trace to run (repeatable). Accepts a full .gz path OR a shorthand
#              like int_0 / fp_1 / infra_0 (-> traces/<class>/<name>_trace.gz).
#              Default: int_0 int_1 fp_0 fp_1 infra_0.
#   -w WINDOW  branches per series row (default 250000)
#   -o OUT     output dir (default results)
#   -j JOBS    parallelism (default all cores)
#   -k         keep the COLLECT build as ./cbp (default: restore fast binary at end)
#
# Env vars SC / N / WINDOW / OUT / JOBS still work as fallback defaults.
#
# The SC toggle sets TI_SC=0/1 per run; make_predictor() in my_cond_branch_predictor.h
# reads it and passes use_sc to the TAGEImproved constructor, so "on" enables the
# statistical corrector and "off" is the baseline.
#
# NOTE: rebuilds ./cbp as the instrumented (make COLLECT=1) binary. Unless -k is
# given, the fast MPKI binary is restored with `make clean && make` on exit.
set -uo pipefail
cd "$(dirname "$0")/.."                      # -> cbp2025/

SC="${SC:-both}"
N="${N:-0}"
WINDOW="${WINDOW:-250000}"
OUT="${OUT:-results}"
JOBS="${JOBS:-$( (command -v nproc >/dev/null 2>&1 && nproc) || sysctl -n hw.ncpu )}"
KEEP=0
TRACE_ARGS=()

while getopts "s:n:t:w:o:j:kh" opt; do
  case "$opt" in
    s) SC="$OPTARG" ;;
    n) N="$OPTARG" ;;
    t) TRACE_ARGS+=("$OPTARG") ;;
    w) WINDOW="$OPTARG" ;;
    o) OUT="$OPTARG" ;;
    j) JOBS="$OPTARG" ;;
    k) KEEP=1 ;;
    h) sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "try: $0 -h" >&2; exit 2 ;;
  esac
done

# SC variants to run, as "<TI_SC value> <output label>" pairs.
case "$SC" in
  off)  VARIANTS=("0 tageimproved") ;;
  on)   VARIANTS=("1 tageimproved_sc") ;;
  both) VARIANTS=("0 tageimproved" "1 tageimproved_sc") ;;
  *) echo "bad -s: '$SC' (use: off | on | both)" >&2; exit 2 ;;
esac

# Resolve each -t into a real .gz path: full path as-is, else shorthand
# int_0 -> traces/int/int_0_trace.gz (class = text before first underscore).
resolve_trace() {
  local a="$1"
  if [ -f "$a" ]; then echo "$a"; return 0; fi
  local cls="${a%%_*}"
  local p="traces/$cls/${a}_trace.gz"
  if [ -f "$p" ]; then echo "$p"; return 0; fi
  return 1
}

TRACES=()
if [ "${#TRACE_ARGS[@]}" -gt 0 ]; then
  for a in "${TRACE_ARGS[@]}"; do
    if r=$(resolve_trace "$a"); then TRACES+=("$r")
    else echo "trace not found: $a" >&2; exit 1; fi
  done
else
  for a in int_0 int_1 fp_0 fp_1 infra_0; do
    r=$(resolve_trace "$a") && TRACES+=("$r")
  done
fi
[ "${#TRACES[@]}" -gt 0 ] || { echo "no traces found (run pull_traces.sh first?)"; exit 1; }
mkdir -p "$OUT"

echo "building instrumented binary (make clean && make COLLECT=1)..."
make clean >/dev/null 2>&1
make COLLECT=0 >/dev/null 2>&1 || { echo "build failed"; exit 1; }
[ -x ./cbp ] || { echo "cbp missing after build"; exit 1; }

NFLAG=""; [ "$N" -gt 0 ] && NFLAG="-n $N"
export OUT NFLAG WINDOW

echo "predictor:  tageimproved"
echo "SC mode:    $SC   (labels: $(printf '%s ' "${VARIANTS[@]#* }"))"
echo "traces:     ${#TRACES[@]} file(s)   window: $WINDOW   jobs: $JOBS"
echo "cap:        $([ "$N" -gt 0 ] && echo "$N insts" || echo full)"
start=$(date +%s)

# one line per (SC variant, trace): "<TI_SC> <label> <trace>"; xargs runs -n3.
for v in "${VARIANTS[@]}"; do
  read -r scval label <<< "$v"
  for t in "${TRACES[@]}"; do
    printf '%s %s %s\n' "$scval" "$label" "$t"
  done
done | xargs -P "$JOBS" -n3 bash -c '
    scval="$1"; label="$2"; t="$3"; base=$(basename "$t" .gz)
    if TI_SC="$scval" COLLECT_OUT="$OUT/${label}__${base}.series.csv" COLLECT_WINDOW="$WINDOW" \
         ./cbp -p tageimproved $NFLAG "$t" > "$OUT/${label}__${base}.log" 2>&1; then
      echo "  ok   ${label}__${base}"
    else
      echo "  FAIL ${label}__${base}"
    fi
  ' _

echo "elapsed: $(( $(date +%s) - start ))s   -> $OUT/"

# --- SC on-vs-off comparison (CondDirect conditional-branch MPKI, from the logs) ---
mpki_of() { grep -E '^CondDirect' "$1" 2>/dev/null | awk '{print $5}' | head -1; }
misp_of() { grep -E '^CondDirect' "$1" 2>/dev/null | awk '{print $3}' | head -1; }
overrides_of() { grep -oE 'overrode [0-9]+' "$1" 2>/dev/null | awk '{print $2}' | head -1; }
have_off=0; have_on=0
for v in "${VARIANTS[@]}"; do
  read -r _ label <<< "$v"
  [ "$label" = tageimproved ]    && have_off=1
  [ "$label" = tageimproved_sc ] && have_on=1
done

echo ""
echo "SC comparison (CondDirect MPKI; delta = on - off, positive => SC worse):"
if [ "$have_off" = 1 ] && [ "$have_on" = 1 ]; then
  printf '  %-20s %10s %10s %11s %8s\n' trace off on delta 'delta%'
else
  printf '  %-20s %10s\n' trace mpki
fi
for t in "${TRACES[@]}"; do
  base=$(basename "$t" .gz)
  off=$(mpki_of "$OUT/tageimproved__${base}.log")
  on=$(mpki_of "$OUT/tageimproved_sc__${base}.log")
  if [ "$have_off" = 1 ] && [ "$have_on" = 1 ]; then
    awk -v t="$base" -v o="$off" -v n="$on" 'BEGIN{
      if (o=="" || n=="") { printf "  %-20s %10s %10s\n", t, (o==""?"-":o), (n==""?"-":n) }
      else { d=n-o; p=(o!=0?100*d/o:0);
             printf "  %-20s %10.4f %10.4f %+11.4f %+7.2f%%\n", t, o, n, d, p }
    }'
  else
    val="${off:-$on}"; printf '  %-20s %10s\n' "$base" "${val:--}"
  fi
done
echo ""

# --- SC override quality: break rate per override (needs both variants + SC stats) ---
# On a binary branch where SC != TAGE exactly one is right, so every override
# either FIXES a TAGE miss (-1) or BREAKS a correct TAGE (+1):
#   net    = on_misp - off_misp = breaks - fixes
#   breaks = (overrides + net)/2,  fixes = (overrides - net)/2
#   break rate = breaks / overrides   (< 50% => overrides help on net => SC has skill)
if [ "$have_off" = 1 ] && [ "$have_on" = 1 ]; then
  echo "SC override quality (break rate = correct TAGE preds destroyed / overrides; <50% => net win):"
  printf '  %-20s %10s %8s %8s %9s\n' trace overrides breaks fixes 'break%'
  for t in "${TRACES[@]}"; do
    base=$(basename "$t" .gz)
    om=$(misp_of "$OUT/tageimproved__${base}.log")
    nm=$(misp_of "$OUT/tageimproved_sc__${base}.log")
    ov=$(overrides_of "$OUT/tageimproved_sc__${base}.log")
    awk -v t="$base" -v om="$om" -v nm="$nm" -v ov="$ov" 'BEGIN{
      if (om=="" || nm=="" || ov=="") { printf "  %-20s %10s\n", t, "-"; exit }
      if (ov+0==0) { printf "  %-20s %10d %8s %8s %9s\n", t, 0, "-", "-", "n/a"; exit }
      net=nm-om; b=(ov+net)/2; f=(ov-net)/2;
      printf "  %-20s %10d %8.0f %8.0f %8.1f%%\n", t, ov, b, f, 100*b/ov
    }'
  done
  echo ""
fi

echo "next:  python3 scripts/plot_series.py $OUT"
echo "       python3 scripts/plot_provider.py $OUT"

if [ "$KEEP" -eq 0 ]; then
  echo "restoring fast binary (make clean && make)..."
  make clean >/dev/null 2>&1 && make >/dev/null 2>&1 && echo "  restored ./cbp (fast)"
else
  echo "keeping instrumented ./cbp (-k); restore later with: make clean && make"
fi
