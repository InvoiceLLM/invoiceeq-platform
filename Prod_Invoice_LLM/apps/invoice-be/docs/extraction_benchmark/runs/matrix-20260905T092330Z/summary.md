# Model matrix — matrix-20260905T092330Z

Generated 2026-09-05T13:09:44.968217+00:00. Baseline `gpt-5-mini`. api-version `2024-10-21`. Cells: primary metric | USD per 1k LLM calls (registry list price) | p95 latency. Same prompts, one run each.

| task | gpt-5.6-terra |
|---|---|
| (a) extraction — field accuracy % | 59.3 | $7.812/1k | p95 54.652s |
| (b) doctype — accuracy % | 100.0 | $3.701/1k | p95 2.605s |
| (c) sql — exec-correct % | 44.4 | $9.312/1k | p95 13.208s |
| (d) chat — judge accuracy 0-1 | 0.622 | $8.207/1k | p95 11.255s |
| (e) judge — mean |Δ acc| vs current judge | — |

## Extraction detail

| model | invoice acc % | field acc % | line P % | line R % | line F1 % | errors | $/invoice | p95 s |
|---|---|---|---|---|---|---|---|---|
| gpt-5.6-terra | 0.0 | 59.3 | 95.6 | 95.6 | 95.6 | 0 | 0.01881 | 54.652 |

### Per-field accuracy % (fields < 80 on every model are OCR/prompt problems, not model problems)

| field | gpt-5.6-terra |
|---|---|
| Actual Alert Type ⚠ all <80 | 7.4 |
| Actual Status ⚠ all <80 | 33.3 |
| Actual Tax | 96.3 |
| Actual Total | 100.0 |

## Chat / SQL detail

| model | SQL turns | exec-correct % | mean attempts | judge acc | faithfulness | relevance | passed % | $/turn | p95 s |
|---|---|---|---|---|---|---|---|---|---|
| gpt-5.6-terra | 27 | 44.4 | 1 | 0.622 | 0.727 | 0.975 | 25.0 | 0.01983 | 11.255 |

## Judge stability (re-grading the baseline's answers)

| judge | mean |Δ acc| | rescored acc mean | original acc mean | pass flips % | $/1k calls |
|---|---|---|---|---|---|

## Runs

| model | task | rc | wall s | log |
|---|---|---|---|---|
| gpt-5.6-terra | extraction | 0 | 792.9 | gpt-5.6-terra__extraction.log |
| gpt-5.6-terra | doctype | 0 | 67.8 | gpt-5.6-terra__doctype.log |
| gpt-5.6-terra | chat+sql | -9 | 8122.8 | gpt-5.6-terra__chat.log |

## Registry in force

```json
{
  "primary": {
    "role": "primary",
    "provider": "azure",
    "deployment": "gpt-5-mini",
    "api_version": "2024-10-21",
    "context_limit": 400000,
    "encoding": "o200k_base",
    "reasoning_capable": true,
    "price_in": 0.25,
    "price_out": 2.0
  },
  "fast": {
    "role": "fast",
    "provider": "azure",
    "deployment": "gpt-5-mini",
    "api_version": "2024-10-21",
    "context_limit": 400000,
    "encoding": "o200k_base",
    "reasoning_capable": true,
    "price_in": 0.25,
    "price_out": 2.0
  },
  "judge": {
    "role": "judge",
    "provider": "azure",
    "deployment": "gpt-5-mini",
    "api_version": "2024-10-21",
    "context_limit": 400000,
    "encoding": "o200k_base",
    "reasoning_capable": true,
    "price_in": 0.25,
    "price_out": 2.0
  },
  "doc_intel_model_id": "prebuilt-invoice",
  "embedding_model": "BAAI/bge-m3"
}
```
