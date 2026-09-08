"""Feature 29 task 29.11 -- deterministic entity resolution for a chat turn.

Before this module, "which invoice / vendor / attachment does the user mean?" was
answered by keyword lists scattered through `agents/query_agent.py` and by the
LLM's own guess inside generated SQL. Spec section 4.2 staged the fix: a
deterministic resolver FIRST, with an automatic clarify on 0 or >1 matches, and
only then (Feature 30 task 30.16) a planner. This is the resolver.

What it does, and only this:

* **Invoice numbers.** Every token shaped like an invoice number is looked up
  exactly (case- and whitespace-insensitive, parameterised, tenant-scoped).
  A token that matches nothing exactly is compared against the tenant's
  invoice numbers with `difflib`; a close-enough neighbour is offered as a
  *suggestion*, never bound -- a typo becomes "did you mean", not an invention.
* **Vendor names.** A name introduced by "from / by / vendor / supplier / of"
  or possessive ("Acme's invoices") is matched against the tenant's distinct
  `vendor_name`s: substring first, then `difflib` above a threshold. Exactly
  one hit binds; several hits are returned as candidates for a clarify card.
* **Attachments.** "this document / the attached / the PO / the second one"
  binds to the session's attachments by count, ordinal or document type.
* **Session references.** "the first one / the second invoice / that one"
  binds against the invoice ids the previous turn returned.

Everything is deterministic (hard rule 3): no model call, no fuzzy binding
below the thresholds, and a resolver that cannot decide says so through
`ResolutionResult.needs_clarification` instead of guessing. It is fail-soft --
any database error resolves nothing, so a broken resolver degrades to the
keyword routing that existed before it, never to a dead turn.

The module is wired into `agents/query_agent.py` behind
`Settings.ENABLE_ENTITY_RESOLVER` (default False, Gap 482). Off, nothing here
runs.
"""
from __future__ import annotations

import difflib
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Sequence

from sqlalchemy import bindparam, text

logger = logging.getLogger(__name__)

# Same shape `query_agent.invoice_ids_named_in()` recognises (task 29.5), so the
# two never disagree about what an invoice number looks like.
INVOICE_NUMBER_PATTERN = re.compile(r"\b[A-Za-z]{2,}-\d{4,}-\d{2,}\b")

#: A vendor mention: "from Acme Corp", "by Acme", "vendor Acme", "Acme's invoices".
#: The name runs until punctuation, a question word, or the end of the sentence.
_VENDOR_LEAD_PATTERN = re.compile(
    r"\b(?:from|by|vendor|supplier|of)\s+(?P<name>[A-Z][\w&.'-]*(?:\s+[A-Z][\w&.'-]*){0,4})",
)
_VENDOR_POSSESSIVE_PATTERN = re.compile(
    r"\b(?P<name>[A-Z][\w&.-]*(?:\s+[A-Z][\w&.-]*){0,4})'s\s+(?:invoice|invoices|bill|bills)\b",
)
#: Words that end a vendor mention when the lead pattern over-captures.
_VENDOR_STOP_WORDS = {
    "invoice", "invoices", "bill", "bills", "in", "on", "for", "and", "or", "the",
    "what", "which", "how", "when", "is", "are", "was", "were", "last", "this", "that",
    "total", "amount", "due", "paid", "overdue", "month", "year", "week", "today",
}

_ORDINALS = {
    "first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2,
    "fourth": 3, "4th": 3, "fifth": 4, "5th": 4, "last": -1,
}
_ORDINAL_REFERENCE_PATTERN = re.compile(
    r"\bthe\s+(?P<ord>first|1st|second|2nd|third|3rd|fourth|4th|fifth|5th|last)\s+"
    r"(?P<noun>one|invoice|document|attachment|file|po|purchase order|quote|quotation|contract|statement)\b",
    re.IGNORECASE,
)
_ATTACHMENT_REFERENCE_PATTERN = re.compile(
    r"\b(?:this|the|that)\s+(?:attached\s+)?(?P<noun>document|attachment|file|po|purchase order|"
    r"quote|quotation|contract|statement|credit note|debit note|delivery note|remittance)\b"
    r"|\bthe\s+attached\b|\battached\s+(?:document|file)\b",
    re.IGNORECASE,
)
_DEMONSTRATIVE_INVOICE_PATTERN = re.compile(
    r"\b(?:that|this)\s+(?:one|invoice)\b|\bthe\s+same\s+invoice\b", re.IGNORECASE
)

