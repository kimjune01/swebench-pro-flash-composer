# Pre-registration — §4.5a Ablation (Gemini 2.5 Flash + Cursor Composer 2.5)

Living dev doc **until frozen (§8)**. At freeze it is tagged and immutable.
Parent: `swebench-pro/PREREGISTRATION.md` (`prereg-pro-v1`). All disciplines
inherited verbatim unless overridden below.

---

## 0. What this is

§4.5a of the inquiry-loop paper: a robustness ablation replacing the parent's
**Sonnet 4.5 + GPT-5.5** pair with **Cursor Composer 2.5 + Gemini 2.5 Flash**
on the same frozen skill contracts (`recon`, `craft`, `audit`).

**The science:** the skills are the independent variable. The models are the
perturbation. Three outcomes:
- System holds → typed skill contracts do the work; model substitution is safe.
- Modest degradation → loop necessary but not sufficient.
- Collapse → model capability dominates; skills are not portable.

**What this is not:** a headline claim, a leaderboard entry, or a capability
test of either model. It is a differential measurement against the parent's
frozen result.

---

## 1. Predicate (inherited from parent §1)

A result is admissible iff:
1. **General** — every harness change is instance-blind, motivated by a
   failure class. Skills are frozen; harness is free game.
2. **Official-attested** — WIN = official Pro grader RESOLVED on the
   source-only diff. Nothing else.
3. **Honest denominator** — exclusions are documented defects only, from the
   parent's pre-run audit (§6 below). No defects added after model results.
4. **Reproducible** — frozen tag, per-instance artifacts committed, runnable
   by a third party.

---

## 2. Two modes (inherited)

- **Exploratory:** any subset, any order, no scoreboard. Phase 0 and dev runs
  are exploratory. Not bound by §3–§5.
- **Measurement:** freeze artifact → run the whole 728 eligible set → that is
  the number. A partial run is **not a headline**; its numerator may not be
  floated.

---

## 3. Restart scope & run order

Verbatim from parent §3:

- **Artifact changed** → rotate the tag, modify, restart the full 728 under
  the new frozen artifact. Prior verdicts are stale, never merged across
  versions. With no quota ceiling and multi-box capacity, a full restart is
  cheap — this is a normal development move, not a last resort.
- **Restarts are unbounded but accountable.** The only obligation is the
  opening entry of the new tag's worklog, written before that tag's run:
  what failure class motivated the change. A result-motivated restart has no
  legitimate failure-class entry to write — that is the guard.
- **Artifact unchanged, infra aborted some instances** → re-run only the
  aborted instances; completed verdicts stand.
- **Run order:** lexicographic sort of all 728 eligible `instance_id`s.
  Committed as `runs/audit/eligible.txt`
  (SHA-256: `c8c73219600f15a4b3b0317cec1fede476092762c82dde08d73489fb77229370`).
  Shard assignment is a deterministic stripe of this order; committed with
  the frozen config.

### 3a. Mac-local multi-shard (cursor-agent is macOS-only)

`cursor-agent` ships a macOS ARM64 Node binary and darwin-arm64 native modules
(`file_service.darwin-arm64.node`, `merkle-tree-napi.darwin-arm64.node`).
Linux x86_64 EC2 is therefore not usable. The run executes as N parallel
`driver/flashcomp_run.py --shard i/N` processes on the local Mac
(arm64, 14 vCPU, 48 GB RAM, OrbStack Docker).

**Committed shard count: 4.** Each process handles a 1/4 deterministic stripe
of the 728 eligible instances (182 per shard). Each writes to its own per-shard
ledger (`runs/scored/run.S{i}of4.jsonl`) to avoid concurrent-write races.
`load_done()` merges all `run.*.jsonl` files to build the resume set.

**Shard-count flexibility (no restart required):** shard count may be adjusted
between sessions (e.g., 4→2 for overnight or 2→4 to catch up). No restart is
required because the eligible set and run order are fixed; adding or removing
shards changes only throughput, not which instances run or what the artifact
computes on them.

**Pruning:** disabled by default when `--shard` is active (concurrent shards
share Docker images; pruning between instances would evict images the sibling
shard is about to pull). Set `FLASH_RUN_PRUNE=1` to force-enable.

**Invariants:**
1. Artifact byte-identical across all shard processes at all times.
2. `load_done()` reads all shard ledgers before each instance — no shard
   attempts an instance already recorded in any sibling shard file.
3. A shard process killed mid-instance produces INCOMPLETE (re-run on restart).
4. No inspection of partial verdicts to decide scaling. Adjusting shard count
   for wall-clock or resource reasons is permitted; "winning/losing too often"
   is optional-stopping leakage → §3 restart.

