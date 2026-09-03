"""Feature 27 (G2) — what kind of commercial document is this?

`services/invoice_classifier.py` answers "how hard is this to extract"
(STANDARD/COMPLEX). This module answers a different question — "what *is* it" —
and the two are consulted at different points for different reasons, which is why
this is its own module rather than a second function over there. An invoice and a
contract can each be simple or complex; the two classifications are orthogonal.

Design record: `docs/feature_27_generic_extraction.md`, decisions E4 (the closed
ten-value taxonomy, the regional synonym table and the verification families) and
E7 (the two-stage, deterministic-first classifier). Read those before changing
anything here.

**Two-stage, deterministic first.** `classify_doc_type_deterministic()` matches
the printed title band against `_DOC_TYPE_SYNONYMS` and short-circuits with **no
LLM call at all** on an unambiguous hit. That is the control, not an
optimisation: "Lieferschein" printed at the top of a page is a *fact* about the
document, not a judgement, and facts belong in code (CONVENTIONS hard rule 3).
The LLM fallback in `classify_doc_type()` runs only when the deterministic pass
found nothing or found two document types in one title line, and its output is
constrained by a `Literal` over the closed enum so an invented value is a
validation error rather than a silently-stored string.

**Wiring status.** As of G2 this module is standalone and called from nowhere.
`classify_doc_type_node`, the graph entry point, the per-family schema/rubric
selection and the `documents` table are G3/G3b/G4/G5/G9, and all of them stay
behind `settings.ENABLE_GENERIC_EXTRACTION` (software-level, never per-tenant —
E2). This module deliberately does **not** read that flag: it is a pure function
of its input, so it can be tested in isolation, and the caller decides whether to
consult it at all.
"""
import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field, ValidationError

from telemetry import tracked_llm_call
from utils.llm import get_llm

logger = logging.getLogger(__name__)


# --- E4: the closed taxonomy -------------------------------------------------
#
# Ten values, in **commercial-lifecycle order** — quote -> proforma -> order ->
# contract -> delivery -> receipt -> invoice -> adjustments. The ordering is not
# cosmetic: it is the order a matching/reconciliation feature walks, so keeping
# the tuple in it means the enum itself documents the procure-to-pay chain. Do
# not re-sort it alphabetically.
#
# `PROFORMA_INVOICE` is its own value, not a synonym for either neighbour: it
# sits after commitment and before shipment, looks structurally like an invoice
# but is not a tax document — no receivable, no input-tax credit, no payment
# obligation. Folding it into `INVOICE` puts a non-payable in the payable family.
#
# `DELIVERY_NOTE`, not `CHALLAN`: a Lieferschein and a delivery challan are the
# same document type and must land on the same value. Naming the canonical value
# after one region's label would have been an actual defect.
#
# `INVOICE` is one type with documented sub-cases (India Tax Invoice / E-Invoice
# with IRN+QR / Bill of Supply, EU VAT invoice incl. reverse charge, US
# commercial invoice). Those are carried in the *extracted fields*
# (`compliance_metadata` already exists for IRN/QR/Peppol), not split across enum
# values — splitting would fragment spend, dashboard insights and the
# AUDIT_REQUIRED count across values that all mean "a bill we owe".
#
# Transport documents — bill of lading, air waybill, CMR, India's e-way bill —
# are deliberately **out of v1** (E5) and route to `OTHER`. They are custody/title
# documents with carrier-issued, externally-verifiable identifiers, and nothing
# downstream consumes them yet.
DOC_TYPES = (
    "QUOTATION",
    "PROFORMA_INVOICE",
    "PURCHASE_ORDER",
    "ORDER_CONFIRMATION",     # A5/R7 — seller->buyer ack; often the REAL agreed price
    "CONTRACT",
    "DELIVERY_NOTE",          # A5/R7 — now also absorbs PACKING_LIST
    "GRN",
    "INVOICE",
    "RECEIPT",                # A5/R7 — payment/fiscal receipt + simplified invoice
    "CREDIT_NOTE",
    "DEBIT_NOTE",
    "REMITTANCE_ADVICE",      # A5/R7 — advisory; "what did they short-pay?"
    "STATEMENT_OF_ACCOUNT",   # A5/R7 — advisory; "which of these are unpaid?"
    "OTHER",
)