#: Attachment doc_type words -> `ChatAttachment.doc_type` values.
_DOC_TYPE_WORDS = {
    "po": "PURCHASE_ORDER", "purchase order": "PURCHASE_ORDER",
    "quote": "QUOTATION", "quotation": "QUOTATION",
    "contract": "CONTRACT", "statement": "STATEMENT",
    "credit note": "CREDIT_NOTE", "debit note": "DEBIT_NOTE",
    "delivery note": "DELIVERY_NOTE", "remittance": "REMITTANCE",
}

#: Fuzzy thresholds. Deliberately high: below these a mention is "none", which
#: clarifies, rather than a wrong binding, which answers about the wrong thing.
INVOICE_SUGGEST_RATIO = 0.80
VENDOR_FUZZY_RATIO = 0.85


@dataclass(frozen=True)
class Candidate:
    """One thing a mention could refer to."""

    id: str
    label: str
    score: float = 1.0


@dataclass(frozen=True)
class ResolvedEntity:
    """One mention in the question and what it resolved to.

    `status` is exactly one of `bound` (one candidate, safe to use), `ambiguous`
    (several -- clarify), `suggested` (nothing exact, one or more near-misses --
    "did you mean") or `none` (nothing at all -- clarify or abstain).
    """

    kind: str  # invoice | vendor | attachment
    mention: str
    candidates: tuple[Candidate, ...] = ()
    status: str = "none"

    @property
    def bound_id(self) -> Optional[str]:
        return self.candidates[0].id if self.status == "bound" else None


@dataclass
class ResolutionResult:
    entities: list[ResolvedEntity] = field(default_factory=list)

    @property
    def invoice_ids(self) -> list[str]:
        out: list[str] = []
        for e in self.entities:
            if e.kind == "invoice" and e.bound_id and e.bound_id not in out:
                out.append(e.bound_id)
        return out

    @property
    def vendor_names(self) -> list[str]:
        """Every spelling of every bound vendor.

        Feature 30 30.0f widened this from `candidates[0].label` to all of them.
        Before the vendor master a bound vendor had exactly one candidate by
        construction, so for the keyword path this returns the same list it
        always did; with the master, one bound vendor carries every
        `invoice.vendor_name` spelling the tenant has confirmed as that
        supplier, and dropping all but the first would re-introduce the split
        history the master exists to fix.
        """
        out: list[str] = []
        for e in self.entities:
            if e.kind != "vendor" or e.status != "bound":
                continue
            for c in e.candidates:
                if c.label not in out:
                    out.append(c.label)
        return out

    @property
    def attachment_ids(self) -> list[str]:
        out: list[str] = []
        for e in self.entities:
            if e.kind == "attachment" and e.bound_id and e.bound_id not in out:
                out.append(e.bound_id)
        return out

    @property
    def unresolved(self) -> list[ResolvedEntity]:
        return [e for e in self.entities if e.status != "bound"]

    @property
    def needs_clarification(self) -> bool:
        return bool(self.unresolved)

    def clarify_message(self) -> str:
        """The deterministic clarify card: one line per unresolved mention, with the
        candidates listed so the user can answer by name rather than re-typing."""
        lines: list[str] = []
        for e in self.unresolved:
            noun = {"invoice": "invoice", "vendor": "vendor", "attachment": "attached document"}[e.kind]
            if e.status == "ambiguous":
                opts = "; ".join(c.label for c in e.candidates[:5])
                lines.append(f"Which {noun} do you mean by \"{e.mention}\"? I found {len(e.candidates)}: {opts}.")
            elif e.status == "suggested":
                opts = ", ".join(c.label for c in e.candidates[:3])
                lines.append(f"I have no {noun} \"{e.mention}\". Did you mean {opts}?")
            else:
                lines.append(f"I could not find a {noun} matching \"{e.mention}\" in your records.")
        return " ".join(lines)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def resolve_entities(
    question: str,
    tenant_id: str,
    db_session,
    attachments: Optional[Sequence[Any]] = None,
    recent_invoice_ids: Optional[Sequence[str]] = None,
) -> ResolutionResult:
    """Resolve every invoice / vendor / attachment mention in `question`.

    `attachments` are the session's `ChatAttachment` rows (or anything with
    `id`, `doc_type`, `filename`, ordered as attached). `recent_invoice_ids` are
    the invoice ids the previous assistant turn returned, for "the second one".
    Never raises: a database failure resolves to no entities.
    """
    result = ResolutionResult()
    if not question or not tenant_id:
        return result
    try:
        result.entities.extend(_resolve_invoice_numbers(question, tenant_id, db_session))
        result.entities.extend(_resolve_vendors(question, tenant_id, db_session))
        result.entities.extend(_resolve_attachments(question, attachments or ()))
        result.entities.extend(_resolve_session_references(question, recent_invoice_ids or ()))
    except Exception as e:  # pragma: no cover - defensive; individual steps already guard
        logger.warning("29.11: entity resolution failed (non-fatal): %s", e)
        _rollback(db_session)
    return result


