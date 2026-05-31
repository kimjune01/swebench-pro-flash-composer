# Worklog — swebench-pro-flash-composer

## 2026-05-30 — prereg-flash-v1 freeze

Freeze tag `prereg-flash-v1` cut at this commit (see §8 of PREREGISTRATION.md).

**Freeze SHA:** (this commit — see `git rev-parse prereg-flash-v1`)

**What's frozen:**
- `driver/flashcomp_pilot.py` — per-instance pilot (Composer recon+craft, Flash volley+audit)
- `driver/flashcomp_run.py` — 4-shard batch driver
- `skills/{recon,craft,audit}/skill.md` — vendored from swebench-pro at freeze SHA
- `runs/audit/eligible.txt` — 728 eligible instances (inherited from parent prereg-pro-v1 audit)
- `runs/audit/run_order.txt` — lexicographic sort of eligible.txt

**Phase 0 results (exploratory, not headline):**
- `instance_navidrome__navidrome-bf2bcb12…` — WIN (187s, official_resolved=True, agent_verdict=RESOLVED)
- `instance_element-hq__element-web-1216285e…` — WIN (245s, official_resolved=True, agent_verdict=RESOLVED)
- `instance_ansible__ansible-0ea40e09…` — WIN (256s, multi-shard validation, shard 1/2)
- `instance_ansible__ansible-0fd88717…` — WIN (289s, multi-shard validation, shard 2/2)

**Next:** measurement run — 4 shards × 182 instances on Mac arm64.

## 2026-05-31 — EC2 measurement run: outage recovery + grading moved on-box

Long recovery session on the §4.5a EC2 coordinator run. Root-caused a cascade of
failures, recovered the ledger without re-running agents, and hardened the harness.

**Incident chain (all distinct, surfaced in sequence):**
1. **Mac disk full → OrbStack down.** `official_grade()` ran *locally* on the Mac
   (`--use_local_docker`), so with Docker down every grade returned `None`. The
   coordinator recorded `None` as LOSS → **131 agent-solved instances mis-scored as
   losses** and frozen in the ledger (resolve rate cratered 87.8% → 33.9%, an artifact).
2. **Re-cloned grader repo missing `docker` SDK** (Xcode python) — silent second cause.
3. **OrbStack flapped again** mid-recovery — confirmed Mac Docker is too fragile to grade on.
4. **Mac public IP changed** — SG ingress is locked to provision-time IP; chased as a lead,
   was secondary.
