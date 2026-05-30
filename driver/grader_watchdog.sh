#!/bin/bash
# grader_watchdog.sh — detect hung Pro graders on EC2 boxes and force-kill them.
# Phase 1 only — not used in phase 0 (single-instance local run).
#
# Ported from swebench-pro/driver/grader_watchdog.sh with Flash+Composer path changes:
#   - Kill ledger: runs/scored/grader_kills.jsonl
#   - Heartbeat:   runs/scored/box_heartbeat.jsonl
#   - Remote log:  ~/swebench-pro-flash-composer/runs/ (not swebench-pro/)
#
# Detection:
#   - /workspace/stdout.log mtime inside grader container, idle > IDLE_THRESHOLD_MIN
#   - "Waiting for Redis to start..." spam (redis-flake) → kick redis, don't kill
#
# Action: docker kill <container>. Writes to grader_kills.jsonl for retry audit.
#
# Start:  nohup bash driver/grader_watchdog.sh > runs/scored/grader_watchdog-boot.log 2>&1 &
# Tail:   tail -f runs/scored/grader_watchdog.log
# Stop:   pkill -f grader_watchdog.sh
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

LOG="runs/scored/grader_watchdog.log"
KILL_LEDGER="runs/scored/grader_kills.jsonl"
HEARTBEAT_LEDGER="runs/scored/box_heartbeat.jsonl"
INTERVAL="${GRADER_WATCHDOG_INTERVAL:-300}"
IDLE_THRESHOLD_MIN="${GRADER_IDLE_MIN:-30}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG" >&2; }

