#!/usr/bin/env python3
"""regrade_from_patches.py — re-grade captured patches whose grade returned None.

When the local grader (Mac Docker) was down, official_grade() returned None for
every instance and the coordinator recorded them as LOSS even though the agent had
produced a patch (agent_verdict=RESOLVED).  The patches were persisted to
runs/dev/fc_pred_<tag>.json + fc_sample_<tag>.jsonl, so we can grade them now
without re-running a single agent.

  python3 driver/regrade_from_patches.py            # regrade all official_resolved=None LOSSes
  python3 driver/regrade_from_patches.py --dry-run  # show what would be regraded

Rewrites runs/scored/run.jsonl in place (backup written first): the stale None-LOSS
rows are dropped and replaced with corrected records carrying the real verdict.
"""
import argparse, json, pathlib, shutil, subprocess, sys, time, os

REPO   = pathlib.Path(__file__).resolve().parent.parent
DEV    = REPO / "runs" / "dev"
LEDGER = REPO / "runs" / "scored" / "run.jsonl"
GRADER = pathlib.Path(os.environ.get("SWEAP_OS_REPO", "/tmp/swebench-pro-os"))
PY     = sys.executable
DOCKERHUB = os.environ.get("DOCKERHUB_USER", "jefzda")


def log(m): print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def target_instances():
    """instance_ids of LOSS records whose detail says official_resolved=None."""
    seen, out = set(), []
    for line in LEDGER.read_text().splitlines():
        try: r = json.loads(line)
        except Exception: continue
        if (r.get("state") == "LOSS"
                and "official_resolved=None" in r.get("detail", "")
                and r["instance_id"] not in seen):
            seen.add(r["instance_id"]); out.append(r["instance_id"])
    return out


def build_batch(iids, work):
    """Concatenate persisted per-instance sample rows + patches into batch files."""
    samp = work / "regrade_sample.jsonl"
    pred = work / "regrade_pred.json"
    rows, patches, ok = [], [], []
    for iid in iids:
        tag = iid.replace("/", "_")
        s = DEV / f"fc_sample_{tag}.jsonl"
        p = DEV / f"fc_pred_{tag}.json"
        if not (s.exists() and p.exists()):
            log(f"  SKIP {iid} — missing persisted sample/pred"); continue
        rows.append(s.read_text().strip())
        patches.extend(json.load(open(p)))
        ok.append(iid)
    samp.write_text("\n".join(rows) + "\n")
    json.dump(patches, open(pred, "w"))
    return samp, pred, ok


def run_grader(samp, pred, out_dir, workers):
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [PY, "swe_bench_pro_eval.py",
           "--raw_sample_path", str(samp), "--patch_path", str(pred),
           "--output_dir", str(out_dir), "--scripts_dir", "run_scripts",
           "--num_workers", str(workers), "--use_local_docker",
           "--dockerhub_username", DOCKERHUB, "--redo"]
    log(f"  grader: {' '.join(cmd)} (cwd={GRADER})")
    subprocess.run(cmd, cwd=GRADER)
    res = out_dir / "eval_results.json"
    if not res.exists():
        return {}
    data = json.load(open(res))
    norm = {}
    for iid, val in data.items():
        if isinstance(val, bool):   norm[iid] = val
        elif isinstance(val, dict): norm[iid] = val.get("resolved")
        else:                       norm[iid] = None
    return norm


def rewrite_ledger(verdicts, targets):
    """Drop stale None-LOSS rows for regraded iids; append corrected records."""
    targets = set(targets)
    kept = []
    for line in LEDGER.read_text().splitlines():
        try: r = json.loads(line)
        except Exception:
            kept.append(line); continue
        if (r.get("instance_id") in targets and r.get("state") == "LOSS"
                and "official_resolved=None" in r.get("detail", "")):
            continue   # drop the stale false-LOSS
        kept.append(line)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    new = []
    for iid, resolved in verdicts.items():
        if resolved is None:
            continue   # still ungradable — leave it OUT of the ledger so it requeues
        new.append(json.dumps({
            "instance_id": iid,
            "state": "WIN" if resolved else "LOSS",
            "detail": f"official_resolved={resolved} agent_verdict=RESOLVED (regraded)",
            "secs": 0, "regraded_at": now,
            "model_pair": "gemini-2.5-flash+composer-2.5",
        }))
    LEDGER.write_text("\n".join(kept + new) + "\n")
    return len(new)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    iids = target_instances()
    log(f"false-LOSS (official_resolved=None) to regrade: {len(iids)}")
    if not iids:
        log("nothing to regrade"); return
    if args.dry_run:
        for i in iids: print("  ", i)
        return

    bak = LEDGER.with_suffix(f".jsonl.bak-{time.strftime('%H%M%S')}")
    shutil.copy(LEDGER, bak); log(f"ledger backed up -> {bak.name}")

    work = DEV / "regrade"; work.mkdir(parents=True, exist_ok=True)
    samp, pred, ok = build_batch(iids, work)
    log(f"batched {len(ok)} instances")

    out_dir = work / "out"
    verdicts = run_grader(samp, pred, out_dir, args.workers)
    graded = {k: v for k, v in verdicts.items() if v is not None}
    wins = sum(1 for v in graded.values() if v)
    log(f"grader returned {len(graded)}/{len(ok)} real verdicts — {wins} WIN, {len(graded)-wins} LOSS")
    still_none = [i for i in ok if verdicts.get(i) is None]
    if still_none:
        log(f"{len(still_none)} STILL None (grader failed) — left out of ledger to requeue:")
        for i in still_none[:10]: log(f"    {i}")

    n = rewrite_ledger(verdicts, ok)
    log(f"ledger rewritten — {n} corrected records written")


if __name__ == "__main__":
    main()
