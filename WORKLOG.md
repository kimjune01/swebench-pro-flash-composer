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
