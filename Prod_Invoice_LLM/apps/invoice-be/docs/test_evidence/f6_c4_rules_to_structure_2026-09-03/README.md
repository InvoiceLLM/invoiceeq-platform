# Feature 6.1 item C4 — rules → structure

**Date:** 2026-09-03 · **Personas:** senior-dev (build), functional-tester (harness + runs)

| run | result |
|---|---|
| `tests/test_c4_schema_linking.py` | 13 passed |
| `tests/test_c4_examples_retrieval.py` | 9 passed |
| `tests/test_gap426_qualified_column_normalisation.py` | 11 passed |
| curated reference SQL vs the seeded golden fixture (`verify_golden_sql.py`) | **29 / 29 verified** (24/29 before the Gap 426 fix) |
| wide regression, 23 suites, real Postgres `localhost:5433` | **654 passed in 158.14s (0:02:38)** |

## Prompt size (o200k_base)

| | before C4 | after C4.2 |
|---|---|---|
| total prompt, one tenant/question | 6,797 | 5,598 |
| cacheable prefix (A4) | 5,002 | 4,609 |
| `query_agent.py` | — | −9,083 chars of rule prose |

## The golden control — owed, not done

The A4 after-run (also C4's baseline) was in flight when C4 landed. The C4
after-run and the case-by-case comparison are:

```
uv run python scripts/run_agent_eval.py --paths default --provider azure --model gpt-5-mini --out docs/test_evidence/f6_c4_rules_to_structure_2026-09-03/after.json
python scratchpad/golden_diff.py docs/test_evidence/f6_a4_prompt_prefix_2026-09-03/after.json docs/test_evidence/f6_c4_rules_to_structure_2026-09-03/after.json
```

C4 is not "proven" until pass_rate / faithfulness / accuracy are within noise of
the baseline and the attribute/metric cases (discount, subtotal, tax component,
outstanding) pass. Gap 226 is the precedent: a prompt change once passed the
mocked suite and regressed live.