# --- E4: the three verification families -------------------------------------
#
# This map is the taxonomy's real payload. G5's `_RUBRIC_BY_DOC_TYPE` is derived
# from it, so adding an eleventh type later is one entry here plus one rubric —
# never a new `if doc_type == ...` branch in verification code.
#
#   MONEY      — full existing arithmetic: line-item sum vs subtotal,
#                subtotal + tax - discount vs grand total, currency present,
#                faithfulness against OCR. This is today's rubric, unchanged.
#   QUANTITY   — price fields are optional and frequently absent *by design* (a
#                delivery note prints quantity and description only, precisely so
#                warehouse staff cannot see pricing). Absent price is not a
#                discrepancy.
#   COMMITMENT — money + quantity, terms-heavy, longer horizon. Arithmetic runs
#                where totals are printed, but an unpriced schedule line is
#                normal and a framework agreement/rate card frequently has no
#                grand total at all. Missing-total is not a failure here.
#   OTHER      — advisory only: alerts are recorded but never set a review
#                status, because we do not know what the document is and have no
#                rubric we can defend.
#
# TWO NAMING NOTES FOR WHOEVER IMPLEMENTS G3b/G5 — both are real and neither is
# settled by E4 itself:
#
# 1. The money family's key here is `MONEY`, following E4's own family table.
#    Amendments A1 and A2 were written later and compare against the string
#    `"INVOICE"` (`DOC_TYPE_FAMILY[doc_type] != "INVOICE"`). Those are the same
#    family under two names; this module ships E4's name because `INVOICE` is
#    already an enum *value* and a map whose keys and values overlap invites
#    exactly the confusion that would make `!= "INVOICE"` silently true for every
#    document. G3b/G5 must use `MONEY_FAMILY` (below) rather than a bare string
#    literal either way.
# 2. E4's family table never assigns `QUOTATION`. It is mapped to `COMMITMENT`
#    here, provisionally and deliberately conservatively: a quotation prints
#    prices and is arithmetically checkable, but it is not a payable and a
#    partially-priced or unpriced quote is normal, so `MONEY` — which requires a
#    currency and a reconciling grand total — would recreate the false-discrepancy
#    class this feature exists to remove. Flagged for founder confirmation when
#    G5 builds the rubric map; it is an open decision, not a settled one.
MONEY_FAMILY = "MONEY"
QUANTITY_FAMILY = "QUANTITY"
COMMITMENT_FAMILY = "COMMITMENT"
OTHER_FAMILY = "OTHER"
# A7/R9. Research §2's "A" family: documents that report ON other documents and
# are never themselves payable. Distinct from OTHER_FAMILY, which means "we could
# not establish what this is" -- these we know exactly, and knowing is what earns
# them a schema (`referenced_documents[]`, `deductions[]`) and their own
# comparison mode (Feature 26 B8's `list_reconcile`). DUNNING and PAYMENT_PROOF
# join them if either is ever promoted out of OTHER.
ADVISORY_FAMILY = "ADVISORY"

DOC_TYPE_FAMILY: Dict[str, str] = {
    # FOUNDER RULING, 2026-09-03 (A5/R7): QUOTATION is COMMITMENT, settled. It is
    # priced and arithmetically checkable but is not a payable, and a
    # partially-priced quote is normal -- MONEY, which wants a currency and a
    # reconciling grand total, would recreate the false-discrepancy class this
    # whole feature exists to remove. No longer provisional.
    "QUOTATION": COMMITMENT_FAMILY,
    "PROFORMA_INVOICE": MONEY_FAMILY,
    "PURCHASE_ORDER": COMMITMENT_FAMILY,
    # A5/R7. Distinguished from PURCHASE_ORDER by DIRECTION (seller->buyer), not
    # by layout -- research §6.1. Same commitment rubric: it states agreed goods,
    # prices and terms over a horizon, and a partially-priced ack is normal.
    "ORDER_CONFIRMATION": COMMITMENT_FAMILY,
    "CONTRACT": COMMITMENT_FAMILY,
    "DELIVERY_NOTE": QUANTITY_FAMILY,
    "GRN": QUANTITY_FAMILY,
    "INVOICE": MONEY_FAMILY,
    # A5/R7. MONEY, but the money rubric must tolerate a legally-absent buyer
    # name, unit price and VAT amount (research §5 trap 9: DE Kleinbetragsrechnung
    # <=EUR 250, IT scontrino, ES ticket, PL <= PLN 450, India cash memo). The
    # RELAXATION ITSELF IS R8's -- it rides on `invoice_subtype=SIMPLIFIED` and
    # the per-sub-type expected-absent set. Until then a RECEIPT is graded as an
    # invoice, which can over-flag; that is the honest interim state and is why
    # R8 follows immediately.
    "RECEIPT": MONEY_FAMILY,
    "CREDIT_NOTE": MONEY_FAMILY,
    "DEBIT_NOTE": MONEY_FAMILY,
    # A7/R9: moved off the interim OTHER_FAMILY mapping R7 left here. The
    # never-set-a-review-status guarantee is unchanged (both rubrics are
    # `advisory_only`); what ADVISORY adds is the two arithmetic flags switched
    # OFF -- a statement has a running balance, not a subtotal/tax/total triple,
    # so the money checks had nothing to check -- plus the schema lists and
    # Feature 26's `list_reconcile` comparison mode.
    "REMITTANCE_ADVICE": ADVISORY_FAMILY,
    "STATEMENT_OF_ACCOUNT": ADVISORY_FAMILY,
    "OTHER": OTHER_FAMILY,
}


