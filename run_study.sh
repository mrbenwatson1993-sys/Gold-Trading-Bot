#!/usr/bin/env bash
# Regenerate every result in the study, in the order the argument is built.
#
# Each stage writes CSVs into reports/ and prints its findings. Stages are
# independent: if one fails the rest still run, so a partial dataset still
# produces whatever it can support.
#
# Usage:  ./run_study.sh [data_dir] [out_dir]
set -uo pipefail

DATA="${1:-data/bars}"
OUT="${2:-reports}"
PY="${PY:-.venv/bin/python}"

mkdir -p "$OUT"

if [ ! -d "$DATA" ] || [ -z "$(ls -A "$DATA" 2>/dev/null)" ]; then
  cat <<'EOF'
No data found. Download it first (resumable; run shards in parallel):

  for i in 0 1 2 3; do
    .venv/bin/python -m aurum.data.dukascopy \
      --start 2022-01-01 --end 2026-09-01 --shard $i --shards 4 &
  done; wait
EOF
  exit 1
fi

run () {
  local title="$1"; shift
  printf '\n\n%s\n== %s\n%s\n\n' \
    "================================================================" \
    "$title" \
    "================================================================"
  "$@" || echo "  [stage failed: $title]"
}

run "0. Engine correctness and look-ahead detection" \
    "$PY" -m pytest tests/ -q

run "1. Market structure: liquidity, autocorrelation, hourly drift, cost floor" \
    "$PY" -m aurum.research.explore --data "$DATA" --out "$OUT"

run "2. Hypothesis screen against a held-out test set" \
    "$PY" -m aurum.research.hypotheses --data "$DATA" --out "$OUT" --tfs 15min

run "3. The horizon spectrum (the central result)" \
    "$PY" -m aurum.research.horizon --data "$DATA" --out "$OUT"

run "4. Frequency vs quality frontier" \
    "$PY" -m aurum.research.frequency --data "$DATA" --out "$OUT"

run "5. Breakeven cost per mechanism, vs buy-and-hold" \
    "$PY" -m aurum.research.breakeven --data "$DATA" --out "$OUT"

run "6. Daily strategy: regime and side robustness" \
    "$PY" -m aurum.research.regime --data "$DATA" --out "$OUT"

run "7. Walk-forward validation, out-of-sample only" \
    "$PY" -m aurum.research.validate --data "$DATA" --out "$OUT" --tf 15min

printf '\n\nAll stages complete. CSVs in %s/\n' "$OUT"
