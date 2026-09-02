# Invoice-Adjacent Financial Documents — India, US, EU (research as of 2 Sep 2026)

Purpose: ground the Feature 27 document taxonomy and the Feature 26 chat/comparison design in what real documents look like in the three target regions. Section 6 is the actionable part (what to change in `DOC_TYPES`). Sections 1–5 are the evidence.

Method: three parallel web-research passes (India / US / EU) against primary sources where available (CBIC, GSTN, IRS, FAR, eCFR, EUR-Lex, BMF, DGFiP, Agenzia delle Entrate, AEAT, Peppol/EN 16931), spot-verified on the highest-impact dates. Items marked **(unverified)** were only found in secondary sources.

---

## 1. The document chain (all three regions share the same skeleton)

```
QUOTE/ESTIMATE ─► (PROFORMA) ─► PURCHASE ORDER ─► ORDER CONFIRMATION
      ▲                              │                    │
   CONTRACT / RATE CARD / FRAMEWORK ─┘                    ▼
                                            DELIVERY NOTE / PACKING LIST / TRANSPORT DOC (LR·BOL·CMR·EWB)
                                                          │
                                                          ▼
                                                   GOODS RECEIPT (GRN)
                                                          │
   ADVANCE / PARTIAL / PROGRESS INVOICE ──────────────────▼
                                                       INVOICE ◄── SELF-BILLED INVOICE
                                                          │
                              CREDIT NOTE / DEBIT NOTE / CORRECTIVE / CANCELLATION
                                                          │
                                                          ▼
                              REMITTANCE ADVICE ─► BANK PROOF ─► STATEMENT OF ACCOUNT ─► DUNNING
```

What differs by region is (a) which of these are *legally regulated documents* with mandatory content, (b) naming, and (c) the correction model (how you fix a wrong invoice).

---

## 2. Canonical taxonomy with regional synonyms

Verification family per Feature 27 E4: **M** = money rubric, **Q** = quantity rubric, **MQ** = both/terms-heavy, **A** = advisory only (non-invoice, or money-only but not a payable).