# --- E4: the regional synonym table ------------------------------------------
#
# Ships as a deterministic normalisation map **and** in the classifier prompt
# (`_build_classifier_prompt()` renders it from this same dict), so the two
# cannot drift.
#
# Entries are matched against the *normalised* title band — lower-cased, accents
# folded, `.`/`'` dropped, every other non-alphanumeric collapsed to a single
# space. So "D.D.T." matches `ddt`, "Albarán" matches `albaran`, "E-Invoice"
# matches `e invoice`. Write entries in that normalised form.
#
# SCOPE, STATED HONESTLY: E4 gives a full regional table for `DELIVERY_NOTE` and
# names the `INVOICE` sub-cases. For the other eight types this map carries the
# canonical name plus widely-printed English variants only — non-English labels
# for them (Rechnung, Angebot, Auftrag, Gutschrift, ...) are **deliberately not
# invented here**. A German invoice titled "Rechnung" therefore falls through to
# the LLM fallback and is classified correctly but at the cost of one call. §7
# task F's real fixtures are what should close that, with the printed title
# recorded per file — guessing foreign vocabulary from an office chair is how a
# synonym table acquires entries no real document has ever carried.
_DOC_TYPE_SYNONYMS: Dict[str, Tuple[str, ...]] = {
    "QUOTATION": (
        "quotation",
        "sales quotation",
        "price quotation",
        "quote",
        "price quote",
        "estimate",
    ),
    "PROFORMA_INVOICE": (
        # "pro-forma" and "pro forma" both normalise to "pro forma".
        "proforma invoice",
        "pro forma invoice",
        "proforma",
    ),
    "PURCHASE_ORDER": (
        "purchase order",
        # Deliberately NOT the bare acronym "po": two letters match far too much
        # ordinary text, and the title-band guard is not a substitute for a
        # synonym that is simply too weak to be evidence.
    ),
    "CONTRACT": (
        "contract",
        "agreement",
        "service agreement",
        "master service agreement",
        "framework agreement",
        # BE Gap 396: the German for it, absent until now -- EU-CT-01 is titled
        # RAHMENVERTRAG and reached CONTRACT only via a paid model call.
        "rahmenvertrag",
        "abrufauftrag",
        "rate contract",
    ),
    "DELIVERY_NOTE": (
        # India
        "delivery challan",
        "challan",
        "goods delivery note",
        # US
        "packing slip",
        "packing list",
        # A5/R7 -- the PACKING_LIST fold. It is NOT its own type: same quantity
        # rubric, same absent-price expectation, so a second value would split one
        # document class across two enum entries for no downstream difference.
        "pack list",
        "pick ticket",
        "case list",
        "packliste",
        "liste de colisage",
        "distinta di imballaggio",
        "lista de embalaje",
        "paklijst",
        "lista pakowa",
        "dispatch note",
        "job work challan",
        "guia de remessa",
        "delivery note",
        "shipping list",
        # Germany / DACH
        "lieferschein",
        # Italy — "DDT", Documento di Trasporto
        "ddt",
        "documento di trasporto",
        # France
        "bon de livraison",
        # Netherlands
        "pakbon",
        # Spain — "Albarán"; accents are folded before matching
        "albaran",
    ),
    "GRN": (
        # Low-frequency and internal-origin by nature (E4): a GRN is generated by
        # the *buyer's* receiving process and usually never leaves the buyer's
        # ERP. It appears here mainly when an enterprise buyer shares one with a
        # supplier to substantiate a short-delivery claim. Low GRN volume is not
        # a classifier defect.
        "goods receipt note",
        "goods received note",
        "grn",
        "material receipt note",
        "receiving report",
    ),
    "INVOICE": (
        "invoice",
        # India
        "tax invoice",
        "gst invoice",
        "e invoice",
        "bill of supply",
        # EU
        "vat invoice",
        # US
        "commercial invoice",
    ),
    "CREDIT_NOTE": (
        "credit note",
        "credit memo",
        "credit memorandum",
    ),
    "DEBIT_NOTE": (
        "debit note",
        "debit memo",
        "debit memorandum",
    ),
    # --- A5/R7: the four new types ------------------------------------------
    "ORDER_CONFIRMATION": (
        "order confirmation",
        "order acknowledgement",
        "order acknowledgment",
        "sales order",
        # DE/IT/NL manufacturing and wholesale, where this document is routine.
        # "ab" and "oa" are deliberately ABSENT: two letters match too much
        # ordinary text for the title-band coverage guard to redeem, which is the
        # same call G2 made for PURCHASE_ORDER's "po".
        # BOTH German spellings. `_normalize()` folds an umlaut to its base
        # letter ("Auftragsbestätigung" -> "auftragsbestatigung") but leaves the
        # ASCII TRANSLITERATION alone ("AUFTRAGSBESTAETIGUNG" ->
        # "auftragsbestaetigung"). Both are correct German and the transliteration
        # is what every system that cannot emit umlauts produces -- which is most
        # ERP exports, and was every one of this repo's own generated fixtures.
        # BE Gap 396: carrying only the folded form made the classifier pay for an
        # LLM call on a document whose title it should have recognised outright.
        "auftragsbestatigung",
        "auftragsbestaetigung",
        # Written in the NORMALISED form: `_normalize()` strips the apostrophe
        # rather than turning it into a space, so "Conferma d'ordine" folds to
        # "conferma dordine". Synonyms are matched post-normalisation, so this is
        # the spelling that matches -- a human-readable "conferma d ordine" never
        # would.
        "conferma dordine",
        "confirmacion de pedido",
        "orderbevestiging",
        "potwierdzenie zamowienia",
    ),
    "RECEIPT": (
        "receipt",
        "payment receipt",
        "cash memo",
        "expense receipt",
        # The simplified-invoice family (research §5 trap 9) -- legally allowed to
        # omit the buyer, the unit price and the VAT amount.
        "kleinbetragsrechnung",
        "facture simplifiee",
        "fattura semplificata",
        "scontrino",
        "factura simplificada",
        "faktura uproszczona",
    ),
    "REMITTANCE_ADVICE": (
        "remittance advice",
        "payment advice",
        "zahlungsavis",
        "avis de paiement",
        "avviso di pagamento",
        "aviso de pago",
        "betalingsspecificatie",
    ),
    "STATEMENT_OF_ACCOUNT": (
        "statement of account",
        "account statement",
        "vendor statement",
        "aging statement",
        "balance confirmation",
        "kontoauszug",
        "saldenbestatigung",
        "saldenbestaetigung",  # BE Gap 396, see ORDER_CONFIRMATION above
        "releve de compte",
        "estratto conto",
        "extracto de cuenta",
        "rekeningoverzicht",
    ),
    # --- E5's deferred documents, routed to OTHER DETERMINISTICALLY (A5/R7) ---
    #
    # This entry replaces an earlier `"OTHER": ()` and the comment that went with
    # it ("OTHER is never matched deterministically -- it is where the classifier
    # lands when it declines to decide"). That was true when OTHER meant only
    # "undecided". E5 also routes a NAMED, KNOWN set of documents here -- bills of
    # lading, e-way bills, customs paperwork, tax certificates, dunning letters --
    # and those are not undecided at all: we know exactly what they are and have
    # decided they are out of v1.
    #
    # Recognising them by title is therefore a real improvement, not a shortcut:
    # an e-way bill quoting its tax-invoice number currently reaches OTHER only
    # via a paid LLM fallback, and one that happens to confuse the model reaches
    # INVOICE instead. Deterministic recognition makes the v1 exclusion free and
    # unambiguous. The distinction OTHER now carries -- "declined to decide"
    # vs "recognised and deferred" -- is visible in `doc_type_method`
    # (`deterministic` here, `fallback` for a genuine miss), which is exactly what
    # that field is for.
    "OTHER": (
        # Transport / custody (E5, research §6.3) -- v2 candidates, EWB first
        "bill of lading",
        "air waybill",
        "airway bill",
        "lorry receipt",
        "bilty",
        "consignment note",
        "e way bill",
        "eway bill",
        "cmr",
        # Customs -- Bill of Entry matters for Indian import ITC (GSTR-2B)
        "shipping bill",
        "bill of entry",
        "cbp 7501",
        # Dunning -- research §5 trap 10: never book these as payables
        "mahnung",
        "zahlungserinnerung",
        "mise en demeure",
        "sollecito",
        "past due notice",
        "final notice",
        # Services fulfilment -- the GRN analogue; promote to QUANTITY if service
        # invoices become a real use case (E5)
        "timesheet",
        "work completion certificate",
        "abnahmeprotokoll",
    ),
}


