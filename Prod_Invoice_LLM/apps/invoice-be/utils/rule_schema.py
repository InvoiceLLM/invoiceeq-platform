"""Feature 18: the structured rule object stored in `ExtractionTemplate.rules["constraints"]`,
and the single shared normalizer every read site uses.

The problem this solves
-----------------------
`constraints` has always been a flat `list[str]` of free text produced by an LLM
interpreting a chat message. Nothing downstream could tell *what* a rule was
about, which alert (if any) motivated it, or whether it was a prompt instruction
versus a verification-threshold change — because all of that was dissolved into a
sentence. Two independent producers (`routers/trainer.py` via the trainer agent,
and `routers/audit.py::_apply_standing_rule` synthesising
`f"For {field}, extract the value as ..."`) both emitted into the same
undifferentiated bag.

A rule is now a tagged object:

    {
      "field":             "tax_amount",          # or "items", "*"
      "condition":         "abs_tol=5.0",         # short machine-ish condition
      "scope":             "vendor" | "global" | "outbound_global",
      "source_alert_type": "tax_mismatch" | None, # the alert this came from
      "origin":            "trainer_alert_correction" | ...,
      "text":              "…rendered prompt/display sentence…",
      "kind":              "extraction" | "tolerance_override" | ...,
      "params":            {"abs_tol": 5.0, "rel_tol": 0.005},
    }

Structured objects live **alongside** legacy strings in the same JSON list — the
column is already JSON (`models.py:258`), so no migration was needed for this and
none was written. Every tenant's existing free-text rules keep working untouched:
`normalize_constraints()` renders a legacy string and a structured object into
identical prompt text, and that one function is what every read site now calls.

Why `for_prompt` defaults to True
---------------------------------
Not every rule belongs in an extraction prompt. A tolerance override
("treat a <=5.00 line-item gap as fine") is consumed by `verify_node`, not by the
LLM — and feeding numeric slack into the extraction prompt would actively fight
`GAP_46_VERBATIM_DIRECTIVE`, which exists precisely to stop the model smoothing
numbers to make arithmetic work. So prompt-facing reads get only the
prompt-relevant kinds; display/history reads pass `for_prompt=False` to see
everything.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Iterable

logger = logging.getLogger(__name__)


# ── Rule kinds ────────────────────────────────────────────────────────────────
#: A free-text instruction for the extraction LLM. Legacy strings normalise to this.
KIND_EXTRACTION = "extraction"
#: Widens abs_tol/rel_tol for one of the three tolerance-taking checks.
KIND_TOLERANCE = "tolerance_override"
#: Lowers the OCR-confidence threshold that produces `low_confidence_field`.
KIND_CONFIDENCE = "confidence_threshold_override"
#: Relabels an alert's severity and/or message without changing whether it fires.
KIND_ALERT_OVERRIDE = "alert_override"

#: Kinds that are rendered into an LLM prompt. Everything else is machinery that
#: `verify_node` reads directly (see the module docstring).
PROMPT_KINDS = frozenset({KIND_EXTRACTION})

ALL_KINDS = frozenset({KIND_EXTRACTION, KIND_TOLERANCE, KIND_CONFIDENCE, KIND_ALERT_OVERRIDE})


# ── Rule origins (who produced it) ────────────────────────────────────────────
#: A plain string that predates the structured schema.
ORIGIN_LEGACY = "legacy_text"
#: Trainer, anchored on a real alert the user marked unnecessary/mis-severity.
ORIGIN_TRAINER_ALERT = "trainer_alert_correction"
#: Trainer, "I expected an alert here and got none" — the only LLM-interpreted path.
ORIGIN_TRAINER_MISSED = "trainer_missed_alert"
#: Trainer free-text chat refinement (the pre-Feature-18 conversational path).
ORIGIN_TRAINER_CHAT = "trainer_chat"
#: routers/audit.py::_apply_standing_rule (inbound auditor correction).
ORIGIN_AUDIT_CORRECTION = "audit_correction"
#: routers/outbound_audit.py::_apply_standing_rule_direct (outbound auditor correction).
ORIGIN_AUDIT_CORRECTION_OUTBOUND = "audit_correction_outbound"


# ── Scopes ────────────────────────────────────────────────────────────────────
SCOPE_VENDOR = "vendor"
SCOPE_GLOBAL = "global"
#: Outbound invoices have no `vendor_name` (the counterparty is `customer_name`,
#: a different party entirely), so outbound rules structurally live on the Global
#: OUTBOUND template row. This is not "Global-scope rule creation" coming back in
#: through a side door — it is the only row an outbound rule *can* live on.
SCOPE_OUTBOUND_GLOBAL = "outbound_global"

#: Keys a structured rule may carry. Anything else is dropped on build so a
#: caller can't smuggle arbitrary JSON into a template row.
RULE_KEYS = ("field", "condition", "scope", "source_alert_type", "origin", "text", "kind", "params")

_WILDCARD_FIELDS = (None, "", "*", "any")


# ─────────────────────────────────────────────────────────────────────────────
# Recognition + the one shared normalizer
# ─────────────────────────────────────────────────────────────────────────────

def is_structured_rule(rule: Any) -> bool:
    """True for a Feature 18 rule object, False for a legacy string / anything else.

    Deliberately keys off `text` rather than `kind`: `text` is the only field
    every structured rule is guaranteed to have (it is what makes the object
    renderable at all), so a rule written by an older build of this module — or
    hand-edited in the DB — still normalises rather than silently vanishing from
    a prompt.
    """
    return isinstance(rule, dict) and isinstance(rule.get("text"), str) and bool(rule.get("text").strip())


def rule_kind(rule: Any) -> str:
    """The kind of a rule, treating legacy strings (and untagged dicts) as extraction rules."""
    if isinstance(rule, str):
        return KIND_EXTRACTION
    if isinstance(rule, dict):
        kind = rule.get("kind")
        return kind if kind in ALL_KINDS else KIND_EXTRACTION
    return KIND_EXTRACTION


def render_constraint(rule: Any) -> str | None:
    """Render one constraint (legacy string or structured object) to prompt text.

    Returns None for anything unrenderable, so callers can filter without
    special-casing. Never raises — a malformed row in one tenant's template must
    not take down extraction for that tenant.
    """
    if isinstance(rule, str):
        text = rule.strip()
        return text or None
    if is_structured_rule(rule):
        return rule["text"].strip()
    if isinstance(rule, dict):
        # A dict with no usable `text`: last-resort render so the rule is at
        # least visible rather than silently dropped.
        for key in ("condition", "message", "rule"):
            value = rule.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None
    if rule is None:
        return None
    try:
        text = str(rule).strip()
        return text or None
    except Exception:  # pragma: no cover - str() on a pathological object
        return None


def normalize_constraints(raw: Any, for_prompt: bool = True) -> list[str]:
    """THE shared normalizer. Every read site calls this, nothing re-implements it.

    Accepts the raw `rules["constraints"]` value (or any iterable of rules) and
    returns prompt-ready strings, de-duplicated, order-preserving.

    `for_prompt=True` (default) keeps only prompt-relevant kinds — see the module
    docstring for why a tolerance override must not reach the extraction prompt.
    `for_prompt=False` renders every rule, for display/history/version surfaces.
    """
    if not raw:
        return []
    if isinstance(raw, (str, bytes)):
        # A bare string where a list was expected: treat it as a single rule
        # rather than iterating it character by character.
        text = render_constraint(raw if isinstance(raw, str) else raw.decode("utf-8", "replace"))
        return [text] if text else []
    if isinstance(raw, dict):
        # Someone handed us the whole `rules` dict instead of its constraints.
        raw = raw.get("constraints") or []

    out: list[str] = []
    seen: set[str] = set()
    try:
        items: Iterable[Any] = list(raw)
    except TypeError:
        return []

    for rule in items:
        if for_prompt and rule_kind(rule) not in PROMPT_KINDS:
            continue
        text = render_constraint(rule)
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def constraints_of(rules: Any, for_prompt: bool = True) -> list[str]:
    """Convenience: pull `constraints` out of a `rules` dict and normalize it."""
    if isinstance(rules, dict):
        return normalize_constraints(rules.get("constraints") or [], for_prompt=for_prompt)
    return normalize_constraints(rules, for_prompt=for_prompt)


def merge_constraints(base: Any, overlay: Any) -> list[Any]:
    """Merge two raw constraint lists, overlay last (it wins on conflict), dropping
    exact duplicates. Works on mixed legacy/structured lists — de-duplication is by
    rendered text, so a structured rule that renders identically to an existing
    legacy string doesn't get applied twice.

    Returns the RAW rules (not rendered strings), because callers persist this.
    """
    merged: list[Any] = []
    seen: set[str] = set()
    for source in (base or [], overlay or []):
        for rule in source:
            text = render_constraint(rule)
            key = text if text else json.dumps(rule, sort_keys=True, default=str)
            if key in seen:
                continue
            seen.add(key)
            merged.append(rule)
    return merged


def rules_fingerprint(constraints: Any) -> str:
    """Stable hash of a constraint list, used as the preview token.

    `/commit` compares this against the token the client got from `/preview`; a
    mismatch means the session's rules changed after the user saw the impact
    estimate, which is exactly the case that must 409 rather than silently commit
    something the user never previewed.
    """
    try:
        canonical = json.dumps(list(constraints or []), sort_keys=True, default=str)
    except Exception:
        canonical = repr(constraints)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


# ─────────────────────────────────────────────────────────────────────────────
# Builders — the only sanctioned way to create a structured rule
# ─────────────────────────────────────────────────────────────────────────────

def _build(
    *,
    field: str | None,
    condition: str,
    scope: str,
    origin: str,
    text: str,
    kind: str,
    source_alert_type: str | None = None,
    params: dict | None = None,
) -> dict:
    rule = {
        "field": field or "*",
        "condition": condition,
        "scope": scope,
        "source_alert_type": source_alert_type,
        "origin": origin,
        "text": text,
        "kind": kind,
        "params": params or {},
    }
    return {k: rule[k] for k in RULE_KEYS}


def build_extraction_rule(
    text: str,
    *,
    field: str | None = None,
    scope: str = SCOPE_VENDOR,
    origin: str = ORIGIN_TRAINER_CHAT,
    source_alert_type: str | None = None,
    condition: str = "",
) -> dict:
    """A free-text instruction for the extraction LLM — the only kind that reaches a prompt."""
    return _build(
        field=field,
        condition=condition or "prompt_instruction",
        scope=scope,
        origin=origin,
        text=text.strip(),
        kind=KIND_EXTRACTION,
        source_alert_type=source_alert_type,
    )


def build_tolerance_rule(
    *,
    alert_type: str,
    field: str | None,
    abs_tol: float,
    rel_tol: float,
    scope: str = SCOPE_VENDOR,
    origin: str = ORIGIN_TRAINER_ALERT,
) -> dict:
    """Widen the tolerance for one of the three tolerance-taking checks."""
    text = (
        f"Treat a '{alert_type}' difference as acceptable when it is within "
        f"{abs_tol:.2f} absolute or {rel_tol * 100:.3g}% relative."
    )
    return _build(
        field=field,
        condition=f"abs_tol={abs_tol};rel_tol={rel_tol}",
        scope=scope,
        origin=origin,
        text=text,
        kind=KIND_TOLERANCE,
        source_alert_type=alert_type,
        params={"abs_tol": float(abs_tol), "rel_tol": float(rel_tol)},
    )


def build_confidence_threshold_rule(
    *,
    threshold: float,
    field: str | None = None,
    scope: str = SCOPE_VENDOR,
    origin: str = ORIGIN_TRAINER_ALERT,
) -> dict:
    """Lower the OCR-confidence threshold that produces `low_confidence_field`.

    Deliberately a different rule kind from the tolerance one: it tunes a
    different parameter (`threshold`) on a different function
    (`verify_field_confidence`), and conflating them would have made the numbers
    on one form silently do nothing.
    """
    text = f"Only flag low OCR confidence below {threshold:.0%}."
    return _build(
        field=field,
        condition=f"threshold={threshold}",
        scope=scope,
        origin=origin,
        text=text,
        kind=KIND_CONFIDENCE,
        source_alert_type="low_confidence_field",
        params={"threshold": float(threshold)},
    )


def build_alert_override_rule(
    *,
    alert_type: str,
    field: str | None = None,
    severity: str | None = None,
    message: str | None = None,
    scope: str = SCOPE_VENDOR,
    origin: str = ORIGIN_TRAINER_ALERT,
) -> dict:
    """Relabel an alert's severity and/or message. Never changes whether it fires."""
    parts = []
    if severity:
        parts.append(f"severity '{severity}'")
    if message:
        parts.append("a custom message")
    what = " and ".join(parts) if parts else "no change"
    text = f"Report '{alert_type}' alerts with {what}."
    params: dict[str, Any] = {}
    if severity:
        params["severity"] = severity
    if message:
        params["message"] = message
    return _build(
        field=field,
        condition=f"override={','.join(sorted(params))}",
        scope=scope,
        origin=origin,
        text=text,
        kind=KIND_ALERT_OVERRIDE,
        source_alert_type=alert_type,
        params=params,
    )