---

## 4. Failure-mode catalog (inherited)

**The rule: INCOMPLETE → retry. LOSS → stands. No exceptions.**

| state | trigger | counts as | rerun? |
|---|---|---|---|
| **WIN** | loop completed; official grader RESOLVED | win | no |
| **LOSS** | loop completed but not resolved — incl. 0-byte capture, stage timeout, agent error, craft hang, audit parse failure, **harness exception before capture** | loss | **no — stands** |
| **INCOMPLETE** (fault) | enumerated external platform fault before a gradeable diff: `BOX_DEATH` / `DISK_FULL` / `OOM` / `SETUP_NETWORK_FAIL` / `PROVIDER_CRED_REJECT` — detected and logged by the coordinator, never by the pilot itself | not scored; re-run under byte-identical artifact | **yes** |

`PROVIDER_CRED_REJECT` definition (from parent §14 amendment 2026-05-29):
subprocess capture contains verbatim provider rejection string, 0-byte patch,
≥3 consecutive on same box, resolved by fresh credential push. All four
invariants required; any missing → LOSS.

**Craft hang = LOSS.** A craft stage that runs the full `CRAFT_CAP` wall-clock
without emitting a patch is endogenous to the method — it stands as LOSS.
No re-roll, no INCOMPLETE reclassification.

**No instance may be reclassified by discretion after its logs are visible.**

**Who decides (no drift between pilot and coordinator):**
- The **pilot** emits only `WIN` / `LOSS` / `INCOMPLETE(grader-None)`. It NEVER declares an
  external fault. An empty patch (0-byte capture) and any exception raised inside our
  scaffold are *endogenous to the method* and record as `LOSS`. A grader that returns
  `None` (could not produce a verdict, e.g. a Docker outage) records `INCOMPLETE`.
- The **coordinator** is the sole authority for external-fault `INCOMPLETE`
  (`BOX_DEATH` / `DISK_FULL` / `OOM` / `SETUP_NETWORK_FAIL` / `PROVIDER_CRED_REJECT`). It
  detects them across instances (SSH-dead box; the 4-invariant cred-reject test) and
  requeues under the byte-identical artifact. The pilot's `setup failed` (cannot pull/run
  the image) is the one infra signal it may surface, treated as `DISK_FULL`/`NETWORK`.

**Why a billing/quota error is still a LOSS unless all four invariants hold:** from inside
a single instance, a lone provider blip is indistinguishable from the agent simply failing.
Auto-retrying on any API error would be optional-stopping leakage through the back door
(retry until it passes). So the bar is deliberately high and *systematic*: >=3 consecutive
on one box AND resolved by a fresh credential push, coordinator-confirmed. A **harness
exception is our scaffold breaking** — that is our fault and stands as a `LOSS`, never
excused as "infra." Solver incompetence and our scaffold bugs both count; only confirmed
external outages retry.

---

## 5. Stopping rule (inherited)

**Measurement: no early stop.** A run is a headline number only if the full
728 eligible complete under one frozen artifact. A budget-capped partial is
**explicitly invalid for headline claims**. Infrastructure failures (box
death, quota) are the only legitimate interrupts; the run resumes under the
byte-identical artifact.

Score-contingent stops — including "we're losing too often" — are
**optional-stopping leakage**. They convert the run to a non-headline and
require a whole-set restart under a new tag with a documented failure-class
motivation (§3).

---

## 6. Eligible denominator (inherited from parent)

**728 instances** — the parent's §6 defect audit result, frozen before any
scored model run. Committed: `runs/audit/eligible.txt`. This list is **not
re-audited** for the ablation; it is inherited as-is. The parent's audit was
instance-blind with respect to both the parent system and this ablation.

Defects (3, excluded): `instance_NodeBB__NodeBB-00c70ce7…`,
`instance_future-architect__vuls-bff6b755…`,
`instance_ansible__ansible-de5858f4…`.

---

## 7. Reported metrics

- **Denominator = 728.** Every instance whose gold patch grades RESOLVED on
  the official grader is in the denominator — that is the eligible set, fixed
  before any model run. INCOMPLETEs are pending toward that 728, not excluded
  from it. The denominator never shrinks due to infra failures; a run is not
  a headline until all 728 have a terminal verdict (§5).
  **We do not allow our incompetence to modify the test set.**
- **Headline:** resolved / 728 (official), per frozen tag. Stated as:
  "Composer 2.5 + Flash ablation resolved X / 728."
- **Differential:** vs parent's frozen result under `prereg-pro-v1`. The
  comparison isolates the model pair; skills and eligible denominator are
  held constant.