# How many non-blank lines from the top of the OCR text count as "the title
# band". A printed document states what it is within the first few lines; past
# that, a match is a *mention* (a "Purchase Order No:" reference on an invoice),
# which is not evidence of type.
_TITLE_BAND_LINES = 20

# What fraction of a line's non-space characters the synonym matches must cover
# before that line is treated as a title rather than a body line that happens to
# name a document type. "DELIVERY CHALLAN" scores 1.0; "Purchase Order No:
# PO-2024-1188" scores ~0.5 and is ignored. This is the single guard that stops
# an e-way bill referencing a tax invoice number from classifying as an invoice.
_TITLE_LINE_COVERAGE = 0.6

# E7: below this, the LLM fallback's answer is discarded and the document is
# `OTHER` with the reason recorded.
#
# RECALIBRATED 2026-09-03 (task R11), 0.6 -> 0.75. §2A/N2 recorded 0.6 as an
# explicit PLACEHOLDER chosen before any fixture existed, and required it be
# validated against real measurements before being treated as settled. It now is.
#
# THE MEASUREMENT. Every fixture in `tests/fixtures/doc_types/` was run through
# the real `classify_doc_type()`, twice: once in run 2 (16 fixtures) and once in
# run 3 (24, after A5's four new types were given fixtures). Across both, the
# LLM-fallback path returned exactly six real confidences:
#
#     0.90, 0.92, 0.93, 0.95, 0.95, 0.95        (minimum 0.90)
#
# and NOT ONE observation landed between 0.60 and 0.90. The model is either
# confident or it declines; the band the old threshold sat in is empty.
#
# WHY 0.75 AND NOT 0.90. Picking a value just under the observed minimum would
# be overfitting six points -- the next genuinely-correct-but-harder document
# would be demoted to OTHER by a threshold tuned to a small sample. 0.75 sits
# clear of every observation (a 0.15 margin below the minimum) while being far
# above the old guess, so it rejects a real low-confidence answer without
# demoting anything measured.
#
# WHAT IT CHANGES ON TODAY'S FIXTURES: nothing. All six observations are >= 0.90
# and all 24 fixtures classify identically at 0.6 and at 0.75, so this is not a
# re-baseline dressed as a calibration -- both numbers and the full per-fixture
# table are in `tests/fixtures/doc_types/MANIFEST.md`.
#
# STILL WORTH RE-RUNNING when the fixture set grows: six points is enough to
# retire a placeholder, not enough to call the distribution known.
DOC_TYPE_CONFIDENCE_THRESHOLD = 0.75