5. **Root of the fleet death: 3h self-terminate watchdog.** `provision_box.sh` set
   `shutdown -h +180` + terminate-on-shutdown. Run outlived its own kill timer (extended by
   hours of debugging) → 17/19 boxes self-terminated mid-run. Coordinator then churned
   INCOMPLETEs (SSH-dead boxes requeue, don't reprovision), so it was stopped.

**Recovery (no agent re-runs):**
- Freed disk; OrbStack restart reclaimed ballooned virtual disk (15G → 110G).
- All 131 patches were persisted (`runs/dev/fc_pred_*`), so re-graded from disk:
  **119 were real WINs, 12 real LOSSes.** First on Mac (flapped), then pivoted to the boxes.

**Hardening (committed to harness):**
- `official_grade()` now grades **on the EC2 box** (its own docker + cached images) when
  `REMOTE_BOX` is set; Mac-local path kept as fallback. A Mac Docker outage can no longer
  turn wins into losses. Validated end-to-end + live (first on-box WIN: flipt-9d25c18b, 604s).
- `provision_box.sh`: installs the grader (repo + `docker/pandas/tqdm`) so reprovisioned
  boxes are grade-ready; watchdog `180 → 720` min (`WATCHDOG_MIN`), verified live on-box.
- `driver/regrade_on_boxes.py` — distributes captured patches across the fleet to re-grade.
- Coordinator gains a **one-shot rerun-list** (`runs/scored/needs_rerun_no_patch.txt`):
  forces patchless/crashed/None records back into `todo` only while still "unfair", then
  prunes on record (a genuinely-unpatchable instance can't be re-forced forever).

**Loss taxonomy (the 11+ patchless "losses"):** not real losses — `no_patch_produced` /
`harness_exception` / `None` from the broken window, queued for one fair re-attempt. On the
healthy fresh fleet most re-ran to genuine `no_patch_produced` (agent truly emits no patch).

**State at log time:** fresh 19-box fleet (provisioned ~18:41, 12h watchdog), on-box grading,
0 box faults. Ledger: **203 WIN / 61 LOSS / 264 graded, 464 todo.** OPEN WATCH — fresh-run
win rate currently depressed; front of `run_order` is lexicographically loaded with harder
ansible/element-web/flipt instances (incl. malformed `*-vnan`). Monitoring whether it
recovers toward the ~87% banked rate as the queue clears the hard front. Grading is clean
(0 `None` regressions on the fresh fleet).

## 2026-05-31 (cont.) — run complete; disk root-cause; capture + reclaim fixes

The OPEN WATCH above resolved: win rate recovered as the hard lexicographic front
cleared. A second local-disk-full crash (`OSError: No space left`, 19:14) killed the
coordinator mid-run; freed disk (OrbStack 102G→16G after pruning 81 `jefzda` images)
and resumed `--boxes 19 --skip-setup`.

**Final ledger:** **559 WIN / 46 LOSS / 117 INCOMPLETE / 6 untouched** (728 eligible) —
**92.4%** over 605 graded. INCOMPLETE is non-terminal, so it does not deflate the rate.

**Root cause of both disk events (one bug):** no `docker rmi`/prune anywhere. `pro_setup`
pulls a unique multi-GB image per instance; nothing reclaims it. Local runs filled OrbStack
(→ the 19:14 crash); the resumed `REMOTE_BOX` run filled box disks on the large-repo tail
(protonmail/qutebrowser/tutanota) → `docker pull` fails in ~3s → the 117 `setup failed`
INCOMPLETEs. Registry manifests for those images were verified PRESENT — it was disk, not
missing tags (an earlier "missing image" guess, refuted).

**Fixes shipped this session:**
- `pilot: reclaim image on teardown` (`docker rm -f` + `rmi -f`, routed via `run()` so it
  guards both local and box) — the actual fix for both disk events.
- `capture: stage untracked files before diff` — `git add -A; git diff --cached HEAD`
  (mirrors parent `pro_pilot.py`); bare `git diff HEAD` was dropping new-file fixes to
  `no_patch`. Reclassified empty-patch LOSS→INCOMPLETE. Test: `driver/test_capture_untracked.py`.
- `docs/cost.md` — full-run cost (~$50–65 cash; ~$160 economic; open-weight piggybacking).

**Cost:** Gemini $23.18 (month) + Cursor on-demand $26.61 + EC2 ~$14 ≈ $50–65 cash on top of
the $200 Cursor plan. All EC2 boxes terminated (incl. 5 post-run idle/orphan).

**Still open (need a fresh fleet — not yet run):**
- Skeptical re-grade of the 559 WINs from persisted `fc_pred`/`fc_sample` (same grader →
  catches only flaky/nondeterministic false-WINs; deterministic coverage gaps need UTBoost).
- Re-run the 117 INCOMPLETE + 6 untouched now that image reclamation prevents the disk death.

## 2026-05-31 (cont. 2) - validation: WIN re-grade + INCOMPLETE re-run

Two post-run validation passes after the fixes landed.

**#3, skeptical WIN re-grade (sample).** Re-graded a 60-WIN stratified sample (across all
11 repos) from persisted `fc_pred`/`fc_sample` on a fresh 5-box `wincheck` fleet, recording
to a separate ledger (`runs/scored/regrade_win.jsonl`); original `run.jsonl` untouched.
Result: **60/60 reproduced WIN, 0 flips.** The 92% is not a grader-flake, serialization, or
operator-mitigation artifact: every sampled WIN reproduces on a clean independent grader.
Boundary: this validates *reproducibility*, NOT *test-coverage* (a weak F2P set still passes
a wrong patch deterministically; that needs the UTBoost stronger tests, a separate axis).
Did not escalate to all 559: same-grader re-grade is deterministic, so 0/60 implies ~0 on
the rest. Script: `driver/regrade_wins.py`.

**#4, re-run the 114 unfinished (in progress at log time).** Coordinator re-run (15 fresh
boxes) of the INCOMPLETE + untouched, using the image-reclaim-fixed pilot. Validates the
fix end-to-end: **setup_failed=0** (boxes no longer fill), and the disk-killed instances are
converting INCOMPLETE to graded. At log time: 624 graded (578W/46L, 92.6%), 98 INCOMPLETE
remaining, conversions running WIN-heavy (expected: these were setup failures on large
repos, not capability losses). Fleet teardown + final tally to follow on DONE.

**Cost note:** wincheck fleet (5 boxes) terminated post-#3; #4's 15 boxes still up.

## 2026-05-31 (cont. 3) - scoring convention: incompetence stays in the denominator

Correction to the framing in the entries above (which led with "X over N graded").
That graded-only rate SHRINKS the denominator by parking our own failures as INCOMPLETE,
which is denominator-shopping. The honest headline counts every eligible instance:

  **HEADLINE = WIN / 728** (same denominator as the parent swebench-pro run).

