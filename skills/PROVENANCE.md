# Skill provenance

These skill files (`recon/skill.md`, `craft/skill.md`, `audit/skill.md`) are vendored from
`swebench-pro/skills/` at:

- **SHA**: `63215e85af5a928149d808976e7cff2d870aedd7`
- **Short**: `63215e8`
- **Date**: 2026-05-24 23:22:59 -0700

Vendored verbatim — no edits between the two runs. This is the experimental invariant of the
controlled comparison (same prompts dispatched to a different model pair).

The eligibility set `runs/audit/eligible.txt` is also vendored from `swebench-pro/runs/audit/eligible.txt`
at the same SHA. 728 instances.

**Update rule:** if the upstream skill files change in `swebench-pro` after this run starts, do NOT
re-vendor mid-run. The whole point of the controlled comparison is that both runs use the same prompts.
Cut a new repo (`swebench-pro-flash-composer-v2`) for a refreshed-skills run.
