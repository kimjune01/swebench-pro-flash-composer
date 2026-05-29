# swebench-pro-flash-composer

The inquiry-loop harness on **SWE-bench Pro**, dispatched against **Cursor's Composer 2.5** (craft) +
**Gemini 3.5 Flash** (audit). Sibling to [`swebench-pro`](https://github.com/kimjune01/swebench-pro)
(Sonnet 4.5 + GPT-5.5 codex) — one repo per *number*, one number per *model pair*.

**Purpose:** §4.5a cheap-ablation companion to the inquiry-loop paper
(`june.kim/the-inquiry-loop-on-swebench-pro`). The paper's argument is that **reasoning lives at the
harness layer** — the recon→craft→audit prose pipeline is the reusable IR, the model pair is the
substrate. This repo is the experimental apparatus that operationalizes that claim by varying *only
the model pair* against the same problem set + same prompts + same verdict mechanism.

## What's invariant vs what varies (the controlled experiment)

| Carries from `swebench-pro` (frozen) | Varies in this repo |
|---|---|
| `skills/{recon,craft,audit}/skill.md` (prose) | Model dispatch + CLI invocations |
| `runs/audit/eligible.txt` (the 728 set) | Per-box stack (cursor-agent + gemini-cli) |
| The Pro grader (`swe_bench_pro_eval.py`) | Coordinator + operator infra (rewritten) |
| Per-instance verdict semantics (WIN/LOSS/INCOMPLETE) | Auth (CURSOR_API_KEY + GEMINI_API_KEY, not Max OAuth) |

Skill prompts are vendored from `swebench-pro/skills/` at the freeze SHA — they're the load-bearing
artifact of the controlled experiment and must not drift between the two runs.

## What's new (the unknowns)

- **Cursor only ships a CLI**, no API surface. Every craft phase is a `cursor-agent` subprocess.
- **DeepSWE lessons table (operational gotchas) is load-bearing here.** `--trust --workspace` mandatory,
  `CURSOR_API_KEY` doesn't survive bash spawn, foreground+pid-wait > async, monitor by log size growth,
  self-reported gate result untrusted beyond n=1, `pgrep` false positives on the eval-string.
- **Concurrency ceiling** is whatever Cursor's account tolerates — replaces "Sonnet Max quota" as the
  binding constraint. Unknown until we measure.
- **Per-call cost** — Cursor + Gemini APIs are paid. Budget unknown until phase 0 measures one instance.

## Phasing

- **Phase 0** — proof of pipeline. One box, one Pro instance, end-to-end with the new model pair.
  Get any verdict (WIN, LOSS, INCOMPLETE) parseable into the ledger. Validates the pipeline shape
  before any scale work. ~1 day.
- **Phase 1** — coordinator + N-way EC2 fleet. Reuse `swebench-pro`'s coordinator pattern (one
  Python orchestrator dispatching to N boxes); replace claude/codex dispatch with cursor-agent /
  gemini-cli. Build forward the operator infra (watchdog, drain, retry, heartbeat). 10-20 instances.
  ~2-3 days.
- **Phase 2** — hardening + scored run. Decide subset vs full 728. Capture provenance + run. ~1-2 days.

## Disclosure stance

This run uses the same prereg posture as `swebench-pro` (per-instance receipts, frozen artifact, no
solver-weakening). A `§0.2-style amendment` at freeze time documents the model-pair swap; the rest
of the discipline (KNOWN_BAD reserved for verifiable platform defects, no test-file edits, etc.)
carries over identically. See `docs/PREREGISTRATION.md`.

## Layout (planned)

```
skills/             → symlinked from ../swebench-pro/skills (frozen prompts, the carried artifact)
driver/             → new orchestration: cursor-agent + gemini-cli dispatch, coordinator, watchdog
runs/
  audit/eligible.txt   → copy of swebench-pro/runs/audit/eligible.txt at freeze SHA
  scored/              → this run's ledger, artifacts, kill log, heartbeat
docs/
  PREREGISTRATION.md   → §0.2 amendment + invariants
  bench-defects.md     → cursor-agent + gemini-cli + grader bugs (likely starts empty, grows from phase 1)
  retros/              → as they accumulate
```

## License

Dual: GPL-3.0 (code) OR CC BY-SA-NS (prose), recipient's choice. See [`LICENSE.md`](LICENSE.md).

## Status

**Phase 0 not yet run.** Repo scaffolded; awaiting API keys + go-ahead to provision the first box.

See [`swebench-pro/WORKLOG.md`](https://github.com/kimjune01/swebench-pro/blob/main/WORKLOG.md)
"2026-05-29" entries for the main run's current status (96.7% on 424/728 graded).
