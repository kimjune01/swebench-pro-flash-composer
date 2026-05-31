#!/bin/bash
# bootstrap.sh — validate the Flash+Composer Phase 0 local environment.
#
# PHASE 0 NOTE — EC2 DEFERRED:
#   cursor-agent ships macOS ARM64 native modules (file_service.darwin-arm64.node,
#   merkle-tree-napi.darwin-arm64.node). A Linux x86_64 build from Cursor is needed
#   before EC2 dispatch works. Phase 0 runs locally on Mac (dev mode, OrbStack amd64
#   emulation), identical to swebench-pro's §4 dev path. Phase 1 resolves the EC2 path.
#
# Validates:
#   1. API keys present (GEMINI_API_KEY + CURSOR_API_KEY)
#   2. gemini-cli works: gemini-2.5-flash headless smoke test
#   3. cursor-agent works: composer-2.5 headless smoke test
#   4. Docker running (OrbStack or Docker Desktop)
#   5. Sibling .proenv sources cleanly (SWEAP_OS_REPO + PY)
#   6. pandas importable from sibling venv (needed by official_grade)
#
# Usage:
#   export GEMINI_API_KEY CURSOR_API_KEY  # or source ~/.zshrc first
#   bash driver/bootstrap.sh
#   . /path/to/swebench-pro/driver/.proenv  # then source .proenv for SWEAP_OS_REPO+PY
set -u
SIBLING="${SIBLING:-/Users/junekim/Documents/swebench-pro}"
PASS=0; FAIL=0

ok()   { echo "  OK  $*"; PASS=$((PASS+1)); }
fail() { echo "  FAIL $*"; FAIL=$((FAIL+1)); }
warn() { echo "  WARN $*"; }

echo "=== Flash+Composer Phase 0 bootstrap (local dev) ==="
echo ""

# 1. API keys
[ -n "${GEMINI_API_KEY:-}" ]  && ok "GEMINI_API_KEY present (${#GEMINI_API_KEY} chars)" \
                              || fail "GEMINI_API_KEY not set — export it or source ~/.zshrc"
[ -n "${CURSOR_API_KEY:-}" ]  && ok "CURSOR_API_KEY present (${#CURSOR_API_KEY} chars)" \
                              || fail "CURSOR_API_KEY not set — export it or source ~/.zshrc"

# 2. google-genai Python package + API smoke
if $PY -c "from google import genai; print(genai.__version__)" >/dev/null 2>&1; then
  GENAI_VER=$($PY -c "from google import genai; print(genai.__version__)" 2>/dev/null)
  HI=$($PY - <<'PYEOF' 2>&1
import os, sys
from google import genai
key = os.environ.get("GEMINI_API_KEY", "")
if not key:
    print("NO_KEY"); sys.exit(0)
try:
    client = genai.Client(api_key=key, http_options={"timeout": 60})
    r = client.models.generate_content(model="gemini-2.5-flash", contents="Reply with only the word: OK")
    print(r.text or "EMPTY")
except Exception as e:
    print(f"ERROR: {e}")
PYEOF
)
  if echo "$HI" | grep -qi "ok\|sure\|hello\|hi"; then
    ok "gemini-2.5-flash API smoke (google-genai==$GENAI_VER)"
  else
    fail "gemini API smoke returned unexpected: ${HI:0:120}"
  fi
else
  fail "google-genai not installed — uv pip install google-genai --python \$PY"
fi

# 3. cursor-agent
if command -v cursor-agent >/dev/null 2>&1; then
  CA_VER=$(cursor-agent --version 2>&1 | head -1)
  CA_HI=$(CURSOR_API_KEY="${CURSOR_API_KEY:-}" \
          cursor-agent --print --model composer-2.5 \
            --trust --workspace /tmp --yolo \
            "Reply with only the word: OK" 2>&1 | head -3 || true)
  if echo "$CA_HI" | grep -qi "ok\|sure\|hello\|hi"; then
    ok "composer-2.5 smoke: $CA_VER"
  else
    fail "cursor-agent smoke returned unexpected: ${CA_HI:0:80}"
  fi
else
  fail "cursor-agent not on PATH"
fi

# 4. Docker
if command -v docker >/dev/null 2>&1 && docker ps >/dev/null 2>&1; then
  ok "Docker running"
else
  fail "Docker not running — start OrbStack or Docker Desktop"
fi

# 5. Sibling .proenv
if [ -f "$SIBLING/driver/.proenv" ]; then
  # source into a subshell to avoid polluting this session
  PROENV_OUT=$(bash -c ". '$SIBLING/driver/.proenv' && echo PY=\$PY SWEAP=\$SWEAP_OS_REPO" 2>&1)
  if echo "$PROENV_OUT" | grep -q "PY="; then
    ok "sibling .proenv sources: $PROENV_OUT"
  else
    fail "sibling .proenv sources but PY not exported: $PROENV_OUT"
  fi
else
  fail "sibling .proenv missing at $SIBLING/driver/.proenv — run bootstrap in swebench-pro first"
fi

# 6. pandas in sibling venv
if [ -n "${PY:-}" ]; then
  $PY -c "import pandas" 2>/dev/null && ok "pandas importable ($PY)" \
    || fail "pandas not in $PY — uv pip install pandas in sibling venv"
else
  warn "PY not set (source sibling .proenv); skipping pandas check"
fi

echo ""
echo "=== $PASS passed, $FAIL failed ==="
if [ "$FAIL" -gt 0 ]; then
  echo "Fix the above failures before running phase0.sh."
  exit 1
fi
echo ""
echo "READY — next steps:"
echo "  1. Source sibling .proenv (if not already):  . $SIBLING/driver/.proenv"
echo "  2. Run one instance:                          bash driver/phase0.sh [<instance_id>]"