# ---------------------------------------------------------------------------
# Invoice numbers
# ---------------------------------------------------------------------------


def _resolve_invoice_numbers(question: str, tenant_id: str, db_session) -> list[ResolvedEntity]:
    mentions = list(dict.fromkeys(INVOICE_NUMBER_PATTERN.findall(question)))
    if not mentions:
        return []
    exact = _exact_invoice_lookup(mentions, tenant_id, db_session)
    out: list[ResolvedEntity] = []
    missing = [m for m in mentions if m.strip().lower() not in exact]
    known = _tenant_invoice_numbers(tenant_id, db_session) if missing else {}
    for m in mentions:
        key = m.strip().lower()
        if key in exact:
            inv_id, number = exact[key]
            out.append(ResolvedEntity("invoice", m, (Candidate(inv_id, number),), "bound"))
            continue
        near = difflib.get_close_matches(key, list(known), n=3, cutoff=INVOICE_SUGGEST_RATIO)
        if near:
            cands = tuple(
                Candidate(known[k][0], known[k][1], difflib.SequenceMatcher(None, key, k).ratio())
                for k in near
            )
            out.append(ResolvedEntity("invoice", m, cands, "suggested"))
        else:
            out.append(ResolvedEntity("invoice", m, (), "none"))
    return out


def _exact_invoice_lookup(mentions: Iterable[str], tenant_id: str, db_session) -> dict[str, tuple[str, str]]:
    try:
        rows = db_session.execute(
            text(
                "SELECT id, invoice_number FROM invoice WHERE tenant_id = :tenant_id "
                "AND TRIM(LOWER(invoice_number)) IN :candidates"
            ).bindparams(bindparam("candidates", expanding=True)),
            {"tenant_id": str(tenant_id), "candidates": [m.strip().lower() for m in mentions]},
        ).fetchall()
    except Exception as e:
        logger.warning("29.11: exact invoice lookup failed (non-fatal): %s", e)
        _rollback(db_session)
        return {}
    return {str(r[1]).strip().lower(): (str(r[0]), str(r[1])) for r in rows if r[1]}


def _tenant_invoice_numbers(tenant_id: str, db_session) -> dict[str, tuple[str, str]]:
    try:
        rows = db_session.execute(
            text(
                "SELECT id, invoice_number FROM invoice WHERE tenant_id = :tenant_id "
                "AND invoice_number IS NOT NULL LIMIT 5000"
            ),
            {"tenant_id": str(tenant_id)},
        ).fetchall()
    except Exception as e:
        logger.warning("29.11: invoice-number listing failed (non-fatal): %s", e)
        _rollback(db_session)
        return {}
    return {str(r[1]).strip().lower(): (str(r[0]), str(r[1])) for r in rows if r[1]}


