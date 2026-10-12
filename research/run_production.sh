#!/usr/bin/env bash
# The full production run, after `windclim fetch` has completed.
# Wakayama first because it is a ninth the size, so any problem surfaces cheaply.
set -euo pipefail
PY=/home/nishihama/anaconda3/envs/jra3q/bin/python

for region in wakayama hokkaido; do
  echo "=== $region ==="
  $PY -m windclim.cli all --region "$region"
  $PY -m windclim.cli summary --region "$region" | tee "out/csv/summary_${region}.txt"
done

echo "=== comparison ==="
$PY -m windclim.cli compare

echo "=== JST convention, for the report's UTC-vs-JST check ==="
$PY -m windclim.cli aggregate --region hokkaido --convention jst