| Canonical type | Family | India labels | US labels | EU labels (DE / FR / IT / ES / NL / PL) | Legally regulated? | AP frequency |
|---|---|---|---|---|---|---|
| QUOTATION | MQ | Quotation, Quote, Estimate, Bhav-patra | Quote, Estimate, Proposal, Bid, Rate Sheet | Angebot, Kostenvoranschlag / Devis / Preventivo / Presupuesto / Offerte / Oferta | No (contract law only) | Med |
| PROFORMA_INVOICE | MQ | Proforma Invoice, PI, Pro-forma | Pro Forma, Preliminary Invoice | Proforma-Rechnung / Facture pro forma / Fattura proforma / Factura proforma / Proforma factuur / Faktura pro forma | No — explicitly *not* an invoice; never VAT/ITC-deductible | Med (imports, prepay) |
| PURCHASE_ORDER | MQ | PO, Work Order, Supply Order | PO, Blanket PO, Release, Contract PO | Bestellung, Auftrag / Bon de commande / Ordine / Pedido / Bestelling, Inkooporder / Zamówienie | No (Peppol Order 3 schema) | High |
| ORDER_CONFIRMATION | MQ | Sales Order, Order Acknowledgement, OA | Order Acknowledgment, Sales Order, PO Ack (EDI 855) | Auftragsbestätigung (AB) / Accusé de réception de commande / Conferma d'ordine / Confirmación de pedido / Orderbevestiging / Potwierdzenie zamówienia | No | High (mfg/wholesale), Med elsewhere |
| CONTRACT | MQ | Agreement, MSA, Rate Contract, ARC, Work Order, LOI | MSA, SOW, Rate Card, Price List | Rahmenvertrag, Abrufauftrag / Contrat-cadre, Marché à bons de commande / Contratto quadro / Acuerdo marco / Raamovereenkomst / Umowa ramowa | Contract law; stamp duty (IN) | Low–Med |
| DELIVERY_NOTE | Q | Delivery Challan, DC, Challan, Dispatch Note, Job Work Challan | Packing Slip, Pack List, Pick Ticket, Delivery Note, Shipping List | Lieferschein / Bon de livraison (BL) / **DDT** (Documento di trasporto) / Albarán / Pakbon / **WZ** / Guia de remessa (PT) | **IN: yes** (Rule 55 particulars incl. taxable value & tax where supply); **IT: yes** (DPR 472/96, needed for deferred invoicing); **PT: yes** (communicated to AT); others no | High |
| PACKING_LIST | Q | Packing List, Case List | Packing List, Shipment Manifest | Packliste / Liste de colisage / Distinta di imballaggio / Lista de embalaje / Paklijst / Lista pakowa | Customs practice | Med |
| TRANSPORT_DOCUMENT | A (v1) | Lorry Receipt / LR / Bilty / Consignment Note, **E-Way Bill**, Bill of Lading, Airway Bill | Bill of Lading (straight/order), Air Waybill, Proof of Delivery, ASN (EDI 856) | CMR-Frachtbrief / Lettre de voiture CMR / Lettera di vettura / Carta de porte / Vrachtbrief / List przewozowy | IN: Carriage by Road Act s.9, Rule 138 (EWB); US: 49 USC ch.801; EU: CMR Convention | Med–High (goods) |
| GRN | Q | GRN, MRN, MRR, Inward Gate Entry, SES (services) | Receiving Report, Receiver, Goods Receipt, WAWF RR (federal) | Wareneingangsschein / Bon de réception / Ricevimento merci / Nota de recepción / Ontvangstbon / PZ | Internal control only | Very high (internal) |
| INVOICE | M | Tax Invoice, Invoice, Bill, GST Invoice, Bijak, Cash Memo, Bill of Supply, Export Invoice | Invoice, Bill, Sales Invoice, Service Invoice, Utility Bill | Rechnung / Facture / Fattura / Factura / Factuur / Faktura (VAT) | **Yes everywhere except US** (IN Rule 46; EU Art. 226; US none federal) | Very high |
| INVOICE — subtype ADVANCE | M | Receipt Voucher (Rule 50; services only) | Deposit invoice, Prepayment invoice | Anzahlungsrechnung / Facture d'acompte / Fattura di acconto (TD02) / Factura de anticipo / Voorschotfactuur / Faktura zaliczkowa | IN Rule 50; EU Art. 65, 220(1)(4) | Med |
| INVOICE — subtype PARTIAL/PROGRESS | M | RA Bill, Running Account Bill, IPC, Milestone Invoice | Pay Application, AIA G702/G703, Progress Billing, Draw Request, Milestone Invoice | Teilrechnung, Abschlagsrechnung / Facture de situation / SAL, Fattura parziale / Factura parcial / Deelfactuur / Faktura częściowa | Same as invoice; cumulative fields | Med (construction/EPC) |
| INVOICE — subtype FINAL | M | Final bill, Retention release bill | Final invoice, Retainage release | Schlussrechnung / Facture de solde / Fattura a saldo / Factura final / Eindfactuur / Faktura końcowa | DE §14(5): **must net prior advances** | Med |
| INVOICE — subtype SELF_BILLED | M | Self-invoice (RCM, Rule 47A, s.31(3)(f)), Payment Voucher (Rule 52), ISD Invoice | ERS / Pay-on-receipt statement, Consignment sell-through | **Gutschrift** (§14(2) UStG — see trap) / Autofacturation / Autofattura (TD16–19, different concept) / Autofactura / Self-billing factuur / Samofakturowanie | IN Rule 46/47A; EU Art. 224 + "Self-billing" mention | Med |
| INVOICE — subtype SIMPLIFIED/RECEIPT | M | B2C invoice < ₹200 consolidated; Cash Memo | Receipt, Register Receipt, Expense Receipt | Kleinbetragsrechnung (≤ €250) / Facture simplifiée / Fattura semplificata (≤ €400), Scontrino / Factura simplificada, Ticket / Faktura uproszczona (≤ PLN 450) | EU Art. 220a, 226b, 238 | High (expenses) |
| CREDIT_NOTE | M | Credit Note, CN, Credit Memo, Sales Return, Jama Note, Commercial/Financial CN (no GST) | Credit Memo, Credit Note, Credit Invoice, RMA Credit (EDI 812) | Rechnungskorrektur, Stornorechnung, (kaufmännische) Gutschrift / Avoir / Nota di credito (TD04) / **Factura rectificativa** / Creditnota / **Faktura korygująca** | IN s.34 + IMS flow; EU Art. 219, 90 | High |
| DEBIT_NOTE | M | Debit Note, DN, Supplementary Invoice, Naame Note; buyer-side claim DN (no GST) | Debit Memo, Chargeback, Deduction Notice, Short-pay | Belastungsanzeige / Note de débit / Nota di debito (TD05) / Factura rectificativa (in plus) / Debetnota / Faktura korygująca (in plus) | IN s.34; EU Art. 219 | Med (High in retail/CPG US) |
| CORRECTIVE_INVOICE | M | Revised Invoice (Rule 53(1), rare) | Corrected invoice, Re-bill | Rechnungskorrektur / Facture rectificative / Nota di variazione / **Factura rectificativa (series R, "por sustitución" or "por diferencias")** / Correctiefactuur / Faktura korygująca | EU Art. 219; ES RD 1619/2012 Art. 15; PL art. 106j | Med (EU), rare elsewhere |
| CANCELLATION_INVOICE | M | IRN cancellation (24h) then CN | Void / reversal | Stornorechnung / Facture d'annulation / Storno TD04 / Rectificativa por sustitución / Annuleringsfactuur / Korygująca do zera | EU Art. 219 | Med |
| REMITTANCE_ADVICE | A | Payment Advice, Remittance Advice, Bhugtan vivaran (shows TDS, GST-TDS deductions, UTR) | Remittance Advice, Check Stub, EFT Advice, ACH CTX/CCD+ addenda (EDI 820) | Zahlungsavis / Avis de paiement / Avviso di pagamento / Aviso de pago / Betalingsspecificatie / Awizo płatności | No; ISO 20022 remt.001 | High |
| STATEMENT_OF_ACCOUNT | A | SOA, Ledger, Khata, Balance Confirmation, Vendor Reconciliation Statement | Vendor Statement, Account Statement, Aging Statement, Open Items | Kontoauszug, Saldenbestätigung / Relevé de compte / Estratto conto / Extracto de cuenta / Rekeningoverzicht / Potwierdzenie salda | No (SA 505 confirmations) | High (monthly) |
| DUNNING | A | Reminder, Demand letter | Past-due Notice, Collection Letter, Final Notice | Mahnung, Zahlungserinnerung / Lettre de relance, Mise en demeure / Sollecito / Reclamación de pago / Aanmaning / Wezwanie do zapłaty | EU Dir. 2011/7/EU (interest ECB+8pp, €40 fee) | Med |
| PAYMENT_PROOF | A | UTR, Bank advice, Bank statement line | Cancelled check, ACH trace, Bank statement | Quittung / Reçu, Quittance / Quietanza / Recibo / Kwitantie / Pokwitowanie; camt.053/054 | RBI/NACHA/SEPA | High |
| RETURN_NOTE / RMA | Q | Return challan, Rejection note | RMA, RGA, Return Authorization | Rücksendeschein, RMA / Bon de retour / Reso (DDT causale "reso") / Albarán de devolución / Retourbon / Korekta WZ | No | Med |
| CUSTOMS_DOCUMENT | A (v1) | Shipping Bill (s.50), Bill of Entry (s.46) — BoE auto-populates GSTR-2B ITC | Commercial Invoice for customs (19 CFR 141.86), CBP 7501 Entry Summary, Broker invoice | SAD / DAU / DUA / Einheitspapier; import VAT statement; MRN, EORI | Customs Acts / UCC | Low–Med |
| TAX_CERTIFICATE | A (v1) | Form 16A (TDS), GSTR-7A (GST-TDS), Form 27D (TCS) | W-9, 1099-NEC/MISC/K, Resale/Exemption Certificate, SST Certificate | (no direct analog; VAT ID confirmation letters) | IT Act / IRC / state law | Low–Med |
| TIMESHEET / COMPLETION_CERT | Q | Timesheet, Work Completion Certificate, Commissioning Report, Measurement Book | Timesheet, Acceptance Certificate, Milestone sign-off, Lien Waiver (construction) | Stundenzettel, Abnahmeprotokoll / Feuille de temps, PV de réception / Foglio ore, Verbale di collaudo / Parte de horas, Acta de recepción | No (contractual); IN s.13 time of supply | Med (services) |
| OTHER | A | Hundi, LC document set, COI, consignment reports | COI (ACORD 25), LC docs, Rebate/Co-op claims, Consignment reports | LC docs, Konsignationsvertrag, Direct-debit mandate, Intrastat/ECSL returns | — | Rare |