# ---------------------------------------------------------------------------
# Vendors
# ---------------------------------------------------------------------------


def _vendor_mentions(question: str) -> list[str]:
    found: list[str] = []
    for pat in (_VENDOR_POSSESSIVE_PATTERN, _VENDOR_LEAD_PATTERN):
        for m in pat.finditer(question):
            words = []
            for w in m.group("name").split():
                if w.lower().strip(".,?!") in _VENDOR_STOP_WORDS:
                    break
                words.append(w.strip(".,?!"))
            name = " ".join(words).strip()
            # a lone invoice number after "from" is not a vendor
            if name and not INVOICE_NUMBER_PATTERN.fullmatch(name) and name not in found:
                found.append(name)
    return found


def _resolve_vendors(question: str, tenant_id: str, db_session) -> list[ResolvedEntity]:
    mentions = _vendor_mentions(question)
    if not mentions:
        return []
    names = _tenant_vendor_names(tenant_id, db_session)
    out: list[ResolvedEntity] = []
    for mention in mentions:
        # Feature 30 task 30.0f: the per-tenant vendor master answers first.
        # It is the only thing that knows "Shree Packaging Pvt Ltd" and "SHREE
        # PACKAGING" are one supplier, and without it the three lines below
        # return ambiguous (two spellings) or bind to whichever spelling the
        # substring test happened to hit. A tenant with no vendor rows -- every
        # tenant until ENABLE_ATTACHMENT_INSIGHTS opens one -- resolves to
        # "none" here and falls straight through to the pre-existing matching,
        # so this addition is inert until the vendor master has content.
        #
        # It binds ONLY on a canonical name or a CONFIRMED alias. A "proposed"
        # resolution is deliberately allowed to fall through rather than being
        # surfaced as a clarify: an unconfirmed alias is not evidence, and 30.0f
        # owns that confirmation flow (POST /chat/vendors/aliases/confirm),
        # not the chat clarify card.
        mastered = _vendor_master_candidates(mention, tenant_id, db_session)
        if mastered:
            out.append(ResolvedEntity("vendor", mention, mastered, "bound"))
            continue
        key = mention.lower()
        hits = [n for n in names if key in n.lower() or n.lower() in key]
        if not hits:
            hits = difflib.get_close_matches(key, [n.lower() for n in names], n=5, cutoff=VENDOR_FUZZY_RATIO)
            hits = [n for n in names if n.lower() in hits]
        cands = tuple(Candidate(n, n, difflib.SequenceMatcher(None, key, n.lower()).ratio()) for n in hits)
        cands = tuple(sorted(cands, key=lambda c: -c.score))
        status = "bound" if len(cands) == 1 else "ambiguous" if cands else "none"
        out.append(ResolvedEntity("vendor", mention, cands, status))
    return out


def _vendor_master_candidates(mention: str, tenant_id: str, db_session) -> tuple:
    """Feature 30 30.0f: every invoice spelling of the vendor this mention binds to.

    Returns () when the vendor master cannot bind the mention -- which is both
    the "no such vendor" case and the "not confirmed yet" case, because neither
    is something the resolver may act on. The candidates are `invoice.vendor_name`
    spellings, not canonical names, because that is the column every downstream
    query filters on.
    """
    try:
        from services.vendor_master import resolve_vendor, vendor_invoice_names

        resolution = resolve_vendor(mention, tenant_id, db_session)
        if not resolution.is_bound:
            return ()
        spellings = vendor_invoice_names(resolution.vendor.id, tenant_id, db_session)
        if not spellings:
            # The vendor is known but has no invoices under any spelling yet.
            # Bind to the canonical name so the mention is still resolved.
            spellings = [resolution.vendor.canonical_name]
        return tuple(Candidate(n, n, 1.0) for n in spellings)
    except Exception as e:  # pragma: no cover - defensive, same rule as the rest
        logger.warning("30.0f: vendor master lookup failed (non-fatal): %s", e)
        return ()


