#!/usr/bin/env python3
"""regrade_on_boxes.py — re-grade captured patches across the EC2 fleet.

Same intent as regrade_from_patches.py, but grades on the boxes (stable) instead
of Mac Docker (flaky).  Distributes the official_resolved=None LOSS instances
round-robin across all /tmp/coord*.env boxes, grades each from its persisted
fc_sample_/fc_pred_ files via the on-box grader, then rewrites the ledger.

  python3 driver/regrade_on_boxes.py
  python3 driver/regrade_on_boxes.py --dry-run
"""
import argparse, json, pathlib, queue, shutil, subprocess, threading, time, glob

REPO   = pathlib.Path(__file__).resolve().parent.parent
DEV    = REPO / "runs" / "dev"
LEDGER = REPO / "runs" / "scored" / "run.jsonl"
DHUB   = "jefzda"

_lock = threading.Lock()
_results = {}   # iid -> resolved(bool) | None


def log(m): print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def boxes():
    out = []
    for f in sorted(glob.glob("/tmp/coord*.env")):
        env = {}
        for line in open(f):
            if "=" in line:
                k, v = line.strip().split("=", 1); env[k] = v
        if env.get("PUBIP") and env.get("KEY"):
            env["name"] = pathlib.Path(f).stem
            out.append(env)
    return out


def target_instances():
    seen, out = set(), []
    for line in LEDGER.read_text().splitlines():
        try: r = json.loads(line)
        except Exception: continue
        if (r.get("state") == "LOSS"
                and "official_resolved=None" in r.get("detail", "")
                and r["instance_id"] not in seen):
            seen.add(r["instance_id"]); out.append(r["instance_id"])
    return out


def _ssh(env, cmd, timeout):
    return subprocess.run(
        ["ssh", "-i", f"/tmp/{env['KEY']}.pem", "-o", "StrictHostKeyChecking=no",
         "-o", "ConnectTimeout=15", f"ec2-user@{env['PUBIP']}", cmd],
        capture_output=True, text=True, timeout=timeout)


def _scp(env, local, remote, timeout=180):
    subprocess.run(
        ["scp", "-i", f"/tmp/{env['KEY']}.pem", "-o", "StrictHostKeyChecking=no",
         "-o", "ConnectTimeout=15", str(local), f"ec2-user@{env['PUBIP']}:{remote}"],
        check=True, capture_output=True, text=True, timeout=timeout)


def grade_on_box(env, iid):
    tag  = iid.replace("/", "_")
    samp = DEV / f"fc_sample_{tag}.jsonl"
    pred = DEV / f"fc_pred_{tag}.json"
    if not (samp.exists() and pred.exists()):
        return None
    rdir = f"/tmp/fcgrade_{tag}"
    try:
        _ssh(env, f"mkdir -p {rdir}/out", 60)
        _scp(env, samp, f"{rdir}/sample.jsonl")
        _scp(env, pred, f"{rdir}/pred.json")
        cmd = (f"cd ~/swebench-pro-os && timeout 1800 python3 swe_bench_pro_eval.py "
               f"--raw_sample_path {rdir}/sample.jsonl --patch_path {rdir}/pred.json "
               f"--output_dir {rdir}/out --scripts_dir run_scripts --num_workers 1 "
               f"--use_local_docker --dockerhub_username {DHUB} --redo")
        _ssh(env, cmd, 1900)
        r = _ssh(env, f"cat {rdir}/out/eval_results.json 2>/dev/null", 60)
        _ssh(env, f"rm -rf {rdir}", 60)
        if not r.stdout.strip():
            return None
        val = json.loads(r.stdout).get(iid)
        if isinstance(val, bool): return val
        if isinstance(val, dict): return val.get("resolved")
    except Exception as exc:
        log(f"  {env['name']} {iid[:40]}: error {exc}")
    return None


def worker(env, q, total):
    while True:
        try: iid = q.get_nowait()
        except queue.Empty: return
        resolved = grade_on_box(env, iid)
        with _lock:
            _results[iid] = resolved
            n = len(_results)
        log(f"{env['name']}: {iid[:46]} -> {resolved}   ({n}/{total})")


def rewrite_ledger(verdicts, targets):
    targets = set(targets)
    kept = []
    for line in LEDGER.read_text().splitlines():
        try: r = json.loads(line)
        except Exception:
            kept.append(line); continue
        if (r.get("instance_id") in targets and r.get("state") == "LOSS"
                and "official_resolved=None" in r.get("detail", "")):
            continue
        kept.append(line)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    new = []
    for iid, resolved in verdicts.items():
        if resolved is None:
            continue   # still ungraded — leave OUT so the coordinator requeues it
        new.append(json.dumps({
            "instance_id": iid,
            "state": "WIN" if resolved else "LOSS",
            "detail": f"official_resolved={resolved} agent_verdict=RESOLVED (regraded-on-box)",
            "secs": 0, "regraded_at": now,
            "model_pair": "gemini-2.5-flash+composer-2.5",
        }))
    LEDGER.write_text("\n".join(kept + new) + "\n")
    return len(new)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    fleet = boxes()
    iids  = target_instances()
    log(f"boxes={len(fleet)}  false-LOSS to regrade={len(iids)}")
    if args.dry_run:
        for i in iids: print("  ", i)
        return
    if not fleet:
        log("no boxes available"); return

    bak = LEDGER.with_suffix(f".jsonl.bak-onbox-{time.strftime('%H%M%S')}")
    shutil.copy(LEDGER, bak); log(f"ledger backed up -> {bak.name}")

    q = queue.Queue()
    for i in iids: q.put(i)
    threads = [threading.Thread(target=worker, args=(env, q, len(iids)), name=env["name"])
               for env in fleet]
    for t in threads: t.start()
    for t in threads: t.join()

    graded = {k: v for k, v in _results.items() if v is not None}
    wins = sum(1 for v in graded.values() if v)
    none = [k for k, v in _results.items() if v is None]
    log(f"graded {len(graded)}/{len(iids)} — {wins} WIN, {len(graded)-wins} LOSS; "
        f"{len(none)} still None (requeue)")
    n = rewrite_ledger(_results, iids)
    log(f"ledger rewritten — {n} corrected records")


if __name__ == "__main__":
    main()
