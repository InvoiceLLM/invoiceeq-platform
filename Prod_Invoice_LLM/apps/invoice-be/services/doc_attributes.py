"""Classification attributes derived from a document's own text (Feature 27 A6, task R8).

WHAT THIS MODULE IS FOR. Feature 27 E4 keeps `INVOICE` as ONE enum value with
documented sub-cases rather than splitting it, because splitting would fragment
every downstream aggregate across values that all mean "a bill we owe". A6 is how
those sub-cases stop being prose and become data: six attribute groups recorded
per document, on the row rather than in the enum.

They are also how the research's classification traps become answerable:

  * trap 2 -- **direction decides the type, not the title.** A German
    *Gutschrift* is a self-billing invoice under UStG s.14 and a commercial credit
    note in ordinary use; a buyer-issued "credit note" is really a debit claim; an
    RCM self-invoice is issued by the recipient. All three are the same word
    problem, and `direction` is the answer to all three.
  * trap 5 -- **cumulative documents.** "This bill" is not "cumulative" on an RA
    bill, an AIA G702 pay application or an Abschlagsrechnung.
  * trap 8 -- **language is not country.** "Factura rectificativa" (ES) is a
    corrective invoice, "Faktura korygujaca" (PL) is a delta, "Gutschrift" (DE) is
    self-billing. The canonical value plus `correction_method` carries this; the
    local label never does.
  * trap 9 -- **simplified invoices** may legitimately lack buyer name, unit price
    and VAT amount. `invoice_subtype` is what lets the money rubric tolerate that
    without loosening the rubric for everything else.

HARD RULE 3 IS WHY EVERY FUNCTION HERE IS PURE PYTHON. No LLM appears in this
module, and none may be added. These attributes feed rubric selection and, in
Feature 26, comparison-mode selection -- both of which decide how a FIGURE is
judged. A model that decided them would be deciding a financial outcome one step
removed, which is precisely the failure hard rule 3 exists to prevent. Where a
value genuinely cannot be determined from the text, the answer is `None`, never a
guess: `None` means "not determined" and never a default (the Gap 283 discipline).

WHAT LIVES WHERE (A6). Classification-time attributes -- `direction`,
`invoice_subtype`, `correction_method`, `fiscal_markers` -- are a JSON column on
the row (`Invoice.doc_attributes` / `Document.doc_attributes`), NOT fields on the
extraction schemas. That is what keeps A2 true: `InvoiceExtractionSchema` is not
widened by this amendment, so the Gap 31/33/36/43/44/46 faithfulness checks and
the India e-invoicing block are untouched.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Closed vocabularies. Every one of these is a Literal-shaped set: a value not in
# it is a bug, not a new case to accommodate.
# ---------------------------------------------------------------------------

SUPPLIER_ISSUED = "SUPPLIER_ISSUED"
BUYER_ISSUED = "BUYER_ISSUED"
SELF_ISSUED = "SELF"
DIRECTIONS: Tuple[str, ...] = (SUPPLIER_ISSUED, BUYER_ISSUED, SELF_ISSUED)

INVOICE_SUBTYPES: Tuple[str, ...] = (
    "STANDARD",
    "ADVANCE",
    "PARTIAL_PROGRESS",
    "FINAL",
    "SELF_BILLED",
    "SIMPLIFIED",
    "EXPORT",
    "RCM_SELF_INVOICE",
    "ISD",
    "BILL_OF_SUPPLY",
)

DELTA = "DELTA"
SUBSTITUTION = "SUBSTITUTION"
REVERSAL = "REVERSAL"
CORRECTION_METHODS: Tuple[str, ...] = (DELTA, SUBSTITUTION, REVERSAL)

FISCAL_MARKERS: Tuple[str, ...] = (
    "IRN_QR",
    "SDI_ID",
    "KSEF_NO",
    "ATCUD",
    "TSE_SIGNATURE",
    "MYDATA_MARK",
)

# Peppol BIS document type codes (research §3.3). Where a document prints one it
# is the least ambiguous signal available -- it is machine-issued, not a title.
PEPPOL_TYPE_CODES: Dict[str, str] = {
    "380": "INVOICE",
    "381": "CREDIT_NOTE",
    "384": "INVOICE",          # corrected invoice -- still an invoice + correction_method
    "386": "INVOICE",          # prepayment invoice -- ADVANCE subtype
    "389": "INVOICE",          # self-billed invoice -- SELF_BILLED subtype
}


def _norm(text: Optional[str]) -> str:
    """Lower-case, collapse whitespace. Deliberately NOT the classifier's
    `_normalize()`: that folds accents and strips punctuation to match title-band
    synonyms, which would destroy the identifiers this module matches on (a GSTIN
    is case-significant, a Peppol code is punctuation-delimited)."""
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


# ---------------------------------------------------------------------------
# Regional identifiers
#
# CONSERVATIVE BY CONSTRUCTION. Every pattern here is anchored and specific
# enough that a false positive is unlikely, because a wrong tax ID is worse than
# a missing one: `direction` is derived from these, and a spurious match on the
# recipient side would flip a supplier invoice into a self-billed one. Where a
# country's format is genuinely ambiguous against ordinary text (a bare 9-digit
# SIREN, a bare 10-digit NIP), the pattern REQUIRES its labelling keyword.
# ---------------------------------------------------------------------------

_ID_PATTERNS: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    # India: GSTIN is 15 chars with a fixed internal shape -- 2 state digits, a
    # 10-char PAN, an entity digit, 'Z', a checksum. Self-validating enough to
    # match unlabelled.
    ("gstin", re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][A-Z0-9]Z[A-Z0-9]\b")),
    ("pan", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    # IRN: 64 hex chars from the IRP. Nothing else in a document is 64 hex chars.
    ("irn", re.compile(r"\b[0-9a-f]{64}\b", re.I)),
    # EU VAT: two-letter country prefix + 8-12 alphanumerics. Requires the prefix,
    # so it cannot match a bare order number.
    ("vat_id", re.compile(r"\b(?:AT|BE|BG|CY|CZ|DE|DK|EE|EL|ES|FI|FR|HR|HU|IE|IT|"
                          r"LT|LU|LV|MT|NL|PL|PT|RO|SE|SI|SK|XI|GB)[0-9A-Z]{8,12}\b")),
    # US EIN: labelled only. A bare NN-NNNNNNN is far too common.
    ("ein", re.compile(r"\bEIN[:\s#]*(\d{2}-\d{7})\b", re.I)),
    # EORI, KSeF, Leitweg-ID, Codice Destinatario: all labelled in practice.
    ("eori", re.compile(r"\bEORI[:\s#]*([A-Z]{2}[0-9A-Z]{1,15})\b", re.I)),
    ("ksef", re.compile(r"\bKSeF[:\s#]*([0-9A-Z\-]{10,40})\b", re.I)),
    ("leitweg_id", re.compile(r"\bLeitweg[- ]?ID[:\s#]*([0-9A-Z\-]{5,46})\b", re.I)),
    ("codice_destinatario", re.compile(r"\bCodice\s+Destinatario[:\s#]*([0-9A-Z]{6,7})\b", re.I)),
    ("siren", re.compile(r"\bSIREN[:\s#]*(\d{3}\s?\d{3}\s?\d{3})\b", re.I)),
    ("nip", re.compile(r"\bNIP[:\s#]*(\d{10})\b", re.I)),
)


def extract_regional_ids(text: Optional[str]) -> Dict[str, List[str]]:
    """Every regional identifier the document prints, keyed by kind.

    Returns `{}` rather than `None` for "nothing found" -- an empty map is a real
    answer here (plenty of legitimate documents carry no tax ID at all), whereas
    `None` would be indistinguishable from "never looked".

    Values are DEDUPLICATED BUT ORDERED BY FIRST APPEARANCE, which is what makes
    `derive_direction()` below possible: on essentially every commercial layout
    the issuer's own registration is printed before the recipient's.
    """
    if not text:
        return {}
    out: Dict[str, List[str]] = {}
    for kind, pattern in _ID_PATTERNS:
        seen: List[str] = []
        for match in pattern.finditer(text):
            value = (match.group(1) if match.groups() else match.group(0)).strip()
            value = re.sub(r"\s+", "", value)
            if value not in seen:
                seen.append(value)
        if seen:
            out[kind] = seen
    return out


# ---------------------------------------------------------------------------
# direction
# ---------------------------------------------------------------------------

_PRIMARY_ID_KINDS = ("gstin", "vat_id", "nip", "siren", "ein")


def _primary_id_occurrences(text: Optional[str]) -> List[str]:
    """Primary tax IDs in order of appearance, WITHOUT deduplication.

    Deliberately not `extract_regional_ids()`, which dedupes -- and that dedup is
    correct for the stored attribute (a GSTIN repeated in a footer is not two
    registrations) but destroys the one signal `derive_direction` most needs.
    "The same registration appears on BOTH SIDES" is a statement about
    OCCURRENCES, not about the distinct set, and collapsing them makes an RCM
    self-invoice indistinguishable from an ordinary one-party document.

    Found by T-A-1 failing against the first implementation, which reused the
    deduped map and could therefore never return SELF.
    """
    if not text:
        return []
    hits: List[Tuple[int, str]] = []
    for kind, pattern in _ID_PATTERNS:
        if kind not in _PRIMARY_ID_KINDS:
            continue
        for match in pattern.finditer(text):
            value = (match.group(1) if match.groups() else match.group(0)).strip()
            hits.append((match.start(), re.sub(r"\s+", "", value)))
    return [value for _, value in sorted(hits, key=lambda pair: pair[0])]


def derive_direction(
    text: Optional[str],
    *,
    tenant_tax_ids: Optional[Iterable[str]] = None,
) -> Tuple[Optional[str], str]:
    """Who ISSUED this document -- the supplier, the buyer, or the tenant itself.

    Returns `(direction, evidence)`. `direction` is `None` when the text does not
    support a determination, which is the common case and is not a failure: most
    documents carry one tax ID or none, and one ID cannot establish a relationship.

    THE RULE, in order:

      1. **Two or more distinct primary IDs, and they are equal** -> `SELF`. The
         same registration on both sides of a document means the issuer and the
         recipient are the same legal person: an RCM self-invoice (India Rule 47A),
         a German *Gutschrift* in its statutory sense, an ERS/pay-on-receipt
         settlement. This is the single most valuable answer this function gives,
         because it is the one the printed title actively lies about.
      2. **The tenant's own ID appears FIRST** -> `SELF` -- we issued it.
      3. **The tenant's own ID appears, but not first** -> `SUPPLIER_ISSUED`: the
         counterparty issued it to us.
      4. **Two distinct IDs, neither ours** -> `None`. Deliberately not a guess:
         without knowing which side we are on, first-position tells us who issued
         it but not what that means relative to the tenant, and every consumer of
         this field wants the relationship, not the raw fact.

    Never derived from the title. That is trap 2, and honouring it is the entire
    point of the attribute.
    """
    primary = _primary_id_occurrences(text)
    if not primary:
        return None, ""

    ours = {re.sub(r"\s+", "", t).upper() for t in (tenant_tax_ids or []) if t}
    upper = [p.upper() for p in primary]

    distinct = list(dict.fromkeys(upper))
    if len(upper) >= 2 and len(distinct) == 1:
        return SELF_ISSUED, f"the same registration {distinct[0]} appears on both sides"

    if ours:
        present = [p for p in upper if p in ours]
        if present:
            if upper[0] in ours:
                return SELF_ISSUED, f"the tenant's own registration {upper[0]} is the issuer"
            return (
                SUPPLIER_ISSUED,
                f"the tenant's registration {present[0]} appears, but is not the issuer",
            )

    return None, ""


# ---------------------------------------------------------------------------
# fiscal markers
# ---------------------------------------------------------------------------

_MARKER_PATTERNS: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    ("IRN_QR", re.compile(r"\bIRN\b|\bInvoice\s+Reference\s+Number\b", re.I)),
    ("SDI_ID", re.compile(r"\bCodice\s+Destinatario\b|\bSdI\b", re.I)),
    ("KSEF_NO", re.compile(r"\bKSeF\b", re.I)),
    ("ATCUD", re.compile(r"\bATCUD\b", re.I)),
    ("TSE_SIGNATURE", re.compile(r"\bTSE\b.{0,20}\bSignatur\b|\bTSE-Signatur\b", re.I)),
    ("MYDATA_MARK", re.compile(r"\bMARK\b[:\s#]*\d{6,}|\bmyDATA\b", re.I)),
)

_PEPPOL_PATTERN = re.compile(r"\b(?:Peppol|BT-3|type\s*code)\b[^\d]{0,20}(\d{3})\b", re.I)


def extract_fiscal_markers(text: Optional[str]) -> List[str]:
    """The machine-issued fiscal identifiers a document carries.

    These are STRONG EVIDENCE that a document is a real invoice-family document
    (research §5 trap 1(d)) -- an IRN comes from India's IRP, an SDI code from the
    Italian exchange, a KSeF number from the Polish one. A proforma cannot have
    them, because no authority issued one for it.

    Strong evidence, NOT a verdict. A credit note also carries an IRN, and an
    e-way bill quotes the tax invoice's. A8 consumes this as a pre-check that
    biases towards the invoice family; it never decides the type alone.
    """
    if not text:
        return []
    found = [name for name, pattern in _MARKER_PATTERNS if pattern.search(text)]
    peppol = _PEPPOL_PATTERN.search(text)
    if peppol and peppol.group(1) in PEPPOL_TYPE_CODES:
        found.append(f"PEPPOL_TYPE_CODE:{peppol.group(1)}")
    return found


# ---------------------------------------------------------------------------
# correction_method
# ---------------------------------------------------------------------------

_SUBSTITUTION_MARKERS = (
    "por sustitucion", "por sustitución",   # ES -- full replacement
    "rectificativa por sustitucion", "rectificativa por sustitución",
)
_DELTA_MARKERS = (
    "por diferencias",                       # ES -- delta
    "faktura korygujaca", "faktura korygująca",  # PL -- always delta
    "nota di variazione", "td04", "td05",    # IT
    "avoir",                                 # FR
    "net a deduire", "net à déduire",
)
_REVERSAL_MARKERS = (
    "stornorechnung", "storno", "annulla", "annullamento",
    "cancellation invoice", "facture d annulation", "facture d'annulation",
    "korygujaca do zera", "korygująca do zera",
)


def derive_correction_method(text: Optional[str]) -> Tuple[Optional[str], str]:
    """How this note corrects the document it references.

    Returns `(method, evidence)`, or `(None, "")` when the text says nothing.

    The three models are genuinely different arithmetic, which is why this cannot
    be left implicit (research §3.3):

      * `SUBSTITUTION` -- the note REPLACES the original's figures (ES *factura
        rectificativa por sustitución*).
      * `DELTA` -- the note ADJUSTS them (ES *por diferencias*, PL *korygująca*,
        IT *nota di variazione*, FR *avoir*).
      * `REVERSAL` -- the note ZEROES the original (DE *Storno*, a full TD04).

    FOUNDER RULING, carried here so the caller does not have to know it: where
    this returns `None`, Feature 26's comparison runs as `DELTA` **and says so in
    the answer**. An unstated assumption about which of three arithmetics was used
    is exactly the class of silent wrongness this feature exists to remove -- so
    the assumption is stated, not hidden, and this function returning `None` is
    what triggers that statement.

    Ordered SUBSTITUTION -> REVERSAL -> DELTA deliberately: "rectificativa por
    sustitución" contains neither of the others, but a document may print both a
    generic *korygująca* and an explicit *do zera* (correcting to zero), and the
    more specific reading must win.
    """
    if not text:
        return None, ""
    haystack = _norm(text)
    for markers, method in (
        (_SUBSTITUTION_MARKERS, SUBSTITUTION),
        (_REVERSAL_MARKERS, REVERSAL),
        (_DELTA_MARKERS, DELTA),
    ):
        for marker in markers:
            if marker in haystack:
                return method, marker
    return None, ""


# ---------------------------------------------------------------------------
# invoice_subtype
# ---------------------------------------------------------------------------

_SUBTYPE_MARKERS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    # Ordered most-specific first: a Schlussrechnung is also an Abschlagsrechnung's
    # sibling and mentions advances, so FINAL must be tested before ADVANCE.
    ("FINAL", ("schlussrechnung", "final invoice", "facture de solde", "fattura a saldo",
               "factura final", "eindfactuur", "final bill", "retention release")),
    ("ADVANCE", ("anzahlungsrechnung", "advance invoice", "receipt voucher",
                 "facture d acompte", "facture d'acompte", "fattura di acconto",
                 "factura de anticipo", "voorschotfactuur", "prepayment invoice",
                 "proforma advance")),
    ("PARTIAL_PROGRESS", ("ra bill", "running account bill", "teilrechnung",
                          "abschlagsrechnung", "facture de situation", "progress billing",
                          "pay application", "aia g702", "milestone invoice", "deelfactuur")),
    ("RCM_SELF_INVOICE", ("self invoice", "self-invoice", "reverse charge self",
                          "rule 47a", "autofattura", "autofacturation")),
    ("SELF_BILLED", ("self billed", "self-billing", "selfbilling", "gutschrift",
                     "evaluated receipt settlement", "pay on receipt")),
    ("ISD", ("isd invoice", "input service distributor")),
    ("BILL_OF_SUPPLY", ("bill of supply",)),
    ("SIMPLIFIED", ("kleinbetragsrechnung", "facture simplifiee", "facture simplifiée",
                    "fattura semplificata", "factura simplificada", "faktura uproszczona",
                    "simplified invoice", "scontrino")),
    ("EXPORT", ("export invoice", "letter of undertaking", " lut ", "supply meant for export",
                "shipping bill no")),
)


def derive_invoice_subtype(
    text: Optional[str], doc_type: Optional[str] = None
) -> Tuple[Optional[str], str]:
    """Which sub-case of the invoice family this is.

    Returns `(subtype, evidence)`. `None` for a document that is not in the
    INVOICE family at all, and `None` -- not `"STANDARD"` -- when an invoice
    prints no sub-type marker. That distinction is load-bearing: `STANDARD` is a
    positive claim that the document is an ordinary invoice, while `None` means
    "not determined", and the money rubric's expected-absent set must not relax
    itself on the strength of a value nobody established.

    `"gutschrift"` maps to `SELF_BILLED` HERE, which looks like it contradicts
    A8's rule that the word must never resolve deterministically. It does not: A8
    governs the DOCUMENT TYPE (is this an invoice or a credit note?), which stays
    ambiguous and goes to the fallback with `direction` supplied. This function
    answers a narrower question that only arises once the type is already known to
    be INVOICE -- and given that, the German word has exactly one meaning.
    """
    if not text:
        return None, ""
    if doc_type is not None and doc_type not in ("INVOICE", "CREDIT_NOTE", "DEBIT_NOTE",
                                                 "PROFORMA_INVOICE", "RECEIPT"):
        return None, ""
    haystack = _norm(text)
    for subtype, markers in _SUBTYPE_MARKERS:
        for marker in markers:
            if marker in haystack:
                return subtype, marker.strip()
    return None, ""


# ---------------------------------------------------------------------------
# The cumulative block
# ---------------------------------------------------------------------------

_CUMULATIVE_MARKERS = (
    "previously billed", "less previous certificates", "previous certificates",
    "cumulative to date", "completed and stored to date", "total completed",
    "abschlagszahlungen", "bisher berechnet", "acomptes anterieurs",
    "acomptes antérieurs", "gia fatturato", "già fatturato",
    "running account", "ra bill", "retention", "retainage",
)


def looks_cumulative(text: Optional[str]) -> bool:
    """Whether this document reports progress against a larger total.

    Research §5 trap 5: on an RA bill, an AIA G702 pay application, an
    Abschlagsrechnung or a *facture de situation*, "this bill" and "cumulative to
    date" are DIFFERENT NUMBERS, and a verification that conflates them reports a
    discrepancy on a document that is perfectly correct -- the same false-failure
    class the whole feature exists to remove.

    A keyword test, and it only sets a flag. The arithmetic it enables
    (`previous_billed + current_due (+ retention) == cumulative_to_date`) is a
    deterministic check over extracted figures; this function never touches a
    figure itself.
    """
    if not text:
        return False
    haystack = _norm(text)
    return any(marker in haystack for marker in _CUMULATIVE_MARKERS)


# ---------------------------------------------------------------------------
# The single entry point
# ---------------------------------------------------------------------------


def derive_doc_attributes(
    text: Optional[str],
    *,
    doc_type: Optional[str] = None,
    tenant_tax_ids: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Everything A6 derives from the document's own text, in one call.

    Keys are OMITTED when undetermined rather than written as `None`. The column
    is a record of what we established, and a wall of nulls is not the same
    statement -- it reads as "we looked and the answer is nothing", when the truth
    is "the text does not say". Callers use `.get()`.

    Never raises. This runs inside the extraction graph, and a classification
    ENRICHMENT must not be able to fail the extraction it decorates -- the same
    reasoning `classify_doc_type_node` applies to the classifier itself.
    """
    try:
        attributes: Dict[str, Any] = {}

        direction, direction_evidence = derive_direction(text, tenant_tax_ids=tenant_tax_ids)
        if direction:
            attributes["direction"] = direction
            attributes["direction_evidence"] = direction_evidence

        subtype, subtype_evidence = derive_invoice_subtype(text, doc_type)
        if subtype:
            attributes["invoice_subtype"] = subtype
            attributes["invoice_subtype_evidence"] = subtype_evidence

        method, method_evidence = derive_correction_method(text)
        if method:
            attributes["correction_method"] = method
            attributes["correction_method_evidence"] = method_evidence

        markers = extract_fiscal_markers(text)
        if markers:
            attributes["fiscal_markers"] = markers

        ids = extract_regional_ids(text)
        if ids:
            attributes["regional_ids"] = ids

        if looks_cumulative(text):
            attributes["cumulative"] = True

        return attributes
    except Exception as e:  # pragma: no cover - defensive, see docstring
        logger.warning("derive_doc_attributes failed, returning {}: %s", e)
        return {}
