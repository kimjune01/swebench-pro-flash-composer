# Attestation and reproducibility

Every verdict in this run is backed by committed, re-gradable artifacts. Nothing here
requires trusting our tally; you can regenerate it.

## What's committed

| Artifact | What it is |
|----------|------------|
| `runs/scored/run.jsonl` + `run.S*of*.jsonl` | The ledgers. Headline = merged last-wins (use `score-pro`, which now globs `run*.jsonl`). Final: 678/728 = 93.1% resolved. |
| `runs/scored/regrade_win.jsonl` | The skeptical WIN re-grade: 60 stratified WINs re-graded on a clean independent box. 60/60 reproduced, 0 flips. |
| `runs/scored/artifacts.tar.zst` | Per-instance evidence (15M zstd). See below. |
| `PREREGISTRATION.md` | Frozen scoring rules (sec.4 table, sec.6 denominator). |
| `WORKLOG.md` | Full narrative, including every incident and correction. |

## The artifact bundle

```bash
tar --use-compress-program=unzstd -xf runs/scored/artifacts.tar.zst
```

Per instance (`<iid>` = instance_id):
- `runs/dev/fc_pred_<iid>.json` + `fc_sample_<iid>.jsonl` — the patch + grader inputs (re-grade with these)
- `runs/dev/fc_patch_<iid>.diff` — the source-only diff (test files stripped)
- `runs/dev/fc_hgraph_<iid>.md` — the inquiry graph (recon/audit per iteration)
- `runs/dev/fc_prompt_<tag>.txt` + `fc_out_<tag>.txt` — exact model prompts and outputs (full provenance)
- `runs/dev/fc_fingate_<iid>_d*.txt`, `fc_failbase_<iid>.txt` — gate output, pre-patch baseline

Excluded: `fc_ws_*` (cursor-agent scratch workspaces, reproducible, ~112M).

## Re-grade any WIN yourself

```bash
# on a box with docker + the Pro grader (see driver/provision_box.sh):
python3 swe_bench_pro_eval.py \
  --raw_sample_path fc_sample_<iid>.jsonl --patch_path fc_pred_<iid>.json \
  --output_dir out --scripts_dir run_scripts --num_workers 1 \
  --use_local_docker --dockerhub_username jefzda --redo
```

`driver/regrade_wins.py` automates this across a fleet (writes to `regrade_win.jsonl`,
never mutates `run.jsonl`).

## What this attests, and what it doesn't

- **Attests:** every WIN is a real, reproducible pass of the official Pro grader on the
  committed patch. The sampled re-grade (0 flips) shows they're not grader flakes or
  serialization artifacts.
- **Does NOT attest:** that each passing patch is *correct* in the sense a strengthened
  test suite would demand. SWE-bench Pro's F2P tests can pass a wrong-but-plausible patch.
  That coverage axis needs the UTBoost stronger tests, which is a separate run not done here.
