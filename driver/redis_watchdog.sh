#!/bin/bash
# redis_watchdog.sh — local Mac version of the Redis-flake watchdog.
#
# The parent's grader_watchdog.sh uses SSH to reach EC2 boxes; this version
# runs on the Mac directly against local Docker containers (OrbStack).
#
# Redis-flake: swe_bench_pro_eval.py runs `redis-server --daemonize yes` inside
# the container; occasionally the daemonize silently fails and the grader spams
# "Waiting for Redis to start..." indefinitely. Kicking redis manually unblocks it.
#
# Usage:
#   nohup bash driver/redis_watchdog.sh >> runs/scored/redis_watchdog.log 2>&1 &
#   pkill -f redis_watchdog.sh

set -u
INTERVAL="${REDIS_WATCHDOG_INTERVAL:-60}"   # poll every 60s
LOG="$(cd "$(dirname "$0")/.." && pwd)/runs/scored/redis_watchdog.log"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

log "redis_watchdog started (interval=${INTERVAL}s)"

while true; do
  # Check every running container for the Redis wedge signature
  while IFS= read -r line; do
    CID=$(echo "$line" | awk '{print $1}')
    CNAME=$(echo "$line" | awk '{print $2}')
    [ -z "$CID" ] && continue

    REDIS_WEDGE=$(docker exec "$CID" bash -c '
      T=$(tail -20 /workspace/stdout.log 2>/dev/null | grep -c "Waiting for Redis to start")
      echo ${T:-0}
    ' 2>/dev/null)
    REDIS_WEDGE="${REDIS_WEDGE:-0}"

    if [ "${REDIS_WEDGE}" -ge 5 ]; then
      log "REDIS_KICK cid=${CID} name=${CNAME} wedge_lines=${REDIS_WEDGE}"
      docker exec -d "$CID" redis-server \
        --daemonize yes --protected-mode no --port 6379 >/dev/null 2>&1
      log "REDIS_KICK sent to ${CID}"
    fi
  done < <(docker ps --format '{{.ID}} {{.Names}}' 2>/dev/null)

  sleep "$INTERVAL"
done