check_box() {
  local name="$1"
  local envf="/tmp/${name}.env"
  [ -f "$envf" ] || return
  ( . "$envf"
    local pem="/tmp/${KEY}.pem"
    [ -f "$pem" ] || { echo "MISSING_PEM"; return; }
    ssh -i "$pem" -o ConnectTimeout=8 -o StrictHostKeyChecking=no ec2-user@${PUBIP} \
      "IDLE=$IDLE_THRESHOLD_MIN bash -s" <<'REMOTE' 2>/dev/null
        set -u
        NOW=$(date +%s)
        LOAD1=$(awk '{print $1}' /proc/loadavg 2>/dev/null || echo 0)
        echo "HEARTBEAT load1=${LOAD1}"
        # Reap orphan grader containers: swe_bench_pro_eval.py is serial per box;
        # anything older than the newest container is leaked. Kill all but newest.
        ALL_CIDS=$(docker ps --format '{{.ID}}')
        ORPHAN_CIDS=$(echo "$ALL_CIDS" | tail -n +2)
        for OCID in $ORPHAN_CIDS; do
          OCNAME=$(docker inspect -f '{{.Name}}' "$OCID" 2>/dev/null | sed 's|^/||')
          OSTARTED=$(docker inspect -f '{{.State.StartedAt}}' "$OCID" 2>/dev/null)
          OSTART_SEC=$(date -d "$OSTARTED" +%s 2>/dev/null || echo 0)
          OUPMIN=$(( (NOW - OSTART_SEC) / 60 ))
          echo "REAP_ORPHAN cid=$OCID name=$OCNAME up=${OUPMIN}m"
          docker kill "$OCID" >/dev/null 2>&1
        done
        docker ps --format '{{.ID}} {{.Names}}' | while read CID CNAME; do
          STARTED=$(docker inspect -f '{{.State.StartedAt}}' "$CID" 2>/dev/null)
          [ -z "$STARTED" ] && continue
          START_SEC=$(date -d "$STARTED" +%s 2>/dev/null || echo 0)
          [ "$START_SEC" = "0" ] && continue
          UPMIN=$(( (NOW - START_SEC) / 60 ))
          CPU=$(timeout 5 docker stats --no-stream --format '{{.CPUPerc}}' "$CID" 2>/dev/null | tr -d '%')
          [ -z "$CPU" ] && CPU=0
          # Redis-flake detection: grader spams "Waiting for Redis to start" when
          # `redis-server --daemonize yes` silently fails. Kick redis; don't kill.
          REDIS_WEDGE=$(docker exec "$CID" bash -c '
            T=$(tail -10 /workspace/stdout.log 2>/dev/null | grep -c "Waiting for Redis to start")
            echo ${T:-0}
          ' 2>/dev/null)
          REDIS_WEDGE="${REDIS_WEDGE:-0}"
          if [ "${REDIS_WEDGE}" -ge 5 ]; then
            echo "REDIS_KICK cid=$CID name=$CNAME wedge_lines=${REDIS_WEDGE}"
            docker exec -d "$CID" redis-server --daemonize yes --protected-mode no --port 6379 >/dev/null 2>&1
          fi
          # Idle signal: max mtime of /workspace/stdout.log inside the container.
          # Host-side grade dirs only update at verdict time — misleading for long runs.
          GRADER_MTIME=$(docker exec "$CID" bash -c '
            T=0
            for f in /workspace/stdout.log /workspace/stderr.log; do
              if [ -f "$f" ]; then
                M=$(stat -c %Y "$f" 2>/dev/null || echo 0)
                [ "$M" -gt "$T" ] && T=$M
              fi
            done
            echo $T
          ' 2>/dev/null)
          GRADER_MTIME="${GRADER_MTIME:-0}"
          if [ "$GRADER_MTIME" = "0" ]; then
            LATEST=$(ls -dt ~/swebench-pro-flash-composer/runs/dev/fc_grade_*/ 2>/dev/null | head -1)
            [ -n "$LATEST" ] && GRADER_MTIME=$(stat -c %Y "$LATEST" 2>/dev/null || echo 0)
          fi
          IDLEMIN=$(( (NOW - GRADER_MTIME) / 60 ))
          echo "ASSESS cid=$CID name=$CNAME up=${UPMIN}m cpu=${CPU} idle=${IDLEMIN}m wedge=${REDIS_WEDGE}"
          if [ "$IDLEMIN" -gt "$IDLE" ]; then
            echo "KILL cid=$CID name=$CNAME up=${UPMIN}m cpu=${CPU} idle=${IDLEMIN}m"
            docker kill "$CID" >/dev/null 2>&1
          fi
        done
REMOTE
  )
}

log "watchdog start (pid=$$, interval=${INTERVAL}s, idle_threshold=${IDLE_THRESHOLD_MIN}m)"

while true; do
  for envf in /tmp/coord*.env; do
    [ -f "$envf" ] || continue
    name=$(basename "$envf" .env)
    OUT=$(check_box "$name")
    if [ -n "$OUT" ]; then
      TS=$(date -u +%FT%TZ)
      echo "$OUT" | while IFS= read -r line; do
        log "$name: $line"
        if [[ "$line" == KILL* ]]; then
          CID=$(echo "$line"   | sed -nE 's/.*cid=([^ ]+).*/\1/p')
          CNAME=$(echo "$line" | sed -nE 's/.*name=([^ ]+).*/\1/p')
          UPMIN=$(echo "$line" | sed -nE 's/.*up=([0-9]+)m.*/\1/p')
          printf '{"ts":"%s","box":"%s","cid":"%s","container":"%s","uptime_min":%s,"reason":"IDLE_KILL"}\n' \
            "$TS" "$name" "$CID" "$CNAME" "${UPMIN:-0}" >> "$KILL_LEDGER"
        fi
      done
      printf '%s\n' "$OUT" | TS="$TS" BOX="$name" python3 -c '
import sys, json, re, os
ts, box = os.environ["TS"], os.environ["BOX"]
load = 0.0; containers = []
for line in sys.stdin:
    line = line.rstrip()
    m = re.match(r"HEARTBEAT load1=([\d.]+)", line)
    if m: load = float(m.group(1)); continue
    m = re.match(r"ASSESS cid=(\S+) name=(\S+) up=(\d+)m cpu=([\d.]+) idle=(\d+)m", line)
    if m:
        containers.append({"cid": m.group(1), "name": m.group(2),
                           "uptime_min": int(m.group(3)),
                           "cpu_pct": float(m.group(4)),
                           "idle_min": int(m.group(5))})
print(json.dumps({"ts": ts, "box": box, "load1": load, "containers": containers}))
' >> "$HEARTBEAT_LEDGER"
    fi
  done
  sleep "$INTERVAL"
done