---

## 3. Region-specific facts that affect extraction and verification

### 3.1 India
- **E-invoicing**: mandatory for AATO > ₹5 crore (any FY since 2017-18). No 2026 threshold cut found. AATO ≥ ₹10 crore must report to IRP within **30 days** of document date (since 1 Apr 2025). IRN = 64-char SHA-256; signed QR carries supplier/recipient GSTIN, doc no/date, total value, line count, main HSN, IRN. IRN cancellation only within 24h, else credit note.
- **Rule 46 tax-invoice particulars** (serial ≤16 chars, alphanumeric + "-" "/", unique per FY; supplier/recipient GSTIN; HSN/SAC; qty + UQC; taxable value; rate & amount per CGST/SGST/IGST/UTGST/cess; place of supply + state for inter-state; RCM flag; QR/IRN where applicable; export endorsement text under LUT / with IGST).
- **Delivery Challan (Rule 55)** is legally a *priced* document when goods move for supply: taxable value + tax rate/amount required; qty may be provisional. Triplicate marking (Consignee/Transporter/Consigner). Must be declared in E-Way Bill. → the quantity rubric must still accept prices when present and not treat absent prices as an error.
- **E-Way Bill** carries value + tax breakup, so it's a reconciling artefact (EWB ↔ invoice ↔ GSTR-1). Validity 1 day/200 km; not generatable for docs > 180 days old; extension cap 360 days.
- **Correction model**: supplier-issued CN/DN under s.34 only; from **1 Oct 2025** supplier can reduce liability only if recipient reversed ITC (IMS accept/reject/pending). Financial/commercial credit notes without GST are common and must be distinguished from s.34 CNs.
- **Self-invoice under RCM**: issuer = recipient (same GSTIN as buyer); must be issued within 30 days (Rule 47A, since 1 Nov 2024). Payment Voucher (Rule 52) is a separate money-only document.
- **Rate era boundary 22 Sep 2025**: GST slabs rationalised to 5 / 18 / 40%. Same HSN can legitimately carry different rates before/after; CNs for old invoices carry the old rate. Never hard-code HSN→rate.
- **ISD mandatory** from 1 Apr 2025 → ISD invoices (tax amounts only, no taxable value/HSN) will appear at branches.
- **Income-tax Act 2025** applies from 1 Apr 2026: TDS sections renumbered (194C/194J/194Q → s.393). Remittance advices show TDS + GST-TDS (s.51) deductions.
- **Numbering**: every GST series (invoice, BoS, CN, DN, RV, PV, DC, ISD) ≤16 chars, unique per FY; multiple series allowed.