# How much of the document the fallback prompt sees. The decision is made from
# the title band and the overall shape; the whole document would cost tokens for
# text that cannot change the answer.
_LLM_TEXT_BUDGET_CHARS = 4000


@dataclass(frozen=True)
class _SynonymMatch:
    doc_type: str
    phrase: str
    start: int
    end: int


def _compile_synonyms() -> List[Tuple[str, str, "re.Pattern[str]"]]:
    """Longest phrase first, so containment (`tax invoice` ⊃ `invoice`) resolves
    to the more specific type rather than to whichever happened to be scanned
    first."""
    compiled: List[Tuple[str, str, "re.Pattern[str]"]] = []
    for doc_type, phrases in _DOC_TYPE_SYNONYMS.items():
        for phrase in phrases:
            pattern = re.compile(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])")
            compiled.append((doc_type, phrase, pattern))
    compiled.sort(key=lambda item: len(item[1]), reverse=True)
    return compiled


_COMPILED_SYNONYMS = _compile_synonyms()


def _normalize(text: str) -> str:
    """Fold to the form `_DOC_TYPE_SYNONYMS` is written in.

    Accents are stripped (so "Albarán" matches `albaran`), `.` and `'` are
    removed rather than spaced (so "D.D.T." matches `ddt`), everything else
    non-alphanumeric becomes a single space.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    without_dots = re.sub(r"[.']", "", without_accents)
    return re.sub(r"[^a-z0-9]+", " ", without_dots.lower()).strip()


def _matches_in(normalized_line: str) -> List[_SynonymMatch]:
    found: List[_SynonymMatch] = []
    for doc_type, phrase, pattern in _COMPILED_SYNONYMS:
        for m in pattern.finditer(normalized_line):
            found.append(_SynonymMatch(doc_type, phrase, m.start(), m.end()))
    return found


def _coverage(normalized_line: str, matches: List[_SynonymMatch]) -> float:
    """Fraction of the line's non-space characters covered by *any* match."""
    total = sum(1 for ch in normalized_line if ch != " ")
    if total == 0:
        return 0.0
    covered = [False] * len(normalized_line)
    for m in matches:
        for i in range(m.start, m.end):
            covered[i] = True
    hit = sum(1 for i, ch in enumerate(normalized_line) if ch != " " and covered[i])
    return hit / total


def _drop_subsumed(matches: List[_SynonymMatch]) -> List[_SynonymMatch]:
    """Drop matches wholly contained in a longer one.

    "PROFORMA INVOICE" matches both `proforma invoice` and `invoice`; the second
    is the first's tail and is not independent evidence of a second document
    type. Without this, every specific invoice sub-case would read as ambiguous.
    """
    kept: List[_SynonymMatch] = []
    for m in matches:
        if any(
            other is not m
            and other.start <= m.start
            and other.end >= m.end
            and (other.end - other.start) > (m.end - m.start)
            for other in matches
        ):
            continue
        kept.append(m)
    return kept


def _title_band_lines(text: str) -> List[str]:
    """The first `_TITLE_BAND_LINES` non-blank lines -- the same band
    `classify_doc_type_deterministic()` scans. Factored out by A8/R10 so the
    ambiguity pre-check looks at exactly the same region the synonym pass does;
    two definitions of "the title" would drift."""
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    return lines[:_TITLE_BAND_LINES]


# ---------------------------------------------------------------------------
# A8 / task R10 — the two pre-checks, the Gutschrift rule, and the rule era
# ---------------------------------------------------------------------------

#: Phrases that mean *this is not a tax document*, in the languages the product
#: targets. Research §5 trap 1(c).
#:
#: A proforma, an order confirmation and a dunning letter all routinely reuse an
#: invoice template -- same layout, same totals block, often the word "Invoice"
#: in the title band. What separates them is not the layout, it is a printed
#: disclaimer that the document itself puts there BECAUSE the layout is
#: misleading. Reading it is the cheapest correct signal available.
_NOT_A_TAX_DOCUMENT_MARKERS: Tuple[str, ...] = (
    "kein vorsteuerabzug",              # DE — no input-tax deduction
    "keine rechnung",                   # DE — not an invoice
    "ne vaut pas facture",              # FR
    "non valido ai fini fiscali",       # IT
    "non e una fattura",                # IT
    "no valido a efectos fiscales",     # ES
    "this is not a tax invoice",
    "not a tax invoice",
    "not a vat invoice",
    "this is not an invoice",
    "proforma - not for itc",
    "not for input tax credit",
    "no input tax credit",
    "for customs purposes only",
)

#: The word that must never resolve deterministically (A8 item 4).
_AMBIGUOUS_TITLE_WORDS: Tuple[str, ...] = ("gutschrift",)

