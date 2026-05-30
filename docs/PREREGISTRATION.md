# Pre-registration — SWE-bench Pro, Flash+Composer ablation

**Status: OPEN (not frozen — pre-scored-run).**

This document governs the scored measurement for
[`swebench-pro-flash-composer`](https://github.com/kimjune01/swebench-pro-flash-composer).
It inherits from and is a companion to the parent preregistration at
[`swebench-pro/PREREGISTRATION.md`](https://github.com/kimjune01/swebench-pro/blob/main/PREREGISTRATION.md)
(the Sonnet 4.5 + GPT-5.5 headline run). See also
[`swebench-pro/PREREGISTRATION-cheap-ablation.md`](https://github.com/kimjune01/swebench-pro/blob/main/PREREGISTRATION-cheap-ablation.md)
(the planning document this run operationalizes).

---

## 0. Import

Every discipline from `swebench-pro/PREREGISTRATION.md` at the `prereg-pro-v1` SHA carries over:
predicate (§1), two modes (§2), restart scope (§3), failure-mode state machine (§4), overnight
recovery (§4a), stopping rule (§5), eligible denominator (§6 — **728**), provenance (§10),
Q1–Q22 checklist (§11), confound discipline (§12), freeze mechanism (§13). The sections below
state the deltas only; everything not named here is in force unchanged.

---

## 1. Scientific purpose (the §4.5a hypothesis)

The parent run pairs Sonnet 4.5 + GPT-5.5 through a recon→craft→audit pipeline. The open
question: **how much of the resolve rate is the pipeline structure, and how much is
frontier-model capability?**

This run answers it by substituting a **cheaper operational stack** while holding fixed
everything that can be held fixed: the 728 eligible instances, the vendored skill prompts,
the official Pro grader, the source-only capture logic, and the verdict semantics. The two
configurations differ in model pair and one structural detail (codex volley absent here —
see §2A). The net comparison is cheap operational stack vs frontier stack, which is the
§4.5a question.

### 1.1 Pre-committed readings

The three readings from `PREREGISTRATION-cheap-ablation.md §3` carry over with numeric
thresholds:

| Cheap-stack rate vs parent | Threshold | Reading |
|---|---|---|
| **Comparable** | Within ±3 percentage points | Pipeline structure is the primary lever; model tier is secondary. Strongest claim. |
| **Modestly lower** | 3–15 pp below parent | Pipeline necessary but not sufficient; hard-tail repos need frontier capability. |
| **Collapses** | > 15 pp below parent | Frontier capability dominates; pipeline structure helps marginally. |

These thresholds are pre-committed. Whichever band the result lands in (by point estimate),
receipts publish per §10. Band assignment is based on the point estimate alone; CI crossing
a threshold boundary does not reclassify the result. CIs are reported alongside the point
estimate as uncertainty quantification.

### 1.2 Primary estimand and statistical plan

**Primary estimand:** per-instance WIN rate on all 728 eligible instances that receive a
terminal verdict (WIN or LOSS) under the frozen run. The 95% Wilson CI is the primary
interval for the rate itself.

**Confirmatory comparison gate:** no confirmatory paired comparison is reported unless all
728 eligible instances receive a terminal WIN or LOSS verdict. A partial run reports a rate
over completed instances, labeled `partial-run`, but is not used for the primary comparison.

**Paired delta:** this run's rate minus the parent's rate. The parent artifact for pairing
is `swebench-pro/runs/scored/run.jsonl` at git tag `prereg-pro-v1` (file blob SHA to be
recorded in `WORKLOG.md` before phase 2). Parent INCOMPLETEs are treated as LOSS in the
denominator for the delta calculation, consistent with parent §4 anti-cheat rules. The
pairing is by instance ID across the same 728 eligible instances.

**Bootstrap CI on the delta:** 10,000 resamples; resampling unit is instance ID over the
728 paired observations; statistic is mean of `(cheap_win_i - parent_win_i)` where
`cheap_win_i` and `parent_win_i` are both 0/1 per instance; CI type is BCa (bias-corrected
and accelerated); random seed 42. Treatment of instances where one run is INCOMPLETE and the
other is terminal: impute the INCOMPLETE as 0 (LOSS) per the anti-cheat rule.

**No sub-group pre-registration** for this run. Repo-level breakdowns are exploratory:
they cannot override the primary interpretation band, cannot be used to exclude repos
post-hoc, and must be labeled uncorrected/exploratory in any report.

---

## 2. What changes (deltas vs. parent `prereg-pro-v1`)

### 2.1 Model pair — Gemini 2.5 Flash + Cursor Composer 2.5

Replaces parent §7 ("Sonnet 4.5 generator + GPT-5.5 craft challenger") with:

| Stage | Model | CLI | Role |
|---|---|---|---|
| **recon** | Cursor Composer 2.5 (`composer-2.5`) | `cursor-agent --print --model composer-2.5 --trust --workspace --yolo` | Read-only codebase exploration; runs `bash {box}` to read files and `bash {gate}` to observe failures; outputs structured handoff to craft |
| **craft** | Cursor Composer 2.5 (`composer-2.5`) | `cursor-agent --print --model composer-2.5 --trust --workspace --yolo` | Implementation; iterates the gate directly |
| **audit** | Gemini 2.5 Flash (`gemini-2.5-flash`) | `google-genai` Python SDK | Reads the patched tree; outputs structured judgment; does NOT determine WIN/LOSS |

**Provider diversity.** Composer (recon + craft) runs on Cursor's API; Gemini Flash (audit
only) is Google infrastructure. These are operationally distinct providers billed separately.
The cheaper-operational-stack framing does not require confirmed distinct training.

**No codex volley.** The parent craft invokes GPT-5.5 (codex) as an adversarial challenger
inside the craft loop. This run omits that step — Composer iterates the gate directly. The
full implications are enumerated in the Harness Equality Contract (§2A). This is the primary
structural difference between the two configurations.

**Gate definition.** The craft gate Composer iterates is the local test suite available at
the repo's `base_commit` state — the tests that existed in the repository before any
SWE-bench test patch is applied. Composer sees pass/fail output from these pre-existing
tests but does not have access to: the official grader verdict, the FAIL_TO_PASS/PASS_TO_PASS
gold test set, or any test patch material from the SWE-bench evaluation harness. The gold
evaluation tests are added by the grader during `swe_bench_pro_eval.py` execution, which
occurs after craft completes and on the source-only captured diff. The gate is "cleared"
when pre-existing local tests pass or the `CRAFT_CAP` wall time is reached. Audit runs
afterward and its output informs the provenance record but does not gate WIN/LOSS
determination.

**Audit vs. official grader.** Final WIN/LOSS is determined solely by the official grader
(`swe_bench_pro_eval.py`) on the source-only patch. The audit step produces a structured
judgment (RESOLVED/NOT_RESOLVED/PARTIAL + rationale) committed to `runs/dev/` for
interpretive analysis but plays no role in verdict computation.

### 2.2 Auth

- **Gemini:** `GEMINI_API_KEY` (Google AI Studio key, 39 chars). Billing: Google's pay-as-you-go.
- **Composer:** `CURSOR_API_KEY` (Cursor API key, 69 chars). Billing: Cursor API.
- **No Max OAuth / ANTHROPIC_API_KEY.** Claude is not invoked in this run.

AUTH_ASSERT (before each scored run): both CLIs successfully complete a trivial instruction-
following task ("Reply with only the word: OK") without error. A non-error response that
ignores the instruction does not satisfy AUTH_ASSERT.

### 2.3 Scope — Pro only (728 eligible)

Same eligible denominator as the parent (`runs/audit/eligible.txt`, inherited from
`swebench-pro` §6 audit at the freeze SHA). No re-audit needed; defect list is frozen.
No Verified companion run.

File hashes to be captured in `WORKLOG.md` before phase 2:
- SHA256 of `runs/audit/eligible.txt` (this repo)
- SHA256 of `tasks/run_order.txt` (this repo)
- git blob hash of `swebench-pro/runs/audit/eligible.txt` at `prereg-pro-v1`

### 2.4 Budget cap

**$300 hard cap** (projected ~$120 for 728 instances at ~$0.16/instance combined
Flash+Composer; cap absorbs EC2 box-hours ~$30-50 + cost overruns from INCOMPLETE re-runs
per §4). At cap, the run is PAUSE(QUOTA_EXHAUSTED) per parent §4; partial results publish
per §10 as non-headline.

**Per-instance retry ceiling:** each instance may receive at most 2 total invocations
(initial + one INCOMPLETE re-run, if and only if a corroborated platform fault exists).
The container-leak retry does not count against this ceiling because it reflects a
grader-infra defect, not an agent invocation. This ceiling bounds per-instance cost.

**Partial-run bias note.** Run order is lexicographic (see §3). If the run halts before
completing all 728 instances, the reported rate is over a non-random prefix (alphabetically
sorted by instance ID). This prefix bias is disclosed; partial results are labeled
`partial-run` and are not used as the headline comparison.

### 2.5 Parallelism — up to 8 boxes (phase 1 target)

Phase 1 target: **8 boxes × ~23 instances/box** at ~15 min/instance ≈ ~46h wall clock.
Shard assignment is a deterministic stripe of the global lexicographic order.

**Shard failure rule.** If a box dies mid-shard: (a) continue remaining shards; (b) the
failed shard's instances are collected, de-duplicated against already-terminal ledger
entries, and re-run as a suffix batch in global order. The partial-prefix guarantee holds
only if no shard fails; with failures, report the actual execution order in `WORKLOG.md`.

Confirmed concurrency ceiling is unknown until measured; Cursor API + Google API rate limits
are the binding constraints, not model quota.

### 2.6 Freeze tag

This artifact freezes as **`prereg-fc-v1`** (annotated tag). SHA recorded in `WORKLOG.md`
before the scored run begins. Amendments follow parent §13: new commit + new tag +
timestamped rationale; old tags never move.

---

## 2A. Harness equality contract

This section enumerates what is **exactly the same** as the parent and what **differs**, so
the comparison can be assessed without reading both preregistrations simultaneously.

### Same as parent

| Component | Status |
|---|---|
| Eligible instance set | Identical (`runs/audit/eligible.txt`, 728 instances) |
| Run order | Identical (`tasks/run_order.txt`, lexicographic, same frozen SHA) |
| Skill prompts | Identical (vendored at SHA `63215e8`; per-file hashes below) |
| Grader | Identical (`swe_bench_pro_eval.py`, official harness, no patches) |
| Grader invocation | Identical (same image tag, flags, timeout, env — to be committed in machine-readable run config before phase 2) |
| Source-only capture | Identical (`_strip_test_blocks` logic; file vendored from parent with SHA check — see §3) |
| Verdict semantics | Identical (WIN/LOSS/INCOMPLETE per parent §4) |
| Failure-mode state machine | Identical (same INCOMPLETE re-run triggers, anti-cheat rules) |
| Redis-flake watchdog | Identical (same kick logic, same logging target) |
| Container-leak cleanup | Identical (same reap logic, one retry before accepting LOSS) |

**Per-file skill prompt hashes** (to be populated from `git hash-object` before phase 2):

| File | SHA (at commit 63215e8) |
|---|---|
| `skills/recon/skill.md` | `26576d5862d99a6db53cbce4a716c12af36aeaf6` |
| `skills/craft/skill.md` | `6d608c07708ef8d5ee9f1bca33999710aceaff92` |
| `skills/audit/skill.md` | `0e52d3f2154b204b7090e5abe36a3648cb0d9b64` |

### Differs from parent

| Component | Parent | This run | Interpretive impact |
|---|---|---|---|
| Recon model | Sonnet 4.5 | Cursor Composer 2.5 | Both use tool-use to explore codebase; prompt is same; Composer can run `bash {box}` |
| Craft model | Sonnet 4.5 | Cursor Composer 2.5 | Core implementation capability change |
| Craft adversary | GPT-5.5 codex volley | None (Composer iterates gate directly) | Removes one challenge layer from the craft loop |
| Audit model | GPT-5.5 | Gemini 2.5 Flash | Audit judgment may differ; prompt is same; audit is non-scoring |
| Auth provider | Anthropic Max + OpenAI | Google AI Studio + Cursor API | Operational only |
| EC2 platform (phase 1) | Linux x86_64 native | Linux x86_64 (pending cursor-agent binary) | Phase 0 runs Mac/OrbStack emulation |

The codex-volley removal is the only **structural** harness change. Everything else is a model
substitution under the same prompt. The scientific comparison is: "cheaper operational stack
without codex adversary" vs "frontier stack with codex adversary." Model tier and adversary
step co-vary; they are not independently controlled.

---

## 3. What does NOT change (explicit)

- **Eligible denominator:** 728 (from parent §6 audit; inherited, no re-audit).
- **Run order:** `tasks/run_order.txt` from sibling (lexicographic, frozen at `prereg-pro-v1` SHA).
  Shard assignment is a deterministic stripe of this order.
- **Skill prompts:** `skills/{recon,craft,audit}/skill.md` — vendored verbatim from `swebench-pro`
  at SHA `63215e8`. These are the load-bearing artifact of the controlled experiment; **do not
  edit**. Runner bugs (in `driver/`) are fixable; skill prompts are not.
- **Grader:** `swe_bench_pro_eval.py` (official SWE-bench Pro harness). No bespoke graders.
  Verdict = official grader's boolean on the captured source-only diff. Exact invocation
  (command, Docker image digest, flags, env) committed as a machine-readable run config before
  phase 2.
- **Source-only capture:** `_strip_test_blocks` logic vendored from parent. The file's SHA256
  hash is checked against the parent's copy before each scored run to confirm identity.
- **Failure-mode state machine:** WIN / LOSS / INCOMPLETE / PAUSE as in parent §4.
  - INCOMPLETE re-run trigger: logged platform fault only (Cursor API outage corroborated by
    status.cursor.com, or Google Cloud corroborated by status.cloud.google.com).
  - INCOMPLETE without corroborating fault evidence → reclassifies to LOSS (anti-cheat, parent
    §4). This holds even if raw logs show 5xx or rate-limit behavior without public corroboration.
- **Bench defects:** redis-flake and container-leak mitigations from `docs/bench-defects.md`
  carry over. Grader watchdog logic inherited (to be ported in phase 1 coordinator).
- **Provenance:** per-instance patches, trajectories, gate outputs, fault codes, cost ledger —
  committed artifacts per parent §10.

---

## 4. Operator-level mitigations (disclosure per parent §14 discipline)

The following operator-layer workarounds are **not** hidden:

1. **Redis-flake watchdog (inherited):** if the Pro grader hangs on "Waiting for Redis to
   start", a watchdog kicks `redis-server` inside the container. This helps the bench's
   intended infra state actually obtain; it does not affect test outcomes. See
   `docs/bench-defects.md`.

2. **Container-leak cleanup (inherited):** orphan grader containers are reaped between
   instances. Kills are logged to `runs/scored/grader_kills.jsonl`; any matching LOSS is
   retried once before being accepted as a real LOSS.

3. **`--platform linux/amd64` emulation (phase 0 only):** phase 0 runs on Mac/OrbStack
   under amd64 emulation. Native EC2 is phase 1. Results under emulation are labeled
   `dev-mode` and are not part of the headline scored run.

**No operator intervention rule.** During the scored phase 2 run, the operator may not:
manually edit any patch, modify any prompt for a specific instance, re-run any instance
outside the predefined PAUSE/INCOMPLETE rules, selectively cancel or delay any instance,
or alter run order. Infrastructure fixes (SSH, container cleanup) are permitted under the
`[runner-fix]` protocol in §9.

---

## 5. Phase separation and artifact isolation

- Phase 0 and phase 1 (dev-mode and calibration) results are written to `runs/dev/`.
- Phase 2 (scored) results are written to `runs/scored/`.
- The headline analysis reads exclusively from `runs/scored/run.jsonl`.
- Each record in `runs/scored/run.jsonl` carries a `phase` field (`"scored"`) to allow
  mechanical filtering even if paths are merged in future tooling.
- Dev-mode records in `runs/dev/` are not used in any numeric comparison against the parent.

---

## 6. EC2 cursor-agent constraint (phase 0 blocker, phase 1 dependency)

The cursor-agent bundle ships macOS ARM64 native Node.js modules
(`file_service.darwin-arm64.node`, `merkle-tree-napi.darwin-arm64.node`). These do not
install on Linux x86_64 without a separate Linux build from Cursor. **Phase 0 therefore runs
locally on Mac (dev mode); EC2 deployment is deferred to phase 1** pending a Linux
cursor-agent binary.

Unblocking path for phase 1: obtain the Linux x86_64 cursor-agent build from Cursor and
wire it into `driver/bootstrap_ec2.sh`. Until then, the coordinator and watchdog patterns
from `swebench-pro/driver/coordinator.py` are not yet deployed for this repo.

---

## 7. Phasing

| Phase | Description | Status |
|---|---|---|
| **Phase 0** | One box, one Pro instance, end-to-end verdict (WIN/LOSS/INCOMPLETE). Validates pipeline shape before scale work. Dev mode (Mac/OrbStack). Output to `runs/dev/`. | In progress |
| **Phase 1** | EC2 fleet (N boxes, coordinator + watchdog), full grader-watchdog port, cursor-agent Linux install. 10-20 instances for calibration. Output to `runs/dev/`. | Pending EC2 cursor-agent unblock |
| **Phase 2** | Frozen scored run on full 728 eligible set. Tag `prereg-fc-v1` cut. Output to `runs/scored/`. | Not started |

The phase 0 deliverable is **any parseable verdict** in `runs/dev/flashcomp_run.jsonl`. The
headline number comes from phase 2 only.

---

## 8. Run-time controls

These values govern every instance in the scored run and are frozen before phase 2 begins.
Changes trigger a version split per §9 (Taint Rules). The freeze gate (§12 checklist)
requires a concrete value for every TBD row before `prereg-fc-v1` is cut.

| Control | Value | Purpose |
|---|---|---|
| `RECON_CAP` | 2000s | Max wall time for gemini recon call |
| `CRAFT_CAP` | 3600s | Max wall time for cursor-agent craft call |
| `AUDIT_CAP` | 1200s | Max wall time for gemini audit call |
| `FLASH_MODEL` | `gemini-2.5-flash` | Gemini model ID used for recon + audit |
| `COMPOSER_MODEL` | `composer-2.5` | Composer model ID used for craft |
| Craft gate iterations | [TBD — set by phase 0 calibration; must be concrete before freeze] | Times Composer invokes the local test gate before accepting result |
| Codex volley | None | Not invoked in this run |
| Concurrency | 8 boxes (phase 1 target) | Worker count ceiling |
| Per-instance retry ceiling | 2 total invocations max | 1 initial + 1 INCOMPLETE re-run if corroborated |

"One craft gate iteration" = one Composer subprocess invocation that may internally loop
over patch/test cycles up to `CRAFT_CAP` seconds. The outer retry ceiling (2 total) governs
invocations of `cursor-agent`, not internal Composer cycles.

These are logged per-instance in `runs/scored/run.jsonl`. Any change to the configured
values in this table during a scored run is a PAUSE(TAINT) event and requires a version
split per §10. Observed wall-clock times exceeding caps (i.e., a subprocess timing out)
are not taint events — they are expected failure modes handled by the state machine.

---

## 9. No-leakage controls

Parent artifacts are not accessible to workers during the scored run:

- Workers receive only: task JSON (`{problem_statement, repo, base_commit}`), vendored skill
  prompts, and the SWE-bench Pro grader Docker image.
- Parent `runs/scored/run.jsonl` (verdicts, patch trajectories) is not staged to worker boxes.
- `WORKLOG.md` entries with resolved-instance IDs are not staged to worker boxes.
- Skill prompts are vendored at SHA `63215e8` and checked into this repo; no live pulls
  from sibling during scored run.

Operator (kimjune01) knows parent verdicts. The no-leakage contract governs the automated
pipeline, not human awareness. This mirrors the parent's disclosure stance (§12).

---

## 10. Taint rules

Any of the following events during the scored run requires a PAUSE, a new git commit with
rationale, and a new tag (`prereg-fc-v2`, etc.) before resuming:

- Any skill prompt edit (even whitespace).
- Any change to `_strip_test_blocks` logic.
- Any change to the grader invocation (flags, timeout, image tag).
- Any change to verdict classification logic in the driver.
- `FLASH_MODEL` or `COMPOSER_MODEL` string changes.
- Any change to `CRAFT_CAP`, `RECON_CAP`, or `AUDIT_CAP` configured values.
- Any change to INCOMPLETE re-run eligibility criteria.
- CLI version string changes (if cursor-agent or gemini-cli auto-updates).

Runner-infra bugs (SSH retry logic, file staging, container cleanup) may be fixed without
a version split **only if** the fix cannot affect: agent inputs (task JSON, skill prompts,
workspace state), verdict classification logic, source-only capture behavior, or grader
invocation. Before applying any `[runner-fix]`, the operator must:
1. Identify all instances run before the fix was applied.
2. Classify whether any could have been affected (conservative: assume yes if unclear).
3. If instances were affected: either re-run all affected instances under the original rules
   (recording both verdicts, using the original as authoritative) or mark this a version
   split.
4. Record pre-fix and post-fix cohorts in `WORKLOG.md` with instance ID ranges.

If the fix affects agent inputs, verdict classification, source capture, or grader behavior:
it is a version split, not a `[runner-fix]`.

---

## 11. Version capture

The following versions are logged to `WORKLOG.md` before phase 2 begins, and included in
`runs/scored/run.jsonl`:

- `gemini --version` output (CLI version string)
- `cursor-agent --version` output (CLI version string + SHA if shown)
- `FLASH_MODEL` string (from env, logged per-run)
- `COMPOSER_MODEL` string (from env, logged per-run)
- `swe_bench_pro_eval.py` git SHA (from sibling)
- Per-file hashes for `skills/{recon,craft,audit}/skill.md` (see §2A)
- `driver/flashcomp_pilot.py` git SHA (from this repo at run start)
- Timestamps of first and last API call per stage (per-instance, to bound version drift)

**Reproducibility caveat.** Hosted model APIs (`gemini-2.5-flash`, `composer-2.5`) may
change behavior behind stable version strings. This cannot be fully controlled. CLI version
strings + call timestamps are logged as the best available approximation. If providers
expose per-call model revision IDs, they are captured. This limitation is disclosed in any
report.

---

## 12. Operational checklist (pre-freeze gate, §13 equivalent)

- [ ] Phase 0 completed: at least one `WIN` or `LOSS` in `runs/dev/flashcomp_run.jsonl`.
- [ ] Phase 0 cost verified: actual per-instance cost matches projection (~$0.16).
- [ ] Phase 0 wall-clock verified: actual per-instance time measured and documented.
- [ ] Craft gate iterations value determined from phase 0 and written to §8 (replaces TBD).
- [ ] EC2 cursor-agent unblocked (Linux x86_64 binary sourced).
- [ ] Phase 1 calibration batch (10-20 instances) validates concurrency ceiling and cost.
- [ ] `tasks/run_order.txt` committed (inherited from sibling or regenerated from pinned dataset).
- [ ] Grader watchdog ported and validated on at least one NodeBB instance.
- [ ] `CURSOR_API_KEY` + `GEMINI_API_KEY` tested on each box; AUTH_ASSERT green (instruction-following confirmed, not just non-error).
- [ ] `docker login jefzda` validated on all boxes (avoid anonymous pull throttle).
- [ ] Both grader defect mitigations (redis-kick, container-reap) wired and logged.
- [ ] Version capture (§11) logged to `WORKLOG.md`.
- [x] Per-file skill prompt hashes (§2A) populated (done 2026-05-29).
- [ ] File hashes for `eligible.txt`, `run_order.txt`, parent verdict file (§2.3) logged.
- [ ] Grader invocation run config committed as machine-readable artifact.
- [ ] `_strip_test_blocks` SHA256 verified against parent.
- [ ] Run-time controls (§8) confirmed and frozen; no TBDs remain.
- [ ] `prereg-fc-v1` tag cut; SHA recorded in `WORKLOG.md` before phase 2 run begins.

---

## 13. Pre-committed interpretations (§11 equivalent)

The three resolve-rate readings in §1.1 are pre-committed. Additionally:

- **If resolve rate > parent's rate:** document as valid. Possible causes: cheaper models have
  lower latency and fit more gate iterations in wall-clock budget; Composer is code-specialized
  and may outperform on certain repo types. Note: no codex adversary means craft iterates
  faster — this is a confound, disclosed here. No result suppression.
- **If INCOMPLETE rate is high (> 10%):** investigate whether it's cursor-agent API rate
  limiting or a craft-skill mismatch. Document in `docs/bench-defects.md`, not in the
  headline.
- **Cost overrun > 2× projection:** halt, investigate, document. Do not reduce eligible
  denominator to stay under budget — only legitimate §6 defects reduce the denominator.
- **Partial run (budget exhausted before 728):** no confirmatory paired comparison is
  reported. Report rate over completed instances labeled `partial-run`, disclose lexicographic
  prefix bias and actual execution order if shards failed. Do not extrapolate to full 728.

---

*Preregistered: 2026-05-29. Run start: [TBD — pending phase 0 completion + phase 1 EC2
unblock]. Freeze tag: `prereg-fc-v1`. Budget cap: $300. Parent: `prereg-pro-v1`.*