### 3.2 United States
- **No federal invoice-content law.** What exists: IRS Pub 583 (invoices as supporting records), state sales-tax rules (tax must be *separately stated*; exemption/resale certificates), UCC Art. 2 (PO = offer; §2-207 battle of forms), 19 CFR 141.86 (customs commercial invoice), FAR 52.232-25 "proper invoice" (federal payees only).
- **Fields are convention**, set by AP departments and EDI trading-partner guides: remit-to (fraud-control critical), PO#, terms (2/10 Net 30), EIN, sales tax by jurisdiction, ship-to vs bill-to (drives tax situs), BOL/PRO/tracking#.
- **Packing Slip** is the canonical no-price document (qty only). **Receiving Report** is the 3rd leg; **ERS / pay-on-receipt** eliminates the invoice entirely (payable = GR × PO price).
- **Correction model**: Credit Memo (seller) / Debit Memo or Chargeback (buyer). Retail/CPG deductions (OTIF, ASN compliance) arrive via EDI 820 adjustment codes — high volume, always disputed with POD/BOL evidence.
- **Construction**: AIA G702/G703 pay apps carry cumulative fields (Original Contract Sum, Net Change by COs, Completed & Stored to Date, Retainage, Less Previous Certificates, Current Payment Due). Retainage caps vary by state (CA private 5% from 1 Jan 2026). Lien waivers (12 states with statutory forms) gate payment.
- **EDI**: 850 PO, 855 ack, 856 ASN, 810 invoice, 812 credit/debit, 820 remittance, 861 receiving advice, 210 freight invoice; grocery uses 875/880.
- **E-invoicing**: no federal/state mandate; DBNAlliance runs a voluntary Peppol-style 4-corner network; federal payees use Treasury IPP and DoD WAWF.
- **1099**: NEC/MISC threshold **$2,000** for payments after 31 Dec 2025 (OBBBA), indexed from 2027; 1099-K back to $20,000 & 200 txns. W-9 rev. 3/2024 (line 3b).

### 3.3 European Union (+UK)
- **Art. 226 VAT Directive** mandatory items (1–15): issue date; sequential number; supplier VAT ID; customer VAT ID (reverse charge / intra-EU); names & addresses; qty & nature; supply date if different; "Cash accounting"; taxable amount per rate + unit price + discounts; VAT rate; VAT amount in national currency; "Self-billing"; exemption reference; "Reverse charge"; margin-scheme mentions; tax-representative details. Signatures cannot be required (Art. 229).
- **Simplified invoices** (Art. 220a/226b/238): ≤ €100 by right, up to €400 by consultation; no customer name, no unit price; VAT amount *or* data to compute it. National: DE €250, IT €400, ES €400 (€3,000 some sectors), NL €100, PL PLN 450, FR €150 HT, PT €100/€1,000 **(verify before hard-coding)**.
- **Art. 219**: any document that amends and refers unambiguously to an invoice *is* an invoice → credit/debit/corrective notes must carry Art. 226 (or 226b) content + original invoice reference.
- **The German "Gutschrift" trap**: in §14 UStG, *Gutschrift* legally means a **self-billing invoice issued by the customer**. A commercial credit note is a *Rechnungskorrektur / Stornorechnung*. BMF 25.10.2013 says the label alone doesn't trigger §14c, but classification must key on **issuer direction + reference to prior invoice + sign of VAT**, never on the word. Peppol type codes: 380 invoice, 381 credit note, 384 corrected, 386 prepayment, 389 self-billed.
- **Correction models differ per country** — the reconciliation engine needs `correction_method ∈ {delta, substitution, reversal}`:
  - ES: no credit-note concept; everything is *factura rectificativa* (own series "R"), either *por sustitución* (full replacement) or *por diferencias* (delta).
  - PL: *faktura korygująca* always delta, must cite KSeF number of original.
  - IT: *nota di variazione* TD04 (down) / TD05 (up) via SDI; storno = TD04 in full.
  - DE: Storno + new invoice (reversal), or Rechnungskorrektur.
  - FR: *avoir* mandatory to reduce VAT; "Net à déduire".
