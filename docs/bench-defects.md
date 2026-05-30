# SWE-bench Pro runtime defects (Flash+Composer field notes)

Audit-facing: defects observed in the parent `swebench-pro` run that we carry mitigations
for here, plus any Flash+Composer-specific issues. All upstream-Pro defects are inherited
unchanged; see also [`swebench-pro/docs/bench-defects.md`](https://github.com/kimjune01/swebench-pro/blob/main/docs/bench-defects.md)
for fuller investigation narratives.

---

## Inherited defects (from swebench-pro)

### 1. `redis-server --daemonize yes` flake in NodeBB grader

**First observed:** swebench-pro, 2026-05-29.

**Symptom:** docker container alive, CPU ~0.4%, `/workspace/stdout.log` spamming
"Waiting for Redis to start..." forever. Container never exits on its own.

**Root cause:** grader's `prepare_test_environment` does `redis-server --daemonize yes`;
sometimes the fork silently fails. Script loops forever pinging nothing.

**Mitigation (phase 1):** `driver/grader_watchdog.sh` — polls `/workspace/stdout.log` inside
each grader container; if ≥5 of the last 10 lines contain "Waiting for Redis to start",
runs `docker exec -d <cid> redis-server --daemonize yes --protected-mode no --port 6379`
to kick-start it. Script is not yet ported for phase 0 (single-instance local run). Phase 0
mitigation: `GRADER_TIMEOUT` env var (default 7200s) hard-caps the grader subprocess; a
killed grader logs to `runs/dev/grader_kills.jsonl` and returns INCOMPLETE.

**Disclosure stance:** the kick-start helps the bench's intended infra state obtain. We do
not modify the grader, the tests, or the verdict. Score outputs note this mitigation.

---

### 2. Grader leaks containers after exit

**First observed:** swebench-pro, 2026-05-29.

**Symptom:** `docker ps` shows multiple stale grader-shaped containers after pro_run finishes.
Disk grows monotonically; orphan grade dirs mislead any watchdog using "most recent grade
dir" as a progress signal.

**Mitigation (phase 1):** `driver/grader_watchdog.sh` reaps orphans each poll — keeps newest
container per box, `docker kill`s the rest. Logs `REAP_ORPHAN` to `grader_kills.jsonl`.
Phase 0 mitigation: single-instance runs are short enough that leaks don't accumulate; a
manual `docker ps` check after each run is sufficient.

---

### 3. "not resolved" LOSS indistinguishable from grader-kill artifact

**First observed:** swebench-pro, 2026-05-29.

**Symptom:** when a watchdog kills a wedged container, pro_run records the failed eval as
`"not resolved"` — the same detail field a genuinely-failed test produces. Ledger can't
distinguish them without external audit trail.

**Mitigation:** `runs/dev/grader_kills.jsonl` — one JSON line per kill event, written by
`flashcomp_pilot.py`'s `_log_grader_kill()`. A `driver/retry_grader_kills.sh` (phase 1) will
cross-reference kills with the scored ledger and strip matching LOSSes for re-run.

**Policy:** if the re-run also fails, it's a real LOSS. If even the gold reference patch
fails (KNOWN_BAD), exclude from denominator under parent §6 rules.

---

## Flash+Composer-specific notes

### 4. cursor-agent workspace isolation

**Observed:** phase 0 validation.

cursor-agent requires `--workspace <path>` to be a directory it trusts. Without `--trust`,
it may silently use its remembered trust dir and edit the wrong tree (DeepSWE lesson #1).
Mitigation: `flashcomp_pilot.py` creates a fresh `runs/dev/fc_ws_{tag}/` directory per
invocation and passes both `--workspace` and `--trust`.

### 5. CURSOR_API_KEY doesn't survive bash spawn

**Observed:** phase 0 validation (expected based on DeepSWE lesson #2).

`CURSOR_API_KEY` must be passed via `subprocess.env=` on each invocation. It does not
survive `source ~/.zshrc` in a bash subshell. `flashcomp_pilot.py` handles this via
`env = {**os.environ, "CURSOR_API_KEY": CURSOR_API_KEY}` on every `cursor-agent` call.

---

## Integrity direction

All defects above bias the SAME direction: **inflated LOSS count, deflated WIN count.**
- A WIN is solid: the grader returned "resolved." Grader bugs don't forge a pass.
- A LOSS may be real OR a bench-side artifact our runner couldn't disambiguate.

Any number from a non-trivial run is **conservative** (lower bound on true capability)
unless the reporter has receipts. Ours:
- Per-instance patches: `runs/dev/fc_patch_<iid>.diff`
- Grader kill audit: `runs/dev/grader_kills.jsonl`
- Stage logs: `runs/dev/flashcomp_run.jsonl`

---

## See also

- `PREREGISTRATION.md §4` — operator-level mitigations (disclosure per §14 discipline)
- `docs/retros/` — operator retrospectives (none yet for flash-composer; see sibling)
- `swebench-pro/docs/bench-defects.md` — parent investigation narratives
