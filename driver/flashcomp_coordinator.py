#!/usr/bin/env python3
"""flashcomp_coordinator.py — Mac-side dynamic dispatcher for the §4.5a EC2 run.

Key difference from the parent coordinator.py: workers run flashcomp_pilot.py as a
LOCAL subprocess (cursor-agent + Flash API are Mac-only), passing REMOTE_BOX in env
so the pilot SSHes to an EC2 box for all docker commands.  Each worker owns one EC2
box as its docker host.

  driver/flashcomp_coordinator.py --boxes 4 --eligible runs/audit/eligible.txt

Fault tolerance (mirrors parent):
  - box dies/hangs     -> SSH timeout hits --instance-ceiling -> id requeued, box re-provisioned
  - coordinator crash  -> re-run; resumes from all run*.jsonl ledgers
  - poison instance    -> bounded --max-attempts -> recorded INCOMPLETE
  - box won't come up  -> bounded --box-restart-max -> worker retires; others carry on
"""
import argparse, json, os, pathlib, queue, re, subprocess, sys, threading, time

REPO   = pathlib.Path(__file__).resolve().parent.parent
DRIVER = REPO / "driver"
SIBLING = pathlib.Path(os.environ.get("SIBLING", "/Users/junekim/Documents/swebench-pro"))
LEDGER = REPO / "runs" / "scored" / "run.jsonl"   # shared ledger (overridable via --ledger)
SCORED = REPO / "runs" / "scored"
PY     = sys.executable

FAULT_RE = re.compile(
    r"BOX_DEATH|OOM|DISK_FULL|SETUP_NETWORK_FAIL|PROVIDER_CRED_REJECT|"
    r"No space left|Cannot connect to the Docker daemon|manifest unknown|"
    r"failed to pull|Killed|MemoryError", re.I)

_ledger_lock   = threading.Lock()
_attempts_lock = threading.Lock()
_attempts      = {}   # iid -> count


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ── ledger ────────────────────────────────────────────────────────────────────

def load_done():
    """Merge ALL run*.jsonl ledger files (picks up existing local shard wins)."""
    done = {}
    SCORED.mkdir(parents=True, exist_ok=True)
    for f in sorted(SCORED.glob("run*.jsonl")):
        for line in f.read_text().splitlines():
            try:
                r = json.loads(line)
                if r["state"] in ("WIN", "LOSS"):   # INCOMPLETE stays runnable
                    done[r["instance_id"]] = r
            except Exception:
                pass
    return done


def record(rec):
    with _ledger_lock:
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with open(LEDGER, "a") as f:
            f.write(json.dumps(rec) + "\n")


# ── box env / provisioning ────────────────────────────────────────────────────

def box_env(name):
    """Parse /tmp/<name>.env written by provision_box.sh."""
    p = pathlib.Path(f"/tmp/{name}.env")
    if not p.exists():
        return None
    env = {}
    for line in p.read_text().splitlines():
        if "=" in line:
            k, v = line.split("=", 1); env[k] = v
    return env if env.get("PUBIP") and env.get("KEY") else None


def setup_box(name, restart_max):
    """Provision + ready a box. Returns env dict or None after restart_max failures."""
    provision = str(DRIVER / "provision_box.sh")
    for attempt in range(1, restart_max + 1):
        log(f"{name}: provision (attempt {attempt}/{restart_max})")
        r = subprocess.run(["bash", provision, name], capture_output=True, text=True)
        if "READY" in r.stdout:
            env = box_env(name)
            if env:
                log(f"{name}: READY @ {env['PUBIP']}")
                return env
        log(f"{name}: provision failed — {(r.stdout + r.stderr).strip().splitlines()[-1:]}")
        kill_box(name)
    return None


