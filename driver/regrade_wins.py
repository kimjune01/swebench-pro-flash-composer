#!/usr/bin/env python3
"""regrade_wins.py — skeptical re-grade of WIN patches through the official grader.

Re-grades the persisted patch of each WIN instance on a fresh box fleet and records
the verdict to a SEPARATE ledger (runs/scored/regrade_win.jsonl) WITHOUT touching the
original run.jsonl — so we can compare original-WIN vs re-grade and count flips.

Same grader → deterministic for a correct patch; this catches flaky / nondeterministic /
serialization / operator-mitigation false-WINs, NOT weak-test-coverage inflation (that
needs stronger tests). Prunes images per-grade so the box disk can't fill.

Box pool: /tmp/wincheck*.env  (provision separately; does NOT touch coordinator boxes).

  python3 driver/regrade_wins.py --sample 60      # stratified sample across repos
  python3 driver/regrade_wins.py                  # all WINs
  python3 driver/regrade_wins.py --dry-run
"""
import argparse, json, pathlib, queue, subprocess, threading, time, glob, collections

REPO    = pathlib.Path(__file__).resolve().parent.parent
DEV     = REPO / "runs" / "dev"
LEDGER  = REPO / "runs" / "scored" / "run.jsonl"
OUT     = REPO / "runs" / "scored" / "regrade_win.jsonl"
DHUB    = "jefzda"

_lock = threading.Lock()
_results = {}   # iid -> {"orig": True, "regrade": bool|None}

def log(m): print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)

def boxes():
    out = []
    for f in sorted(glob.glob("/tmp/wincheck*.env")):
        env = {}
        for line in open(f):
            if "=" in line:
                k, v = line.strip().split("=", 1); env[k] = v
        if env.get("PUBIP") and env.get("KEY"):
            env["name"] = pathlib.Path(f).stem
            out.append(env)
    return out

def win_instances(sample=0):
    """Distinct current-WIN instances (last-wins). Optionally a stratified sample."""
    recs = {}
    for line in LEDGER.read_text().splitlines():
        try: r = json.loads(line)
        except Exception: continue
        recs[r["instance_id"]] = r
    wins = [i for i, r in recs.items() if r.get("state") == "WIN"]
    # only those with a persisted patch to re-grade
    wins = [i for i in wins if (DEV / f"fc_sample_{i.replace('/','_')}.jsonl").exists()]
    if not sample or sample >= len(wins):
        return sorted(wins)
    # stratify by repo so the sample spans the distribution
    by_repo = collections.defaultdict(list)
    for i in wins: by_repo[i.split("__")[0]].append(i)
    out, repos = [], sorted(by_repo)
    idx = 0
    while len(out) < sample:
        r = repos[idx % len(repos)]
        if by_repo[r]: out.append(by_repo[r].pop())
        idx += 1
        if all(not v for v in by_repo.values()): break
    return sorted(out)

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
    rdir = f"/tmp/wcgrade_{tag}"
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
        # reclaim: drop the grade container + the multi-GB instance image so disk stays bounded
        _ssh(env, "docker container prune -f >/dev/null 2>&1; docker image prune -af >/dev/null 2>&1", 180)
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
            _results[iid] = {"orig": True, "regrade": resolved}
            n = len(_results)
        flip = "" if resolved is True else (" <-- FLIP" if resolved is False else " (None)")
        log(f"{env['name']}: {iid[:46]} -> {resolved}{flip}   ({n}/{total})")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=0, help="stratified sample size (0=all)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    fleet = boxes()
    iids  = win_instances(args.sample)
    log(f"wincheck boxes={len(fleet)}  WINs to re-grade={len(iids)}"
        + (f"  (sample of all WINs)" if args.sample else ""))
    if args.dry_run:
        for i in iids: print("  ", i)
        return
    if not fleet:
        log("no /tmp/wincheck*.env boxes — provision a wincheck fleet first"); return

    q = queue.Queue()
    for i in iids: q.put(i)
    threads = [threading.Thread(target=worker, args=(env, q, len(iids)), name=env["name"])
               for env in fleet]
    for t in threads: t.start()
    for t in threads: t.join()

    graded = {k: v for k, v in _results.items() if v["regrade"] is not None}
    flips  = [k for k, v in graded.items() if v["regrade"] is False]
    none   = [k for k, v in _results.items() if v["regrade"] is None]
    log(f"re-graded {len(graded)}/{len(iids)}: {len(graded)-len(flips)} reproduced WIN, "
        f"{len(flips)} FLIPPED to LOSS, {len(none)} ungraded(None)")
    if flips:
        log("FLIPS (original WIN -> re-grade LOSS):")
        for k in flips: log(f"  {k}")
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(OUT, "w") as f:
        for iid, v in _results.items():
            f.write(json.dumps({"instance_id": iid, "orig_state": "WIN",
                                "regrade_resolved": v["regrade"], "regraded_at": now}) + "\n")
    log(f"wrote {OUT.name} ({len(_results)} records) — original run.jsonl untouched")

if __name__ == "__main__":
    main()