#: India's GST rate rationalisation and the TDS renumbering; the EU e-invoicing
#: go-lives. A document's DATE decides which rules applied to it.
_RULE_ERA_BOUNDARIES: Tuple[Tuple[str, str], ...] = (
    ("2025-09-22", "IN_GST_SLABS_RATIONALISED"),
    ("2026-01-01", "BE_PEPPOL_MANDATORY"),
    ("2026-02-01", "PL_KSEF_LARGE"),
    ("2026-04-01", "IN_TDS_RENUMBERED"),
    ("2026-09-01", "FR_EINVOICE_RECEIVE_ALL"),
)


def has_not_a_tax_document_disclaimer(text: Optional[str]) -> Tuple[bool, str]:
    """Whether the document says outright that it is not a tax document.

    Returns `(hit, phrase)`. A hit VETOES the INVOICE family as a deterministic
    outcome -- it does not choose a replacement, because the disclaimer says what
    the document is *not*, never what it is.
    """
    if not text:
        return False, ""
    haystack = _normalize(text)
    for marker in _NOT_A_TAX_DOCUMENT_MARKERS:
        if _normalize(marker) in haystack:
            return True, marker
    return False, ""


def title_band_is_mandatorily_ambiguous(text: Optional[str]) -> Tuple[bool, str]:
    """A8 item 4: words whose meaning is decided by DIRECTION, not by the word.

    "Gutschrift" is the whole list today. Under UStG §14(2) it is a SELF-BILLING
    INVOICE issued by the customer; in ordinary commercial use it is a credit
    note. BMF 25.10.2013 is explicit that the label alone does not settle it, and
    research §5 trap 2 says classification must key on *issuer direction +
    reference to a prior invoice + sign of VAT*, never on the word.

    So the word is never allowed to resolve deterministically, even when it is
    the only synonym in the title band. It goes to the LLM fallback with
    `direction` supplied, and the fallback's answer is then constrained by the
    rule in `resolve_ambiguous_direction_type()`.
    """
    if not text:
        return False, ""
    for line in _title_band_lines(text):
        normalized = _normalize(line)
        for word in _AMBIGUOUS_TITLE_WORDS:
            if word in normalized:
                return True, line.strip()
    return False, ""


def resolve_ambiguous_direction_type(
    direction: Optional[str], references_original: bool
) -> Optional[str]:
    """The constrained answer for a direction-decided title (A8 item 4).

    Research §3.3, verbatim: classification must key on issuer direction, a
    reference to a prior invoice, and the sign of VAT -- never on the label.

      * issued by the customer or by us, with NO reference to a prior invoice
        -> it is a SELF-BILLED INVOICE, which is an `INVOICE` carrying
        `invoice_subtype = SELF_BILLED`.
      * issued by the supplier AND referencing a prior invoice -> it is a
        commercial `CREDIT_NOTE`.
      * anything else -> `None`, i.e. we still do not know, and the caller keeps
        the model's own low-confidence answer or falls to `OTHER`. Guessing
        between the two would put a payable and a credit on the same footing.
    """
    if direction in ("SELF", "BUYER_ISSUED") and not references_original:
        return "INVOICE"
    if direction == "SUPPLIER_ISSUED" and references_original:
        return "CREDIT_NOTE"
    return None


def derive_rule_era(doc_date: Optional[str]) -> Optional[str]:
    """Which regulatory era a document's DATE places it in (A8 item 5).

    NOT consumed by the classifier -- a document's type does not depend on when
    it was issued. This is a VERIFICATION input: a credit note dated before
    2025-09-22 legitimately carries a GST rate that no longer exists, and a
    rubric that checked it against today's slabs would flag a correct document.
    Research §3.1 is explicit that HSN->rate must never be hard-coded.

    Returns the most recent boundary the date is on or after, or `None` for a
    date before every boundary or one we could not parse. `None` means "no era
    established" and must never be read as "current rules apply".
    """
    if not doc_date:
        return None
    text = str(doc_date).strip()[:10]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", text):
        return None
    era = None
    for boundary, name in _RULE_ERA_BOUNDARIES:
        if text >= boundary:
            era = name
    return era


def classify_doc_type_deterministic(ocr_text: str) -> Tuple[Optional[str], str]:
    """Stage 1 (E7). Title-band synonym match. **Never calls an LLM.**

    Returns `(doc_type, evidence)` where `evidence` is the verbatim printed line
    the decision came from — so a misclassification is reviewable after the fact
    rather than only being a wrong answer.

    Returns `(None, "")` when no line in the title band is a title (no synonym
    matched, or the matches only cover a fraction of the line, i.e. they are
    references in body text). Returns `(None, "<a description of the clash>")`
    when one title line names two different document types ("TAX INVOICE CUM
    DELIVERY NOTE" — a real Indian document): a non-empty evidence string
    alongside a `None` type is how the caller tells "ambiguous" from "nothing
    found", and both route to the LLM fallback.
    """
    if not ocr_text:
        return None, ""

    lines = [line.strip() for line in ocr_text.splitlines() if line.strip()]
    for line in lines[:_TITLE_BAND_LINES]:
        normalized = _normalize(line)
        if not normalized:
            continue
        matches = _matches_in(normalized)
        if not matches:
            continue
        if _coverage(normalized, matches) < _TITLE_LINE_COVERAGE:
            # A body line that mentions a document type, not a title.
            continue
        doc_types = {m.doc_type for m in _drop_subsumed(matches)}
        if len(doc_types) == 1:
            doc_type = doc_types.pop()
            logger.info(
                "Deterministic doc-type match: %s from title line %r", doc_type, line
            )
            return doc_type, line
        return None, (
            f"ambiguous title line {line!r} names "
            f"{', '.join(sorted(doc_types))} — deferring to the model"
        )

    return None, ""