def kill_box(name):
    """Terminate the EC2 instance for <name> via its .env file (best-effort)."""
    env = box_env(name)
    if not env:
        return
    region = env.get("REGION", "us-west-2")
    iid    = env.get("IID")
    sg     = env.get("SG")
    key    = env.get("KEY")
    if iid:
        subprocess.run(
            ["aws", "ec2", "terminate-instances", "--instance-ids", iid, "--region", region],
            capture_output=True)
    if sg:
        subprocess.run(
            ["aws", "ec2", "delete-security-group", "--group-id", sg, "--region", region],
            capture_output=True)
    if key:
        subprocess.run(
            ["aws", "ec2", "delete-key-pair", "--key-name", key, "--region", region],
            capture_output=True)
        pem = pathlib.Path(f"/tmp/{key}.pem")
        if pem.exists():
            pem.unlink(missing_ok=True)
    env_file = pathlib.Path(f"/tmp/{name}.env")
    if env_file.exists():
        env_file.unlink(missing_ok=True)


# ── task preparation ──────────────────────────────────────────────────────────

def make_task(iid):
    """Ensure task JSON exists for iid. Returns path or None on failure."""
    task_dir = SIBLING / "tasks" / "generated"
    task_dir.mkdir(parents=True, exist_ok=True)
    task = task_dir / f"{iid}.json"
    if task.exists():
        return task
    mk = subprocess.run(
        [PY, str(SIBLING / "driver" / "make_task.py"), iid],
        capture_output=True, text=True,
        env={**os.environ, "BENCH": "pro"}, timeout=600)
    if task.exists():
        return task
    log(f"  {iid}: make_task failed — {(mk.stderr or mk.stdout).strip()[-200:]}")
    return None


# ── per-instance dispatch ─────────────────────────────────────────────────────

def run_instance(env, iid, ceiling):
    """Run flashcomp_pilot.py locally with REMOTE_BOX pointing to the EC2 box.

    Returns parsed rec dict, or None on transport/box fault (pilot did not emit
    RESULT_JSON or subprocess timed out).
    """
    pem       = f"/tmp/{env['KEY']}.pem"
    remote_box = f"ec2-user@{env['PUBIP']}:{pem}"

    task = make_task(iid)
    if task is None:
        # make_task failure is a platform fault (network, credentials) — treat as box fault
        return None

    child_env = {**os.environ, "REMOTE_BOX": remote_box}

    try:
        r = subprocess.run(
            [PY, str(DRIVER / "flashcomp_pilot.py"), str(task), iid],
            capture_output=True, text=True, timeout=ceiling, env=child_env)
    except subprocess.TimeoutExpired:
        log(f"  {iid}: instance ceiling {ceiling}s hit — treating as box fault")
        return None

    out = r.stdout + r.stderr
    for line in (r.stdout or "").splitlines():
        if line.startswith("RESULT_JSON "):
            try:
                return json.loads(line[len("RESULT_JSON "):])
            except Exception:
                pass

    # No RESULT_JSON.  Distinguish platform faults (INCOMPLETE/requeue) from
    # endogenous failures (LOSS) so the attempt counter is used correctly.
    if FAULT_RE.search(out):
        log(f"  {iid}: platform fault in output — requeue as box fault")
        return None   # causes requeue + reprovision, same as transport failure
    # Pilot crashed before emitting RESULT_JSON — endogenous; return a synthetic LOSS
    # so the attempt counter advances and eventually records INCOMPLETE if repeated.
    return {
        "instance_id": iid,
        "state":       "INCOMPLETE",
        "detail":      "no RESULT_JSON (pilot crashed): " + out.strip()[-200:],
        "secs":        0,
    }


# ── worker ────────────────────────────────────────────────────────────────────