def _tenant_vendor_names(tenant_id: str, db_session) -> list[str]:
    try:
        rows = db_session.execute(
            text(
                "SELECT DISTINCT vendor_name FROM invoice WHERE tenant_id = :tenant_id "
                "AND vendor_name IS NOT NULL AND TRIM(vendor_name) <> '' LIMIT 5000"
            ),
            {"tenant_id": str(tenant_id)},
        ).fetchall()
    except Exception as e:
        logger.warning("29.11: vendor listing failed (non-fatal): %s", e)
        _rollback(db_session)
        return []
    return [str(r[0]).strip() for r in rows if r[0]]


# ---------------------------------------------------------------------------
# Attachments and session references
# ---------------------------------------------------------------------------


def _attachment_label(a: Any) -> str:
    doc_type = str(getattr(a, "doc_type", "") or "").replace("_", " ").title()
    name = getattr(a, "filename", None) or getattr(a, "doc_number", None) or str(getattr(a, "id", ""))
    return f"{doc_type} {name}".strip()


def _resolve_attachments(question: str, attachments: Sequence[Any]) -> list[ResolvedEntity]:
    out: list[ResolvedEntity] = []
    items = list(attachments)

    for m in _ORDINAL_REFERENCE_PATTERN.finditer(question):
        noun = m.group("noun").lower()
        if noun in ("one", "invoice"):
            continue  # a session-invoice reference, handled below
        idx = _ORDINALS[m.group("ord").lower()]
        pool = [a for a in items if _DOC_TYPE_WORDS.get(noun) in (None, getattr(a, "doc_type", None))]
        if pool and -len(pool) <= idx < len(pool):
            a = pool[idx]
            out.append(ResolvedEntity("attachment", m.group(0), (Candidate(str(a.id), _attachment_label(a)),), "bound"))
        else:
            out.append(ResolvedEntity("attachment", m.group(0), (), "none"))

    for m in _ATTACHMENT_REFERENCE_PATTERN.finditer(question):
        mention = m.group(0)
        if any(e.mention.lower().endswith(mention.lower()) for e in out):
            continue
        noun = (m.group("noun") or "").lower()
        wanted = _DOC_TYPE_WORDS.get(noun)
        pool = [a for a in items if wanted is None or getattr(a, "doc_type", None) == wanted]
        cands = tuple(Candidate(str(a.id), _attachment_label(a)) for a in pool)
        status = "bound" if len(cands) == 1 else "ambiguous" if cands else "none"
        out.append(ResolvedEntity("attachment", mention, cands, status))
    return out


def _resolve_session_references(question: str, recent_invoice_ids: Sequence[str]) -> list[ResolvedEntity]:
    out: list[ResolvedEntity] = []
    ids = [str(i) for i in recent_invoice_ids]
    for m in _ORDINAL_REFERENCE_PATTERN.finditer(question):
        if m.group("noun").lower() not in ("one", "invoice"):
            continue
        idx = _ORDINALS[m.group("ord").lower()]
        if ids and -len(ids) <= idx < len(ids):
            out.append(ResolvedEntity("invoice", m.group(0), (Candidate(ids[idx], ids[idx]),), "bound"))
        else:
            out.append(ResolvedEntity("invoice", m.group(0), (), "none"))
    if not out:
        for m in _DEMONSTRATIVE_INVOICE_PATTERN.finditer(question):
            if len(ids) == 1:
                out.append(ResolvedEntity("invoice", m.group(0), (Candidate(ids[0], ids[0]),), "bound"))
            elif ids:
                out.append(ResolvedEntity("invoice", m.group(0), tuple(Candidate(i, i) for i in ids[:5]), "ambiguous"))
            else:
                out.append(ResolvedEntity("invoice", m.group(0), (), "none"))
            break
    return out


def _rollback(db_session) -> None:
    try:
        db_session.rollback()
    except Exception:
        pass


__all__ = [
    "Candidate",
    "ResolvedEntity",
    "ResolutionResult",
    "resolve_entities",
    "INVOICE_NUMBER_PATTERN",
    "INVOICE_SUGGEST_RATIO",
    "VENDOR_FUZZY_RATIO",
]
