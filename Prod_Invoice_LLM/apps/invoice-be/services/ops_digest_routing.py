"""
Feature 24 (Ops Digest Agent) — two-tier critical/digest classification.

This is the routing *decision* only — not the scheduler, not the delivery
mechanism, not the LLM-summarization step. Those are separate, larger tasks
(see feature_24_ops_digest_agent.md's "Open / not yet decided"). This module
answers one question: given one signal (an Azure Monitor alert firing, or an
AI-eval finding — the two source shapes this app actually produces), should
it page immediately or wait for the next periodic digest?

Two distinct signal sources, because they arrive through different
mechanisms:

1. **Azure Monitor alerts** (the 25 rules in `infra/modules/monitoring/
   alert-rules.bicep`) already have a critical/info split baked into which
   action group they're wired to at alert-*definition* time (Gap 291's
   finding: both groups currently notify the same place, but the
   *classification* itself — which alerts are tagged critical vs. info — is
   real and correct). So for an Azure alert, this module doesn't re-derive
   severity from scratch; it trusts the alert's own `action_group` field.

2. **AI-eval findings** (Feature 23's benchmark/telemetry results) have no
   Azure Monitor alert wired up at all today — there's no existing
   critical/info assignment to defer to, so this module applies the named
   exceptions directly.

Named "always critical" exceptions (agreed 2026-08-23, feature_24_ops_
digest_agent.md): data-loss-risk (already the critical action group, case 1
above), full outage, the audit/benchmark job itself failing to run, a sharp
AI quality-score drop. **Honest limitation**: "full outage" (all replicas of
an app down, not one restarting) has no real data source yet — no existing
check distinguishes "1 of 5 replicas restarting" from "0 of 5 running." The
`replica_count`/`expected_min_replicas` signal fields exist here so the
caller *can* supply that distinction once something upstream computes it,
but nothing in this codebase computes it today — treat that specific
exception as scaffolding, not a working detector, until Wave 2's dashboard
work gives it a real source.
"""
from typing import Literal, TypedDict

Tier = Literal["critical", "digest"]


class Signal(TypedDict, total=False):
    source: Literal["azure_alert", "ai_eval"]
    # azure_alert fields
    action_group: Literal["critical", "info"]
    # ai_eval fields
    finding_type: str  # e.g. "audit_job_failed", "quality_score_drop", "quality_score_drift"
    is_sharp_drop: bool  # True = cliff, not gradual drift (feature_24 doc: drift belongs in digest)
    # shared, optional, for the not-yet-wired full-outage exception
    replica_count: int | None
    expected_min_replicas: int | None


def classify(signal: Signal) -> Tier:
    source = signal.get("source")

    if source == "azure_alert":
        # Trusts the alert's own action-group assignment (see module
        # docstring, case 1) -- this module doesn't second-guess
        # alert-rules.bicep's existing, correct severity classification.
        return "critical" if signal.get("action_group") == "critical" else "digest"

    if source == "ai_eval":
        finding_type = signal.get("finding_type")
        if finding_type == "audit_job_failed":
            # A silent scheduler failure is worse than any single bad
            # metric -- nobody would know to look otherwise.
            return "critical"
        if finding_type in ("quality_score_drop", "quality_score_drift"):
            return "critical" if signal.get("is_sharp_drop") else "digest"
        # Any other AI-eval finding type (not yet named as an exception)
        # defaults to digest -- deliberately no "never critical" list either
        # (feature_24 doc: premature before real noise has been observed),
        # so an unrecognized finding_type falls to the safer, quieter tier
        # rather than either silently dropping it or over-paging on an
        # unclassified signal type.
        return "digest"

    # Full-outage check: zero running replicas, not merely below the
    # configured minimum -- one replica restarting while others cover
    # traffic is normal/self-healing and belongs in the digest, not here.
    # Only fires if a caller actually supplied both replica fields (see
    # module docstring's honest limitation above).
    replica_count = signal.get("replica_count")
    expected_min = signal.get("expected_min_replicas")
    if replica_count is not None and expected_min is not None and expected_min > 0 and replica_count == 0:
        return "critical"

    # Unknown/malformed signal: safer to surface it than silently drop it,
    # but don't page on something we couldn't even identify the source of.
    return "digest"
