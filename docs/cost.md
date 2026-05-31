# Cost — and why Composer 2.5

The model choice is a cost argument as much as a capability one. Flash+Composer was
picked because it turns a full SWE-bench Pro reproduction from a **variable per-token
bill into a fixed subscription cost**.

## Measured (2026-05-31 export, ~2,094 Composer calls ≈ half a run)

| Kind | calls | cash |
|------|------:|-----:|
| Included (Cursor plan) | 1,821 | $0 |
| On-Demand (overage)    |    84 | **$26.61** |
| Errored, No Charge     |   188 | $0 |
| Free                   |     1 | $0 |

**Out of pocket: ~$27.** 87% of calls were absorbed by the $200/mo plan.

### Token volume (1.57 B total)

| | tokens | standard rate | economic cost |
|--|------:|--------------:|-----:|
| Fresh input | 92 M | $0.50/M | $46 |
| Output | 17 M | $2.50/M | $43 |
| Cache read | 1,463 M | ~$0.05/M | $73 |
| **Total** | **1.57 B** | | **~$160** |

93% of tokens are cache reads — Composer re-reading repo context across tool turns.
Priced at the published `composer-2.5` **standard** rate ($0.50 / $2.50 per M in/out);
we run standard, not Fast (`cursor-agent --model composer-2.5`, no `--fast`), because
Fast's only benefit is interactive throughput and this is a headless batch.

## Why Composer 2.5

- **~100× cheaper per task than frontier.** Composer 2.5 standard measures ~$0.07/task
  vs Opus 4.7 max ~$4.10/task ([Artificial Analysis Coding Agent Index][aa]). A 728-instance
  repro at frontier per-token rates ≈ **$3,000/run**; on Composer-via-plan it's the plan.
- **Fixed, predictable cost.** A skeptic reproduces the run for the price of a single
  $200 plan — not a metered token bill that scales with instance count. The barrier is
  one flat subscription, whether or not they already use Cursor; that predictability is
  the point for a bench whose value is its legibility.
- **Marginal cost → ~$0** until the monthly quota caps. The *next* repro is nearly free.

### What's actually being exploited: open-weight piggybacking

The cost win isn't Cursor's engineering — it's **open-weight economics, resold at a flat
rate**. Composer 2.5 is reported to be Kimi K2.5 underneath, and OpenRouter's May 2026
traffic shows that whole class (Kimi / Qwen3 Coder / MiMo-V2-Pro / DeepSeek V4) now leads
the coding category on cost-per-task — Chinese open-weight models crossed ~52% of total
token flow. Cursor's contribution is *convenient flat-rate delivery* of weights it doesn't
own.

So the dependency is on the **model class, not the vendor**. The pilot's solver is swappable
(`cursor-agent --model composer-2.5` is one line); if Cursor's pricing or plan changed, the
same run is reproducible by pointing at the open weights directly (OpenRouter, self-host, or
another wrapper). We're piggybacking on the open-weight cost curve and using Cursor as the
cheapest current on-ramp — not betting on Cursor. That's what keeps the reproducibility
argument vendor-independent.

## The full cash picture

| Component | cash | billing |
|-----------|-----:|---------|
| Gemini Flash planner (recon + volley + audit) | **$23.18** | pay-per-token (whole month, May 3–30) |
| Cursor Composer — on-demand overage | **$26.61** | past the plan quota |
| Cursor Composer — plan-included | $0 marginal | $200/mo plan absorbed 1,821/2,094 calls |
| EC2 (19× `m7i.xlarge` @ $0.2016/hr) | ~$14 | per-run |
| **Total out of pocket** | **~$50–65** | on top of the $200 plan |

So the two metered APIs are **comparable in cash** (~$23 Flash, ~$27 Cursor overage); the
big Composer volume (~$135 of economic value) is what the flat plan absorbs. Flash is only
a "rounding error" against Composer's *economic* cost (~$160) — in *cash* it's neck-and-neck
with the Cursor overage. The boxes are the genuine rounding error.

## Caveat / TODO

These figures are export-and-multiply: the pilot logs no `usage`. Post-run, capture
`usage` from the Gemini and Cursor responses into the ledger so cost becomes a column,
not an estimate. The cache-read rate (~$0.05/M assumed, 93% of volume) is the only soft
number; everything else is pinned to published rates.

[aa]: https://artificialanalysis.ai/articles/cursor-composer-2-5-coding-agent-index