class DocTypeClassification(BaseModel):
    """Stage 2's constrained output (E7).

    `doc_type` is a `Literal` over `DOC_TYPES`, so a value the model invents is a
    pydantic validation error rather than a silently-stored string — the same
    closed-vocabulary discipline the rest of this feature relies on.

    **Every field has a default, deliberately** (§8 trap 2). `MockInvoiceLLM`'s
    `_generate_structured()` fallback is `try: return schema_cls()`, so a model
    with a required field raises inside a `try/except Exception` there and the
    failure presents as a classification *miss* rather than an error. That is the
    same masking that hid the `get_llm(temperature=0)` bug (Gap 367) for as long
    as it did. The defaults are also the fail-closed answer: no opinion, no
    confidence, no evidence.
    """

    # `Literal[DOC_TYPES]` — subscripting with a tuple is equivalent to listing
    # the members, and keeps DOC_TYPES the single source of truth. Static
    # checkers want literals spelled out; correctness here wants one list.
    doc_type: Literal[DOC_TYPES] = Field(  # type: ignore[valid-type]
        "OTHER",
        description=(
            "The document type, from the closed vocabulary. Use OTHER for "
            "anything outside it, including transport documents (bill of "
            "lading, air waybill, e-way bill)."
        ),
    )
    confidence: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="0.0-1.0. Be honest: a low score routes the document to OTHER, which is the safe outcome.",
    )
    evidence: str = Field(
        "",
        description="The verbatim printed phrase the decision was made from, exactly as it appears on the document.",
    )


def _build_classifier_prompt(ocr_text: str) -> str:
    """Render the prompt from `_DOC_TYPE_SYNONYMS` itself, so the model's
    vocabulary and the deterministic map can never drift apart (E4)."""
    lines = [
        "You are classifying a commercial document by its type.",
        "",
        "Choose exactly one value from this closed vocabulary:",
    ]
    for doc_type in DOC_TYPES:
        synonyms = _DOC_TYPE_SYNONYMS.get(doc_type, ())
        if synonyms:
            lines.append(
                f"- {doc_type} — printed as any of: {', '.join(synonyms)} "
                "(and their regional equivalents in other languages)"
            )
        else:
            lines.append(f"- {doc_type}")
    lines += [
        "",
        "Rules:",
        "1. Decide from what the document IS, primarily its printed title, not from what it mentions.",
        "   An invoice that quotes a purchase order number is still an INVOICE.",
        "2. A delivery note / challan / Lieferschein / DDT / bon de livraison / pakbon / albaran",
        "   is DELIVERY_NOTE regardless of the language it is printed in.",
        "3. A proforma invoice is PROFORMA_INVOICE, never INVOICE and never QUOTATION.",
        "4. Tax Invoice, E-Invoice (IRN/QR), Bill of Supply, VAT invoice and commercial invoice",
        "   are all INVOICE — they are sub-cases, not separate types.",
        "5. Transport and custody documents — bill of lading, air waybill, CMR consignment note,",
        "   India's e-way bill — are OTHER. They are deliberately out of scope.",
        "6. If you are not sure, say OTHER and give a low confidence. A wrong type is worse than no type.",
        "7. `evidence` must be a phrase copied verbatim from the document text below. Do not paraphrase it.",
        "",
        "Document text:",
        ocr_text[:_LLM_TEXT_BUDGET_CHARS],
    ]
    return "\n".join(lines)


def _result(
    doc_type: str,
    evidence: str,
    confidence: float,
    method: str,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "doc_type": doc_type,
        "doc_type_evidence": evidence,
        "doc_type_confidence": confidence,
        "doc_type_method": method,
        "doc_type_reason": reason,
    }


