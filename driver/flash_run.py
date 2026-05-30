#!/usr/bin/env python3
"""flash_run.py — whole-set driver for the §4.5a ablation run.

Deterministic stripe of runs/audit/run_order.txt across N parallel shards.
Resume is automatic: instances already in any ledger shard are skipped.
Tag rotation (artifact change) → delete or archive all run.*.jsonl and restart.

  driver/flash_run.py [--shard i/N] [--limit N] [--only ID ...]
  driver/flash_run.py --shard 1/4   # shard 1 of 4 (Mac process 1)
  driver/flash_run.py --shard 2/4   # shard 2 of 4 (Mac process 2)

Multi-shard: run N of these in parallel. Each writes to its own shard ledger
(runs/scored/run.S{i}of{N}.jsonl) to avoid concurrent-write races. load_done()
merges all run.*.jsonl files to build the resume set.

Pruning: disabled when --shard is active (concurrent shards share Docker images;
pruning between instances would evict images the other shard is about to pull).
Set FLASH_RUN_PRUNE=1 to force-enable.

Reads $PY/$SWEAP_OS_REPO from sibling .proenv (source it first).
Reads $GEMINI_API_KEY/$CURSOR_API_KEY from env.
"""
import argparse, json, os, pathlib, re, subprocess, sys, time

REPO   = pathlib.Path(__file__).resolve().parent.parent
DRIVER = REPO / "driver"
SIBLING = pathlib.Path(os.environ.get("SIBLING", "/Users/junekim/Documents/swebench-pro"))
ORDER  = REPO / "runs" / "audit" / "run_order.txt"
SCORED = REPO / "runs" / "scored"
PY     = sys.executable

# Enumerated external platform faults (prereg §4) — INCOMPLETE, retry permitted.
# Everything else is endogenous to the harness → LOSS, no retry.
FAULT_RE = re.compile(
    r"BOX_DEATH|OOM|DISK_FULL|SETUP_NETWORK_FAIL|PROVIDER_CRED_REJECT|"
    r"No space left|Cannot connect to the Docker daemon|manifest unknown|"
    r"failed to pull|Killed|MemoryError", re.I)


def load_order():
    if not ORDER.exists():
        sys.exit(f"missing {ORDER} — run `sort runs/audit/eligible.txt > runs/audit/run_order.txt`")
    return [l.strip() for l in ORDER.read_text().splitlines() if l.strip()]


def shard(ids, spec):
    """Deterministic stripe of the frozen order (prereg §3)."""
    if not spec:
        return ids
    i, n = (int(x) for x in spec.split("/"))
    if not (1 <= i <= n):
        sys.exit(f"--shard {spec}: need 1<=i<=N")
    return [x for k, x in enumerate(ids) if k % n == (i - 1)]


def ledger_path(shard_spec):
    """Per-shard ledger file. No shard → run.jsonl (backward compat)."""
    if not shard_spec:
        return SCORED / "run.jsonl"
    i, n = (int(x) for x in shard_spec.split("/"))
    return SCORED / f"run.S{i}of{n}.jsonl"


def load_done():
    """Merge all run.*.jsonl ledger files into a single done dict (last-write wins)."""
    done = {}
    SCORED.mkdir(parents=True, exist_ok=True)
    for f in sorted(SCORED.glob("run*.jsonl")):
        for line in f.read_text().splitlines():
            try:
                r = json.loads(line); done[r["instance_id"]] = r
            except Exception:
                pass
    return done


def run_one(iid, task_dir):
    """make_task + flash_pilot. Returns (state, detail) per prereg §4."""
    task = task_dir / f"{iid}.json"
    if not task.exists():
        mk = subprocess.run(
            [PY, str(SIBLING / "driver" / "make_task.py"), iid],
            capture_output=True, text=True,
            env={**os.environ, "BENCH": "pro"}, timeout=600)
        if not task.exists():
            return "INCOMPLETE", "make_task failed: " + (mk.stderr or mk.stdout).strip()[-200:]

    p = subprocess.run(
        [PY, str(DRIVER / "flash_pilot.py"), str(task), iid],
        capture_output=True, text=True)
    out = p.stdout + p.stderr

    # Pilot emits RESULT_JSON — parse it as the authoritative verdict.
    m = re.search(r"^RESULT_JSON (.+)$", out, re.MULTILINE)
    if m:
        try:
            rec = json.loads(m.group(1))
            return rec["state"], rec.get("detail", "")
        except Exception:
            pass

    # No RESULT_JSON: platform fault or unrecoverable crash.
    if FAULT_RE.search(out):
        return "INCOMPLETE", "platform fault: " + FAULT_RE.search(out).group(0)
    return "LOSS", "no RESULT_JSON (endogenous): " + out.strip()[-200:]


def prune_images(shard_spec):
    """Drop pulled images between instances to bound disk use.
    Disabled when --shard is active unless FLASH_RUN_PRUNE=1 is forced:
    concurrent shards share Docker images and pruning evicts images the
    other shard is about to pull."""
    default_on = "0" if shard_spec else "1"
    if os.environ.get("FLASH_RUN_PRUNE", default_on) == "0":
        return
    subprocess.run(
        "docker system prune -af --volumes >/dev/null 2>&1",
        shell=True, timeout=300)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", help="i/N deterministic stripe of the frozen order")
    ap.add_argument("--limit", type=int, help="stop after N instances (dev only)")
    ap.add_argument("--only", nargs="*", default=[],
                    help="run exactly these ids (single-dispatch / re-run)")
    args = ap.parse_args()

    SCORED.mkdir(parents=True, exist_ok=True)
    task_dir = SIBLING / "tasks" / "generated"
    task_dir.mkdir(parents=True, exist_ok=True)

    ledger = ledger_path(args.shard)
    done = load_done()  # merges all shard ledgers for resume

    if args.only:
        valid = set(load_order())
        ids = [i for i in args.only if i in valid]
        force_redo = set(args.only)
    else:
        ids = shard(load_order(), args.shard)
        if args.limit:
            ids = ids[:args.limit]
        force_redo = set()

    print(f"ledger: {ledger.name}  shard: {args.shard or 'all'}  "
          f"todo: {sum(1 for i in ids if i not in done or i in force_redo)}/{len(ids)}", flush=True)

    with open(ledger, "a") as f:
        for k, iid in enumerate(ids, 1):
            if iid in done and iid not in force_redo:
                continue  # resume: skip recorded (prereg §3)

            t0 = time.time()
            started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t0))
            print(f"[{k}/{len(ids)}] {iid} ...", flush=True)

            state, detail = run_one(iid, task_dir)

            rec = {
                "instance_id": iid,
                "state":       state,
                "detail":      detail,
                "secs":        round(time.time() - t0),
                "started_at":  started_at,
                "ended_at":    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            f.write(json.dumps(rec) + "\n"); f.flush()
            print(f"    -> {state} ({rec['secs']}s) {detail[:80]}", flush=True)
            print("RESULT_JSON " + json.dumps(rec), flush=True)

            prune_images(args.shard)

    # Summary (merge all shards)
    done_now = load_done()
    from collections import Counter
    c = Counter(r["state"] for r in done_now.values())
    print(f"\n=== flash_run summary: {dict(c)} of {len(done_now)} recorded ===")


if __name__ == "__main__":
    main()