def worker(name, q, max_attempts, ceiling, restart_max, skip_setup=False):
    if skip_setup:
        env = box_env(name)
        if not env:
            log(f"{name}: --skip-setup but /tmp/{name}.env missing/invalid — retiring worker")
            return
        log(f"{name}: REUSING existing box @ {env['PUBIP']} (skip-setup)")
    else:
        env = setup_box(name, restart_max)
        if not env:
            log(f"{name}: could not provision after {restart_max} tries — retiring this worker")
            return

    while True:
        try:
            iid = q.get_nowait()
        except queue.Empty:
            break

        with _attempts_lock:
            _attempts[iid] = _attempts.get(iid, 0) + 1
            n = _attempts[iid]
        log(f"{name}: dispatch {iid} (attempt {n})")

        rec = run_instance(env, iid, ceiling)

        if rec is None:
            # box/transport fault — requeue the instance, recycle the box
            log(f"{name}: box fault on {iid} — requeue + reprovision")
            q.put(iid)
            kill_box(name)
            env = setup_box(name, restart_max)
            if not env:
                log(f"{name}: reprovision failed — retiring worker (work stays queued)")
                return
            continue

        rec["box"] = name
        if rec["state"] == "INCOMPLETE" and n < max_attempts:
            log(f"  {iid}: INCOMPLETE (attempt {n}/{max_attempts}) — requeue")
            q.put(iid)
            continue

        record(rec)
        log(f"  {iid}: {rec['state']} ({rec.get('secs', '?')}s) recorded")

    log(f"{name}: queue drained — terminating box")
    kill_box(name)


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="flashcomp EC2 coordinator (Mac-side)")
    ap.add_argument("--boxes",            type=int, required=True,
                    help="number of EC2 boxes to provision")
    ap.add_argument("--box-offset",       type=int, default=0,
                    help="start box numbering at coord<offset+1> (avoids collision with a parallel coordinator)")
    ap.add_argument("--skip-setup",       action="store_true",
                    help="reuse already-provisioned boxes from /tmp/<name>.env")
    ap.add_argument("--eligible",         default=str(REPO / "runs" / "audit" / "eligible.txt"))
    ap.add_argument("--max-attempts",     type=int, default=3,
                    help="per-instance attempts before recording INCOMPLETE")
    ap.add_argument("--box-restart-max",  type=int, default=3,
                    help="provision retries before a worker retires")
    ap.add_argument("--instance-ceiling", type=int, default=14400,
                    help="hard per-instance subprocess timeout (s); RECON_CAP+CRAFT_CAP+AUDIT_CAP")
    ap.add_argument("--ledger",
                    help="ledger path (default runs/scored/run.jsonl)")
    args = ap.parse_args()

    global LEDGER
    if args.ledger:
        LEDGER = pathlib.Path(args.ledger)

    if not LEDGER.parent.exists():
        LEDGER.parent.mkdir(parents=True, exist_ok=True)

    elig = pathlib.Path(args.eligible).read_text().split()
    done = load_done()
    todo = [i for i in elig if i not in done]
    log(f"eligible={len(elig)}  done={len(done)}  todo={len(todo)}  boxes={args.boxes}")
    if not todo:
        log("nothing to do — ledger already complete"); return

    q = queue.Queue()
    for i in todo:
        q.put(i)

    threads = [
        threading.Thread(
            target=worker,
            args=(f"coord{b + 1 + args.box_offset}", q,
                  args.max_attempts, args.instance_ceiling,
                  args.box_restart_max, args.skip_setup),
            name=f"coord{b + 1 + args.box_offset}")
        for b in range(args.boxes)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Summary from the shared ledger
    recs = {}
    if LEDGER.exists():
        for line in LEDGER.read_text().splitlines():
            try:
                r = json.loads(line); recs[r["instance_id"]] = r
            except Exception:
                pass
    from collections import Counter
    c = Counter(r["state"] for r in recs.values())
    won    = [i for i, r in recs.items() if r["state"] == "WIN"]
    graded = [i for i, r in recs.items() if r["state"] in ("WIN", "LOSS")]
    log(f"DONE — {dict(c)} of {len(recs)} recorded; eligible={len(elig)}")
    log(f"  WINS={len(won)}  graded={len(graded)}  "
        f"resolve-rate={len(won) / max(1, len(graded)):.3f}")
    missing = [i for i in elig if i not in recs]
    if missing:
        log(f"  {len(missing)} eligible instances unrecorded — re-run coordinator to finish")


if __name__ == "__main__":
    main()