def classify_doc_type(
    ocr_text: str,
    ocr_result: Optional[Dict[str, Any]] = None,
    *,
    tenant_id: str = "",
) -> Dict[str, Any]:
    """The two-stage classifier (E7). Returns a dict, never raises.

    Stage 1 is `classify_doc_type_deterministic()` — a title-band synonym match
    that short-circuits with **no LLM call at all** on an unambiguous hit. Stage
    2 runs only when stage 1 found nothing or found a clash, and is one
    `with_structured_output(DocTypeClassification)` call against the closed enum.

    Fails closed to `OTHER` in every uncertain case — below-threshold confidence,
    a validation error on an invented value, or any exception out of the model
    call — always with the reason recorded, so a miss is reviewable rather than
    merely wrong. A guess is never promoted to a type.

    `ocr_result` is the `_run_ocr()` dict; only its `content` is consulted, and
    only as a source for `ocr_text` when the caller passed none. Nothing
    invoice-specific in that dict is read here — `prebuilt-invoice` force-fits
    `VendorName`/`InvoiceTotal` onto a delivery note at low confidence, so those
    fields are confident wrong data for exactly the documents this function
    exists to identify (§8 trap 1).

    `tenant_id` is carried for telemetry attribution only, exactly as
    `ExtractionState["tenant_id"]` is: no classification decision reads it, and
    the answer is identical whether it is present, empty or absent. This flag is
    software-level, never per-tenant (E2).

    Returned keys: `doc_type`, `doc_type_evidence`, `doc_type_confidence`,
    `doc_type_method` (`deterministic` | `llm` | `fallback`) and
    `doc_type_reason` (None unless it fell back).
    """
    text = ocr_text or ""
    if not text.strip() and isinstance(ocr_result, dict):
        text = ocr_result.get("content") or ""

    # --- A8/R10 pre-check 1: a direction-decided title never resolves here ---
    #
    # Checked BEFORE the synonym pass, not after, because "Gutschrift" IS a
    # synonym -- of CREDIT_NOTE in commercial use and of a self-billed INVOICE
    # under UStG §14(2). Letting the deterministic pass see it first would give a
    # confident 1.0 answer to the one word that cannot be answered from the word.
    ambiguous, ambiguous_line = title_band_is_mandatorily_ambiguous(text)

    doc_type, evidence = classify_doc_type_deterministic(text)

    # --- A8/R10 pre-check 2: a printed disclaimer vetoes the INVOICE family ---
    #
    # Research §5 trap 1(c). A proforma, an order confirmation and a dunning
    # letter routinely reuse an invoice template -- and the document itself
    # prints "ne vaut pas facture" / "kein Vorsteuerabzug" precisely BECAUSE the
    # layout misleads. A veto, not a replacement: the disclaimer says what the
    # document is not, never what it is, so the type still has to be established
    # by the fallback rather than guessed at here.
    disclaimed, disclaimer = has_not_a_tax_document_disclaimer(text)
    # The veto is scoped to INVOICE alone, NOT to the money family. A proforma
    # printing "ne vaut pas facture" is not contradicting itself -- a proforma is
    # BY DEFINITION not a tax document, so the disclaimer CONFIRMS the type the
    # title band read. Same for a commercial credit note carrying "no input tax
    # credit", which research §3.1 says is common and is still a credit note.
    # `INVOICE` is the one type the phrase actually contradicts.
    vetoed = disclaimed and doc_type == "INVOICE"

    if doc_type is not None and not ambiguous and not vetoed:
        # Confidence 1.0 is not flattery: a printed title band is a fact, and
        # this branch reports what the document says about itself.
        return _result(doc_type, evidence, 1.0, "deterministic")

    if ambiguous:
        stage_one_reason = "direction_decided_title"
        evidence = ambiguous_line or evidence
    elif vetoed:
        stage_one_reason = "not_a_tax_document_disclaimer"
        evidence = disclaimer
    else:
        stage_one_reason = "ambiguous_title_band" if evidence else "no_title_band_match"

    if not text.strip():
        # No text at all is not an ambiguity a model can resolve; spending a call
        # on it would buy a hallucination.
        return _result("OTHER", "", 0.0, "fallback", "empty_ocr_text")

    try:
        classification = _classify_with_llm(text, tenant_id=tenant_id)
    except ValidationError as e:
        # E7: the `Literal` did its job — an invented doc_type is an error here,
        # not a stored string.
        logger.warning("doc-type fallback returned a value outside the enum: %s", e)
        return _result(
            "OTHER", evidence, 0.0, "fallback", f"validation_error ({stage_one_reason})"
        )
    except Exception as e:  # pragma: no cover - exercised via the narrow test below
        logger.warning("doc-type fallback call failed: %s", e)
        return _result(
            "OTHER", evidence, 0.0, "fallback", f"llm_error ({stage_one_reason}): {e}"
        )

    if classification.confidence < DOC_TYPE_CONFIDENCE_THRESHOLD:
        return _result(
            "OTHER",
            classification.evidence,
            classification.confidence,
            "fallback",
            (
                f"low_confidence {classification.confidence:.2f} < "
                f"{DOC_TYPE_CONFIDENCE_THRESHOLD} — model proposed "
                f"{classification.doc_type} ({stage_one_reason})"
            ),
        )

    return _result(
        classification.doc_type,
        classification.evidence,
        classification.confidence,
        "llm",
    )


def _classify_with_llm(ocr_text: str, *, tenant_id: str = "") -> DocTypeClassification:
    """Stage 2. One structured-output call, one telemetry event.

    The `tracked_llm_call` wrapper is on this path **only**, matching
    `dynamic_qa_node`'s pattern (E7): the deterministic path costs nothing and
    must therefore show as nothing, so `extraction.classify_doc_type` events are
    a direct count of how often the title band was not enough.
    """
    llm = get_llm(max_tokens=512)
    structured_llm = llm.with_structured_output(DocTypeClassification)
    prompt = _build_classifier_prompt(ocr_text)
    with tracked_llm_call(
        "extraction.classify_doc_type",
        llm=llm,
        tenant_id=str(tenant_id or ""),
    ):
        return structured_llm.invoke(prompt)