- **No capability claim.** Both Composer 2.5 and Flash 2.5 postdate these
  repos — symmetric contamination, same as parent §12 C2. The differential
  is system-vs-system, not capability-vs-capability.

---

## 8. Freeze mechanism

This document is a living dev doc until we cut the first scored-run tag.
At freeze:
1. Commit this document with the frozen config block (§9 below).
2. Annotated tag `prereg-flash-v1`.
3. SHA recorded in `WORKLOG.md`.

Pre-freeze amendments: new commits + new tags + timestamped rationale; old
tags never move.

**Pre-freeze gate (all must be committed before the tag):**
- [x] Eligible denominator — inherited from parent `prereg-pro-v1` audit.
  `runs/audit/eligible.txt` (728 instances, 3 defects excluded) committed at
  SHA `cbe0770`. Not re-audited; defects are instance-blind w.r.t. this run.
- [x] Frozen config block (§9) — model IDs, stage caps, skill SHAs, grader
  digest, `eligible.txt` SHA. EC2 instance type and watchdog TBD at freeze.
- [x] `runs/audit/run_order.txt` — lexicographic sort of `eligible.txt`,
  committed. 728 lines.
- [x] Batch driver `driver/flashcomp_run.py` — per-shard ledger, merged resume,
  deterministic stripe, RESULT_JSON parsing, pruning disabled in multi-shard.
  Validated end-to-end on navidrome (phase0.sh, WIN ~180s) and
  element-web (phase0.sh, WIN ~245s).
- [x] Mac-local multi-shard architecture committed (§3a). cursor-agent is
  macOS ARM64 only; EC2 not applicable. 4 shards × 182 instances on
  arm64 Mac (14 vCPU, 48 GB RAM, OrbStack). Per-shard ledger files prevent
  concurrent-write races. No watchdog needed: each shard process is bounded
  by per-stage caps (RECON_CAP + CRAFT_CAP + AUDIT_CAP per outer-loop depth).
- [x] Multi-shard validated: 2 shards ran concurrently (ansible-0ea40e09 via
  shard 1/2, ansible-0fd88717 via shard 2/2), both WIN, non-overlapping
  verdicts in run.S1of2.jsonl + run.S2of2.jsonl, merged summary correct.

---

## 9. Frozen config (fill in at freeze)

```
Generator:          Cursor Composer 2.5  (cursor-agent --model composer-2.5)
Adversary/Auditor:  Gemini 2.5 Flash     (gemini-2.5-flash-preview-05-20)
Skills (frozen):
  recon/skill.md    SHA-256: 05e7e31592160f75b989617d099150432dfd2e2f94d231386d1f2b6c3f4e1992
  craft/skill.md    SHA-256: 3652a94a0f45051907680ae89ed23d71cfff8d0c82d14e46e4a72b9516d768ad
  audit/skill.md    SHA-256: c0084b835b7cbe1dcfb0ac41d9f339187e5761a870e9c9984c191e70880ab55d
Harness:            driver/flashcomp_pilot.py
                    SHA-256: bf66d0b527277f8351d4df326e4a8499c08ed3d401cf3dd2c0ce2a1529df6a9c
Batch driver:       driver/flashcomp_run.py
                    SHA-256: 2bda56836592c06c3d55f8cb9f36228c86087c70205ff42903b72692d92945dd
Stage caps:         RECON_CAP=2000s  CRAFT_CAP=3600s  AUDIT_CAP=1200s  MAX_OUTER=5
Eligible list:      runs/audit/eligible.txt
                    SHA-256: c8c73219600f15a4b3b0317cec1fede476092762c82dde08d73489fb77229370
Run order:          runs/audit/run_order.txt  (lexicographic sort of eligible.txt)
Grader:             swe_bench_pro_eval.py
                    SHA-256: bb5d4c5486be296e464e695df3747064aaa3bb197394bc6d39980634afec2034
Execution host:     Mac arm64 (14 vCPU, 48 GB RAM, OrbStack Docker)
Shard count:        4 parallel flashcomp_run.py processes (--shard 1/4 … 4/4)
Per-stage caps:     RECON_CAP=2000s  CRAFT_CAP=3600s  AUDIT_CAP=1200s
```

---

## 10. Provenance (inherited)

Every instance (WIN, LOSS, INCOMPLETE) is committed as its own artifact:
ledger entry, captured source-only diff, official report, agent logs, fault
codes. Losing runs stay in history. The number is re-derivable from commits,
not asserted. Per parent §14 amendment: **the run is not a headline until
per-instance trajectories + diffs are published**, not merely the ledger.