def build_audit_correction_rule(
    *,
    field: str,
    new_value: Any,
    old_value: Any,
    scope: str = SCOPE_VENDOR,
    origin: str = ORIGIN_AUDIT_CORRECTION,
) -> dict:
    """The auditor "standing rule" that `routers/audit.py` used to emit as bare text.

    The `text` is byte-identical to the sentence that function has always
    produced, so existing prompts and any operator eyeballing a template row see
    exactly what they saw before — only now the field/old/new are also available
    structurally instead of only inside the prose.
    """
    text = f"For {field.replace('_', ' ')}, extract the value as {new_value!r}, not {old_value!r}."
    return _build(
        field=field,
        condition=f"value={new_value!r}",
        scope=scope,
        origin=origin,
        text=text,
        kind=KIND_EXTRACTION,
        params={"new_value": _jsonable(new_value), "old_value": _jsonable(old_value)},
    )


def _jsonable(value: Any) -> Any:
    """Coerce a value into something the JSON column can store."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


# ─────────────────────────────────────────────────────────────────────────────
# Extractors — what verify_node reads
# ─────────────────────────────────────────────────────────────────────────────

def _iter_rules(rules: Any) -> list[Any]:
    """Accept either a `rules` dict, a constraints list, or None."""
    if not rules:
        return []
    if isinstance(rules, dict):
        raw = rules.get("constraints") or []
    else:
        raw = rules
    try:
        return list(raw)
    except TypeError:
        return []


def tolerance_overrides(rules: Any) -> dict[str, dict[str, float]]:
    """`{alert_type: {"abs_tol": float, "rel_tol": float}}` for the three eligible checks.

    Later rules win, so a vendor rule merged on top of a Global one overrides it —
    the same precedence the merged constraint list already has.
    """
    from utils.alert_registry import TOLERANCE_OVERRIDABLE_TYPES

    out: dict[str, dict[str, float]] = {}
    for rule in _iter_rules(rules):
        if not isinstance(rule, dict) or rule.get("kind") != KIND_TOLERANCE:
            continue
        alert_type = rule.get("source_alert_type")
        if alert_type not in TOLERANCE_OVERRIDABLE_TYPES:
            continue
        params = rule.get("params") or {}
        try:
            entry = {}
            if params.get("abs_tol") is not None:
                entry["abs_tol"] = float(params["abs_tol"])
            if params.get("rel_tol") is not None:
                entry["rel_tol"] = float(params["rel_tol"])
        except (TypeError, ValueError):
            logger.warning("Ignoring tolerance override with non-numeric params: %s", params)
            continue
        if entry:
            out[alert_type] = entry
    return out


def confidence_threshold_override(rules: Any) -> float | None:
    """The tenant's overridden OCR-confidence threshold, or None to use the default.

    Clamped to (0, 1]: a threshold of 0 would disable the check entirely, which is
    a suppression the "unnecessary alert" flow deliberately doesn't offer (the
    user is widening a tolerance, not turning verification off).
    """
    threshold: float | None = None
    for rule in _iter_rules(rules):
        if not isinstance(rule, dict) or rule.get("kind") != KIND_CONFIDENCE:
            continue
        try:
            value = float((rule.get("params") or {}).get("threshold"))
        except (TypeError, ValueError):
            continue
        if 0.0 < value <= 1.0:
            threshold = value
    return threshold


def alert_overrides(rules: Any) -> list[dict]:
    """Severity/message relabel rules, in application order (later wins)."""
    out = []
    for rule in _iter_rules(rules):
        if not isinstance(rule, dict) or rule.get("kind") != KIND_ALERT_OVERRIDE:
            continue
        params = rule.get("params") or {}
        if not params.get("severity") and not params.get("message"):
            continue
        out.append({
            "type": rule.get("source_alert_type"),
            "field": rule.get("field"),
            "severity": params.get("severity"),
            "message": params.get("message"),
        })
    return out


def apply_alert_overrides(alerts: list, rules: Any) -> list:
    """Relabel produced alerts per the tenant's override rules.

    Runs *after* the checks, never inside them — `utils/verification_tools.py`'s
    checks are deliberately left unrestructured (they only gained an optional
    `tolerances` parameter). An overridden alert keeps its original text under
    `original_message` so an auditor can still see what the system actually
    computed, not only what the tenant chose to call it.
    """
    overrides = alert_overrides(rules)
    if not overrides or not alerts:
        return alerts

    result = []
    for alert in alerts:
        if not isinstance(alert, dict):
            result.append(alert)
            continue
        updated = alert
        for override in overrides:
            if override["type"] and override["type"] != alert.get("type"):
                continue
            if override["field"] not in _WILDCARD_FIELDS and override["field"] != alert.get("field"):
                continue
            updated = dict(updated)
            if override.get("severity"):
                updated["severity"] = override["severity"]
            if override.get("message"):
                updated.setdefault("original_message", alert.get("message"))
                updated["message"] = override["message"]
            updated["overridden_by_rule"] = True
        result.append(updated)
    return result