- **Advance/final chain**: Art. 65 VAT due on payment on account; DE §14(5) Schlussrechnung **must list and deduct** prior Anzahlungsrechnungen or §14c double-VAT arises.
- **Delivery notes**: IT **DDT** (DPR 472/96) is legally required for deferred invoicing (TD24 must cite DDT numbers); PT *guia de transporte* must be pre-communicated to AT; DE Lieferschein doubles as intra-EU proof (Gelangensbestätigung, §17a–c UStDV); signed **CMR** is Art. 45a evidence for zero-rated intra-EU supply.
- **National mandatory extras**: DE Leistungsdatum, Steuernummer/USt-IdNr, Leitweg-ID (B2G); FR SIREN both parties, delivery address, nature of operation, penalty rate, **€40 recovery indemnity**, escompte terms, RCS + capital; IT Codice Destinatario, Codice Fiscale, bollo €2, CIG/CUP for PA, split payment; ES NIF, series; PL NIP both, KSeF number, split-payment mention; BE enterprise number = VAT number.
- **Late Payment Directive 2011/7/EU**: B2B 30 days default / 60 max; interest ECB + 8pp; €40 fixed fee. Dunning letters list open invoices + interest — must never be ingested as invoices.
- **E-invoicing timeline (verified on the big ones)**:
  - IT: SDI since 2019 (FatturaPA XML, TD01–TD28 codes).
  - FR: **1 Sep 2026** all must receive; large + ETI must issue; **1 Sep 2027** SMEs issue. Factur-X / UBL / CII via Plateformes Agréées.
  - DE: receive since 1 Jan 2025; issue **1 Jan 2027** (> €800k) / **1 Jan 2028** all. XRechnung / ZUGFeRD ≥ 2.0.1. Exempt: B2C, ≤ €250, Kleinunternehmer.
  - PL: KSeF **1 Feb 2026** (> PLN 200m) / **1 Apr 2026** all; penalties 2027.
  - BE: **1 Jan 2026** B2B Peppol mandatory.
  - ES: Verifactu 1 Jan 2027 / 1 Jul 2027; Crea y Crece B2B realistically 2027–28 **(unverified)**; Basque TicketBAI live.
  - HR 1 Jan 2026; RO since Jul 2024; GR Mar/Oct 2026; PT PDF accepted to 31 Dec 2026; NL B2B planned 2030.
  - **ViDA** (Dir. 2025/516, in force 14 Apr 2025): 1 Jul 2030 structured e-invoice mandatory for intra-EU B2B, 10-day issuance, ECSL abolished, new mandatory fields (IBAN, due date, corrected-invoice reference). Plan schema now.
  - UK: VAT Regs reg. 14 (mirrors Art. 226 + unit price); MTD; **B2B e-invoicing mandate announced for April 2029** (Peppol).
- **EN 16931 / Peppol BIS**: UBL 2.1 and CII syntaxes; BT-1 number, BT-3 type code, BT-10 buyer reference (Leitweg-ID), BT-13 PO, BT-16 despatch advice, BT-31/48 VAT IDs, BT-84 IBAN, BG-23 VAT breakdown. Peppol post-award docs: Order, Order Response, Despatch Advice, Receipt Advice, Catalogue, Invoice Response (status codes).

---

## 4. Matching / reconciliation roles (what each document is *for* in a 3-way world)

| Leg | India | US | EU |
|---|---|---|---|
| Commitment (price) | PO / Work Order / Rate Contract | PO / Blanket PO / SOW | PO / Order confirmation (often the better price ref) / Framework |
| Fulfilment (qty) | Delivery Challan + E-Way Bill + LR; GRN | Packing Slip + BOL/POD; Receiving Report | Lieferschein/DDT/Albarán + CMR; Wareneingang |
| Claim (money) | Tax Invoice (IRN) | Invoice | Invoice (Art. 226 / EN 16931) |
| Adjustment | s.34 CN/DN (+ IMS action) | Credit/Debit Memo, Chargeback | Credit note / rectificativa / korygująca / nota di variazione |
| Settlement | Remittance advice (TDS, GST-TDS), UTR | Remittance (820 / CTX addenda), check | Zahlungsavis, camt.054, RF reference |
| Reconciliation | Vendor ledger reco, GSTR-2B/IMS, Form 26AS | Vendor statement recon, 1099 | Statement of account, Saldenbestätigung, ECSL/Intrastat |

Services replace the fulfilment leg with **timesheets / completion certificates / SES**; construction replaces it with **measurement books / SOV + retention**.

---

## 5. Classification traps (cross-region)

