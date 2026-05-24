#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-http://127.0.0.1:8000}"

echo "== health =="
curl -s "$BASE_URL/health"
echo
echo

echo "== compute =="
curl -s -X POST "$BASE_URL/class/compute" \
  -H "Content-Type: application/json" \
  -d '{
    "H0": 72.9,
    "omega_b": 0.0244,
    "omega_cdm": 0.127,
    "f_EDE": 0.082,
    "z_c": 3500,
    "n_s": 0.9847,
    "ln10_10_As": 3.058,
    "tau_reio": 0.0511
  }'
echo
