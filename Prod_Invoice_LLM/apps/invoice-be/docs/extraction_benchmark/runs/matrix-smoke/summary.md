# Model matrix — matrix-smoke

Generated 2026-09-05T09:20:40.839101+00:00. Baseline `gpt-5.6-luna`. api-version `2024-10-21`. Cells: primary metric | USD per 1k LLM calls (registry list price) | p95 latency. Same prompts, one run each.

| task | gpt-5.6-luna |
|---|---|
| (a) extraction — field accuracy % | — |
| (b) doctype — accuracy % | 100.0 | $0.387/1k | p95 3.075s |
| (c) sql — exec-correct % | 100.0 | $0.751/1k | p95 8.831s |
| (d) chat — judge accuracy 0-1 | 1.0 | $0.751/1k | p95 8.831s |
| (e) judge — mean |Δ acc| vs current judge | 0.0 | $0.293/1k | p95 —s |

## Extraction detail

| model | invoice acc % | field acc % | line P % | line R % | line F1 % | errors | $/invoice | p95 s |
|---|---|---|---|---|---|---|---|---|

### Per-field accuracy % (fields < 80 on every model are OCR/prompt problems, not model problems)


## Chat / SQL detail

| model | SQL turns | exec-correct % | mean attempts | judge acc | faithfulness | relevance | passed % | $/turn | p95 s |
|---|---|---|---|---|---|---|---|---|---|
| gpt-5.6-luna | 1 | 100.0 | 1 | 1.0 | 0.5 | 1.0 | 0.0 | 0.00225 | 8.831 |

## Judge stability (re-grading the baseline's answers)

| judge | mean |Δ acc| | rescored acc mean | original acc mean | pass flips % | $/1k calls |
|---|---|---|---|---|---|
| gpt-5.6-luna | 0.0 | 1.0 | 1.0 | 0.0 | 0.293 |

## Runs

| model | task | rc | wall s | log |
|---|---|---|---|---|
| gpt-5.6-luna | extraction | 1 | 2.8 | gpt-5.6-luna__extraction.log |
| gpt-5.6-luna | doctype | 0 | 71.0 | gpt-5.6-luna__doctype.log |
| gpt-5.6-luna | chat+sql | 0 | 54.7 | gpt-5.6-luna__chat.log |
| gpt-5.6-luna | judge | 0 | 23.3 | gpt-5.6-luna__judge.log |

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