1. **Look-alikes**: proforma, quotation, order confirmation, delivery note, dunning letter, statement and remittance advice all mimic invoice layouts. Decide by (a) title in any language, (b) presence of a *sequential* invoice number + VAT/GST breakdown, (c) disclaimers ("kein Vorsteuerabzug", "ne vaut pas facture", "non valido ai fini fiscali", "Proforma – not for ITC"), (d) fiscal identifiers only real invoices carry (IRN/QR, SDI ID, KSeF no., ATCUD, TSE signature, myDATA MARK).
2. **Direction decides the type**, not the title: same GSTIN/VAT-ID as issuer and recipient → self-invoice; buyer-issued "credit note" → actually a debit claim; German "Gutschrift" → self-billing unless it references a prior invoice.
3. **Absent prices are normal** on delivery notes, packing lists, GRNs, timesheets — but India's Rule 55 challan *does* carry taxable value when goods move for supply. Quantity rubric must accept both.
4. **Missing grand total is normal** on contracts, rate cards, framework agreements, statements (running balance instead), dunning letters.
5. **Cumulative documents** (RA bills, AIA G702, Abschlagsrechnung, facture de situation): "this bill" ≠ "cumulative"; verification must compare *previous + this = cumulative* and deduct retention/advances.
6. **Money-only, no lines**: receipt voucher, payment voucher, ISD invoice, remittance advice, statement. Line-item math is not applicable.
7. **Rate/era boundaries**: IN 22 Sep 2025 GST slabs; IN 1 Apr 2026 TDS section renumbering; EU national e-invoice go-lives — a document's *date* changes which rules apply.
8. **Language ≠ country**: "Factura rectificativa" (ES) is a *corrective invoice*, "Faktura korygująca" (PL) is *delta*, "Gutschrift" (DE) is *self-billing*. Canonical value + `correction_method` attribute, never the local label.
9. **Simplified invoices** may lack customer name, unit price, and VAT amount (rate only). Do not flag missing buyer as an error.
10. **Statements and dunning letters** must never be booked as payables; they are reconciliation inputs.

---

## 6. What this means for Feature 27's `DOC_TYPES`

Current (E4): `QUOTATION, PROFORMA_INVOICE, PURCHASE_ORDER, CONTRACT, DELIVERY_NOTE, GRN, INVOICE, CREDIT_NOTE, DEBIT_NOTE, OTHER`.

**Verdict: the 10-value enum is a sound *core* but under-represents the documents users will actually attach in chat.** Proposed changes, ordered by value:

### 6.1 Add (high frequency in all three regions, distinct rubric)
| Add | Family | Why |
|---|---|---|
| `ORDER_CONFIRMATION` | MQ | Very common in DE/IT/NL mfg (Auftragsbestätigung); often the *real* agreed price, not the PO. Distinct from PO by direction (seller→buyer). |
| `STATEMENT_OF_ACCOUNT` | A | Monthly in all regions; highest-value non-invoice for "which of these invoices are missing/unpaid?" questions; must never be treated as a payable. |
| `REMITTANCE_ADVICE` | A | Carries invoice-level allocations + deductions (TDS, chargebacks, Skonto); the natural doc for "what did they short-pay?" |
| `RECEIPT` (payment receipt / simplified invoice / fiscal receipt) | M (relaxed) | Expenses; lacks buyer/unit price by law; needs its own relaxed rubric. |

### 6.2 Add as attributes on INVOICE / CREDIT_NOTE rather than new enum values
- `invoice_subtype ∈ {STANDARD, ADVANCE, PARTIAL_PROGRESS, FINAL, SELF_BILLED, SIMPLIFIED, EXPORT, RCM_SELF_INVOICE, ISD, BILL_OF_SUPPLY}` — same money rubric, different *expected-missing* fields (e.g. FINAL must reference advances; ISD has no HSN; BILL_OF_SUPPLY has no tax).
- `correction_method ∈ {DELTA, SUBSTITUTION, REVERSAL}` + `references_original: [doc_no]` on CREDIT_NOTE / DEBIT_NOTE / CORRECTIVE.
- `direction ∈ {SUPPLIER_ISSUED, BUYER_ISSUED, SELF}` — derived from issuer vs recipient tax IDs; this is what disambiguates Gutschrift, buyer debit notes, RCM self-invoices.
- `cumulative: bool` + `previous_billed`, `retention`, `advance_adjusted` for progress billing.

