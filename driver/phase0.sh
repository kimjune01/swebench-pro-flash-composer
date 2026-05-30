#!/bin/bash
# phase0.sh — proof of pipeline: ONE instance, end-to-end, any parseable verdict.
#
# Picks an instance from eligible.txt (or takes one as $1), runs flashcomp_pilot.py,
# appends the RESULT_JSON to runs/scored/run.jsonl.
#
# Usage:
#   . /path/to/swebench-pro/driver/.proenv  # sets SWEAP_OS_REPO + PY
#   export GEMINI_API_KEY CURSOR_API_KEY    # or source ~/.zshrc
#   bash driver/phase0.sh                  # auto-picks first unrecorded eligible
#   bash driver/phase0.sh <instance_id>    # run a specific instance
#
# For a fast smoke-check, pick a known short WIN from the sibling's ledger:
#   grep '"state":"WIN"' /path/to/swebench-pro/runs/scored/run.jsonl \
#     | python3 -c "import sys,json;recs=sorted([json.loads(l) for l in sys.stdin],
#       key=lambda r:r['secs'])[:5];[print(r['instance_id'],r['secs'],'s') for r in recs]"
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
SIBLING="${SIBLING:-/Users/junekim/Documents/swebench-pro}"
ELIGIBLE="$REPO/runs/audit/eligible.txt"
LEDGER="$REPO/runs/scored/run.jsonl"
TASKS_DIR="$SIBLING/tasks/generated"

# ── environment gates ─────────────────────────────────────────────────────────
[ -n "${SWEAP_OS_REPO:-}" ] || {
  echo "FATAL: SWEAP_OS_REPO not set — source sibling .proenv first:"
  echo "  . $SIBLING/driver/.proenv"
  exit 1
}
[ -n "${PY:-}" ] || {
  echo "FATAL: PY not set — source sibling .proenv first"
  exit 1
}
[ -n "${GEMINI_API_KEY:-}" ]  || { echo "FATAL: GEMINI_API_KEY not set"; exit 1; }
[ -n "${CURSOR_API_KEY:-}" ]  || { echo "FATAL: CURSOR_API_KEY not set"; exit 1; }
command -v cursor-agent >/dev/null 2>&1 || { echo "FATAL: cursor-agent not on PATH"; exit 1; }
$PY -c "from google import genai" 2>/dev/null || { echo "FATAL: google-genai not installed — uv pip install google-genai"; exit 1; }
command -v docker       >/dev/null 2>&1 || { echo "FATAL: docker not on PATH"; exit 1; }
docker ps >/dev/null 2>&1 || { echo "FATAL: Docker not running (start OrbStack/Docker Desktop)"; exit 1; }

# ── pick instance ─────────────────────────────────────────────────────────────
if [ -n "${1:-}" ]; then
  IID="$1"
else
  # First eligible instance not already terminal in the ledger
  IID=""
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    if ! grep -q "\"instance_id\":\"${line}\"" "$LEDGER" 2>/dev/null; then
      IID="$line"; break
    fi
  done < "$ELIGIBLE"
  [ -n "$IID" ] || { echo "FATAL: all eligible instances already recorded"; exit 0; }
fi
echo "=== Phase 0: $IID ==="

# ── make task ─────────────────────────────────────────────────────────────────
TASK_JSON="$TASKS_DIR/${IID}.json"
if [ ! -f "$TASK_JSON" ]; then
  echo "--- make_task $IID (from sibling driver) ---"
  BENCH=pro $PY "$SIBLING/driver/make_task.py" "$IID"
fi
[ -f "$TASK_JSON" ] || { echo "FATAL: make_task failed for $IID"; exit 1; }

# ── run pilot ─────────────────────────────────────────────────────────────────
mkdir -p "$REPO/runs/scored"
echo "--- flash_pilot $IID ---"
# Capture all output; parse the RESULT_JSON line out at the end.
# tee /dev/stderr lets us stream the run log while still capturing stdout.
PILOT_OUT=$($PY "$REPO/driver/flashcomp_pilot.py" "$TASK_JSON" "$IID" 2>&1) || true
echo "$PILOT_OUT"

# ── record verdict ────────────────────────────────────────────────────────────
RESULT=$(echo "$PILOT_OUT" | grep "^RESULT_JSON " | tail -1 | cut -c13-)
if [ -n "$RESULT" ]; then
  echo "$RESULT" >> "$LEDGER"
  STATE=$(echo "$RESULT" | python3 -c \
    "import sys,json; r=json.load(sys.stdin); print(r['state'], r.get('detail','')[:80])")
  echo "=== recorded: $STATE ==="
  echo "    ledger: $LEDGER"
else
  echo "WARNING: no RESULT_JSON in pilot output."
  echo "  Check: $REPO/runs/dev/flashcomp_run.jsonl"
  echo "  and:   $REPO/runs/dev/fc_out_*.txt"
  exit 1
fi