Everything that is not a WIN counts as non-resolved: LOSS, INCOMPLETE (including setup
failures from our local/box disk mismanagement AND genuine no-patch capability misses),
and untouched. Our incompetence (the two disk crashes, the missing image-prune, the
capture bug, the agent emitting no patch) does NOT get excluded from the score.

At this log time (#4 re-run still converting parked INCOMPLETEs):
- **Headline: 615 / 728 = 84.5%** (rising; final number on #4 DONE).
- Graded-only 615/661 = 93.0% is a DIAGNOSTIC ONLY, not the headline.
- Parent codex: 694 / 728 = 95.3%. Real gap ~11 pts (codex is the stronger solver and never
  bled instances to disk/no-patch).

Skeptical WIN re-grade (#3) stands: 60/60 sampled WINs reproduce on a clean grader (0 flips),
so the WINs in the numerator are real grader passes (reproducibility, not coverage).

## 2026-05-31 (cont. 4) - prereg correction to the denominator framing

cont. 3 overcorrected. Per PREREGISTRATION.md §5/§6 the split is:

- **Denominator = 728, never shrinks.** INCOMPLETEs are PENDING toward 728, not excluded
  and NOT counted as solver losses (§6).
- **INCOMPLETE = enumerated EXTERNAL fault only** (`BOX_DEATH/DISK_FULL/OOM/SETUP_NETWORK_FAIL/
  PROVIDER_CRED_REJECT`), coordinator-detected -> retry under byte-identical artifact (§5).
  Our two disk crashes are DISK_FULL infra: retried, NOT charged to the agent.
- **0-byte capture / agent-emitted-no-patch = LOSS, stands** (§5 table). Solver incompetence
  counts; infra incompetence retries. Headline = resolved / 728.

**Compliance gap found:** the `no_patch_produced -> INCOMPLETE` reclassification committed
earlier (701006b) DEVIATES from the frozen table (§5: 0-byte capture = LOSS; §5: "No
INCOMPLETE reclassification"). Correct behavior is a split:
  - setup-fault / DISK_FULL / crash-before-capture -> INCOMPLETE (infra, retry)
  - agent ran the loop and emitted nothing (0-byte capture) -> LOSS (stands)
The 2 remaining ansible no-patches (5 iters, NOT_RESOLVED) are 0-byte-capture LOSSes, not
INCOMPLETE. Fix the classify block post-#4 (not mid-run); score those 2 as LOSS in the final.

**Honest in-progress headline:** resolved / 728 = 621 / 728 = 85.3% (LOWER bound; the
DISK_FULL-infra INCOMPLETEs are still being retried up by #4). Final on #4 DONE.
Parent codex: 694/728 = 95.3%.

## 2026-05-31 (cont. 5) - FINAL locked

#4 re-run DONE. Merging all scored-run shards (run*.jsonl, the load_done view):

  **HEADLINE: resolved / 728 = 678 / 728 = 93.1%** (prereg-honest).

- WIN (resolved): 678
- LOSS: 49 (47 graded + 2 ansible no-patch scored as 0-byte-capture LOSS per PREREG sec.5)
- Pending (infra, re-runnable per sec.6): 1 (ansible-c1f2, `setup failed` DISK_FULL, exhausted
  --max-attempts; not charged as a loss)
- untouched: 0

Validation that backs the number:
- Skeptical WIN re-grade (#3): 60/60 sampled WINs reproduced on a clean independent grader,
  0 flips. WINs are real, reproducible grader passes.
- Reclaim fix held: setup_failed=0 across the entire #4 re-run (boxes never re-filled).
- #4 recovered ~119 instances (559 -> 678 WIN) that the disk bug had killed as INCOMPLETE,
  confirming they were genuinely solvable work lost to our infra, not capability failures.
- Full 728 denominator, nothing excluded; infra retried per prereg, 0-byte capture = LOSS.

Comparison: parent codex 694/728 = 95.3%. Flash+composer 678/728 = 93.1%, ~2.2 pts back.

Boundary (unchanged): this is reproducibility-validated, NOT coverage-validated. A weak F2P
set still passes a wrong patch deterministically; the coverage axis needs UTBoost stronger
tests, a separate run not done here.

Tooling notes for next time:
- `score-pro` reads only `run.jsonl`, not the `run.S*of*.jsonl` shards, so it UNDERCOUNTS a
  sharded run (showed 672, true merged = 678). Use the merged/load_done view for the headline.
- Pending code fix (post-run, prereg compliance): split the empty-patch classify - infra
  fault -> INCOMPLETE, agent-emitted-nothing (0-byte capture) -> LOSS. The blanket
  no_patch->INCOMPLETE committed in 701006b deviates from sec.5 and must be reverted/split.