### 6.3 Fold or keep as OTHER in v1 (state explicitly in E5)
- `TRANSPORT_DOCUMENT` (LR/Bilty, E-Way Bill, BOL, AWB, CMR) → OTHER in v1 as already decided, but **India E-Way Bill deserves a note**: it carries value + tax and is a common attachment; users will ask "does the EWB match the invoice?". Candidate for v2 as its own type with a money+qty rubric.
- `CUSTOMS_DOCUMENT` (Shipping Bill, Bill of Entry, CBP 7501, SAD) → OTHER v1; BoE matters for Indian import ITC (auto-populates GSTR-2B). v2 candidate.
- `TAX_CERTIFICATE` (Form 16A, W-9, 1099, exemption certificates) → OTHER v1.
- `TIMESHEET / COMPLETION_CERTIFICATE` → OTHER v1, but it's the services equivalent of GRN; if service invoices are a real use case, promote to Q family.
- `PACKING_LIST` → fold into `DELIVERY_NOTE` (same Q rubric) with a `has_prices=false` expectation; don't add a type.
- `CORRECTIVE_INVOICE` / `CANCELLATION` → fold into CREDIT_NOTE/DEBIT_NOTE with `correction_method`; add a separate type only if ES/PL volume justifies it.

### 6.4 Rubric adjustments E4/E6 should absorb
- Quantity family: **prices optional, but if present run money checks additionally** (India Rule 55 challan carries tax). Already stated in E4 — keep.
- Contract/PO family: **no grand total is normal**; **validity/delivery-schedule fields matter more than totals**.
- New A family (advisory / non-payable): STATEMENT, REMITTANCE, DUNNING, PAYMENT_PROOF — never set a review status, never enter spend, but *are* comparable against invoice rows by invoice number. This is a different comparison mode: **list reconciliation** (which referenced invoice numbers exist / are paid), not line-item diff. Feature 26's `compare_documents()` should get `mode=list_reconcile`.
- Simplified/receipt: buyer name, unit price, VAT amount may legitimately be absent.

### 6.5 Synonym table additions for the deterministic classifier (E7)
Beyond E4's DELIVERY_NOTE table: PROFORMA ("Pro forma", "Proforma-Rechnung", "Facture pro forma", "Fattura proforma", "Factura proforma"); ORDER_CONFIRMATION ("Auftragsbestätigung", "AB", "Order Acknowledgment", "Conferma d'ordine", "Confirmación de pedido", "Orderbevestiging", "Sales Order", "OA"); CREDIT_NOTE ("Avoir", "Nota di credito", "Factura rectificativa", "Faktura korygująca", "Creditnota", "Credit Memo", "Jama"); STATEMENT ("Statement of Account", "Kontoauszug", "Relevé de compte", "Estratto conto", "Extracto de cuenta", "Ledger", "Khata", "Balance Confirmation"); REMITTANCE ("Remittance Advice", "Payment Advice", "Zahlungsavis", "Avis de paiement", "Avviso di pagamento"); DUNNING ("Mahnung", "Zahlungserinnerung", "Relance", "Mise en demeure", "Sollecito", "Past Due", "Reminder"); INDIA specifics ("Bijak", "Bill of Supply", "Receipt Voucher", "Payment Voucher", "Self Invoice", "ISD Invoice", "RA Bill", "E-Way Bill", "Lorry Receipt", "Bilty"); US specifics ("Pay Application", "AIA G702", "Packing Slip", "Pick Ticket", "Chargeback", "Deduction"). **"Gutschrift" must map to AMBIGUOUS → LLM fallback with direction check, never deterministically to CREDIT_NOTE.**

### 6.6 Fixture set (§7 of Feature 27) — add cells
ORDER_CONFIRMATION (DE, IT), STATEMENT_OF_ACCOUNT (IN, US, DE), REMITTANCE_ADVICE (IN with TDS, US with deductions), simplified receipts (DE Kleinbetragsrechnung, ES ticket, IT scontrino), a DE "Gutschrift" of *each* meaning, an ES factura rectificativa por sustitución, an Indian Rule 55 challan *with* tax, an Indian RA bill, a US AIA G702, an E-Way Bill and a Bill of Entry (to prove OTHER routing).

---

## 7. Things still unverified (check before encoding as rules)
- EU simplified-invoice thresholds per country (secondary sources only).
- Spain Crea y Crece B2B final go-live dates.
- ViDA DRR reporting window (5 days?) and Late Payment Regulation status.
- Income-tax Act 2025 form numbering (Form 16A retained?).
- Carriage by Road Rules 2011 rule number for LR contents.
- US state retainage figures (drawn from summaries).

---

