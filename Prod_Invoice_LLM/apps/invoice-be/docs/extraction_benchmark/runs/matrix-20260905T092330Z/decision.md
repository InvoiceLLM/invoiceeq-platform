# Model decision - matrix-20260905T092330Z

Five candidates, same prompts, api-version 2024-10-21, one pass each on the dev account. `Actual Status` and `Actual Alert Type` are **excluded**: every candidate ran after the baseline had already ingested the same 27 PDFs, so the pipeline flagged them as duplicates. Those two columns measure ingestion order, not the model. Extraction score = mean of Tax acc %, Total acc %, line-item F1 %.

Rule (founder, 2026-09-05): per role, the cheapest model within 1 point of the best wins; Sol/Astra only if >2 points over Terra on extraction; judge must also keep the pass-flip rate low.

## Matrix

| task | gpt-5-mini | gpt-5.6-luna | gpt-5.6-terra | gpt-5.6-sol | gpt-6-astra |
|---|---|---|---|---|---|
| (a) extraction score % / $ per 1k calls / p95 s | **98.8** / $2.97 / 65.295 | **99.3** / $0.85 / 35.748 | **97.3** / $7.81 / 54.652 | **98.0** / $19.85 / 31.338 | **95.1** / $24.07 / 59.825 |
| (a) tax / total / line F1 % | 96.3 / 100.0 / 100.0 | 100.0 / 100.0 / 97.8 | 96.3 / 100.0 / 95.6 | 96.3 / 100.0 / 97.8 | 92.6 / 92.6 / 100.0 |
| (a) errors / $ per invoice | 0 / $0.00727 | 0 / $0.00201 | 0 / $0.01881 | 0 / $0.04704 | 2 / $0.05705 |
| (b) doc-type acc % / $ per 1k / p95 s | **95.8** / $0.89 / 5.368 | **100.0** / $0.38 / 2.704 | **100.0** / $3.7 / 2.605 | **100.0** / $9.25 / 2.705 | **100.0** / $16.93 / 4.107 |
| (c) SQL exec-correct % (n) / p95 s | **32.3** (31) / 34.0 | **40.7** (27) / 12.4 | **44.4** (27) / 13.2 | **28.0** (25) / 17.3 | **44.4** (27) / 21.5 |
| (d) chat judge acc / faithfulness / passed % | **0.542** / 0.783 / 22.2 | **0.583** / 0.824 / 27.8 | **0.622** / 0.727 / 25.0 | **0.514** / 0.833 / 22.2 | **0.639** / 0.785 / 25.0 |
| (d) $ per turn / $ per 1k calls / p95 s | $0.0062 / $2.36 / 34.0 | $0.0022 / $0.93 / 11.2 | $0.0198 / $8.21 / 11.3 | $0.0517 / $22.18 / 16.6 | $0.0847 / $35.87 / 20.6 |
| (e) judge mean abs delta / pass flips % / $ per 1k | **0.097** / 5.6 / $1.49 | **0.191** / 22.2 / $0.35 | **0.169** / 27.8 / $2.86 | **0.156** / 22.2 / $9.31 | **0.119** / 19.4 / $9.42 |

List price per 1M tokens in/out (registry): gpt-5-mini $0.25/$2.00, gpt-5.6-luna $0.20/$1.20, gpt-5.6-terra $2.00/$12.00, gpt-5.6-sol $5.00/$30.00, gpt-6-astra $10.00/$12.50

## Per-role recommendation (rule applied mechanically)

| role | winner | values |
|---|---|---|
| primary (extraction) | **gpt-5.6-luna** | gpt-5-mini 98.8, gpt-5.6-luna 99.3, gpt-5.6-terra 97.3, gpt-5.6-sol 98.0, gpt-6-astra 95.1 |
| doc-type classifier | **gpt-5.6-luna** | gpt-5-mini 95.8, gpt-5.6-luna 100.0, gpt-5.6-terra 100.0, gpt-5.6-sol 100.0, gpt-6-astra 100.0 |
| text-to-SQL | **gpt-5.6-terra** | gpt-5-mini 32.3, gpt-5.6-luna 40.7, gpt-5.6-terra 44.4, gpt-5.6-sol 28.0, gpt-6-astra 44.4 |
| fast (chat/narration) | **gpt-6-astra** | gpt-5-mini 0.542, gpt-5.6-luna 0.583, gpt-5.6-terra 0.622, gpt-5.6-sol 0.514, gpt-6-astra 0.639 |
| judge | **gpt-5-mini** (lowest pass-flip rate vs current judge) | gpt-5-mini flips 5.6%, gpt-5.6-luna flips 22.2%, gpt-5.6-terra flips 27.8%, gpt-5.6-sol flips 22.2%, gpt-6-astra flips 19.4% |

## Notes

- Escalation test: Terra extraction 97.3; Sol 98.0, Astra 95.1. Neither beats Terra by >2 points, so **no Sol/Astra escalation tier**.
- Chat pass rate is 22-28% and SQL exec-correct is ~40-50% for every model. Those are prompt/agent problems, not model choice. Re-eval after any swap.
- One pass each. Differences under ~3 points are within run-to-run noise on 27 invoices / 36 turns.
- Original baseline file is `gpt-5-mini__extraction.json`; the end-of-matrix re-run is `gpt-5-mini__extraction_rerun.json` (below).

## Status

Decision recorded for founder review. No code changed, no deployments deleted, no rollout applied.