## 8. Key sources
India: [CBIC Rule 46](https://taxinformation.cbic.gov.in/content/html/tax_repository/gst/rules/cgst_rules/active/chapter6/rule46_v1.00.html) · [ClearTax CGST Rules ch. VI](https://cleartax.in/s/cgst-rules-chapter-6-tax-invoice-credit-and-debit-notes) · [ICAI Handbook on Invoicing (Jun 2025)](https://d23z1tp9il9etb.cloudfront.net/download/pdf25/Handbook_on_Invoicing_under_GST17-06-2025.pdf) · [IRP mandatory fields](https://einvoice6.gst.gov.in/content/e-invoice-printing-process-mandatory-fields-modes-of-irn-generation/) · [GSTN 30-day advisory](https://taxreply.com/gst/Taxpayers_with_turnover_of_10_Crores_and_above_to_report_e-Invoices_on_IRP_Portal_within_30_days_w_e_f__01_April_2025__GSTN_Advisory-1534.html) · [56th GST Council press release](https://gstcouncil.gov.in/sites/default/files/2025-09/press_release_press_information_bureau_0.pdf) · [Finance Act 2025 GST amendments](https://dpncglobal.com/recent-gst-amendments-effective-1st-october-2025-notifications-advisories/) · [IMS changes Oct 2025](https://a2ztaxcorp.net/major-changes-in-gst-invoice-management-system-ims-from-october-2025-tax-period/) · [Rule 47A](https://www.taxtmi.com/article/detailed?id=13066) · [E-way bill limits](https://cleartax.in/s/time-limit-for-e-way-bill-generation) · [E-invoice limit 2026](https://getswipe.in/blog/article/e-invoice-turnover-limit-2026-5-crore-rule-india)

US: [IRS Pub 583](https://www.irs.gov/publications/p583) · [FAR 52.232-25](https://www.acquisition.gov/far/52.232-25) · [5 CFR 1315](https://www.ecfr.gov/current/title-5/chapter-III/subchapter-B/part-1315) · [UCC §2-201](https://www.law.cornell.edu/ucc/2/2-201) · [49 USC §80101](https://www.law.cornell.edu/uscode/text/49/80101) · [19 CFR 141.86](https://www.law.cornell.edu/cfr/text/19/141.86) · [CBP 7501](https://www.cbp.gov/sites/default/files/2026-02/cbp_form_7501.pdf) · [IRS 1099-K FAQ](https://www.irs.gov/newsroom/form-1099-k-faqs) · [Avalara OBBBA 1099](https://www.avalara.com/blog/en/north-america/2025/07/one-big-beautiful-bill-act-1099-reporting-threshold.html) · [DBNAlliance](https://dbnalliance.org/) · [IOFM ERS](https://www.iofm.com/ap/process-improvement/payment/evaluated-receipt-settlement-ers) · [AIA G702](https://help.aiacontracts.com/hc/en-us/articles/1500009308242-Instructions-G702-1992-Application-and-Certificate-for-Payment) · [CA SB 61 retention](https://www.buchalter.com/insights/effective-january-1-2026-california-sb-61-caps-retention-at-5-on-private-construction-projects/) · [MTC exemption certificate](https://www.mtc.gov/resources/faq-uniform-sales-and-use-tax-certificate/)

EU: [VAT Directive 2006/112/EC](https://eur-lex.europa.eu/eli/dir/2006/112/oj) · [ViDA Dir. 2025/516](https://eur-lex.europa.eu/eli/dir/2025/516/oj) · [Late Payment Dir. 2011/7/EU](https://eur-lex.europa.eu/eli/dir/2011/7/oj) · [Impl. Reg. 282/2011 Art. 45a](https://eur-lex.europa.eu/eli/reg_impl/2011/282/oj) · [CMR Convention](https://unece.org/transport/documents/2021/06/cmr-convention) · [UStG §14](https://www.gesetze-im-internet.de/ustg_1980/__14.html) · [BMF E-Rechnung FAQ](https://www.bundesfinanzministerium.de/Content/DE/FAQ/e-rechnung.html) · [EC eInvoicing Germany](https://ec.europa.eu/digital-building-blocks/sites/spaces/DIGITAL/pages/467108886/eInvoicing+in+Germany) · [EY France Sept 2026](https://www.ey.com/en_gl/technical/tax-alerts/french-government-announces-simplification-measures-as-part-of-september-2026-e-invoicing-mandate) · [impots.gouv e-invoicing](https://www.impots.gouv.fr/facturation-electronique-et-plateformes-agreees) · [Agenzia Entrate FatturaPA](https://www.agenziaentrate.gov.it/portale/web/guest/fatturazione-elettronica) · [AEAT Verifactu](https://sede.agenciatributaria.gob.es/Sede/iva/sistemas-informaticos-facturacion-verifactu.html) · [EY Poland KSeF timeline](https://www.ey.com/en_gl/technical/tax-alerts/poland-announces-new-timeline-for-mandatory-e-invoicing) · [EC eInvoicing Belgium](https://ec.europa.eu/digital-building-blocks/sites/spaces/DIGITAL/pages/467108877/eInvoicing+in+Belgium) · [Peppol BIS Billing 3.0](https://docs.peppol.eu/poacc/billing/3.0/) · [CEN EN 16931](https://www.cencenelec.eu/areas-of-work/cen-sectors/digital-society-cen/einvoicing/) · [UK e-invoicing consultation outcome](https://gov.uk/government/consultations/promoting-electronic-invoicing-across-uk-businesses-and-the-public-sector/electronic-invoicing-promoting-e-invoicing-across-uk-businesses-and-the-public-sector)
