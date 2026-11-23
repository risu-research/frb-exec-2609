# R02 decision record — G-Cloud 15, 23 Nov 2026

**Decision:** NO-GO as Stigler Center 2027 lead paper for the current thesis "search keyword differences cause market-competition losses". The research can be reopened only if qualified substitutes and meaningful loss under normal buyer workflow are independently established. This is NOT a claim that search is effective, fair, or comprehensive.

## Sources and artifacts

- [R01 full-index run](https://github.com/risu-research/frb-exec-2609/actions/runs/45273298875): 11 complete query pairs; document classification/categorisation returned 146/52 services, 7 common / 191 union.
- [R02 public official detail-page run](https://github.com/risu-research/frb-exec-2609/actions/runs/45275882911): 89 distinct pages HTTP 200, 95 task-by-service records, 60 unique pages in the document classification topic. See `run_r02.py` for frozen sampling and source capture. Temporary Actions artifacts contain original captured public records and should not be treated as sanitized.
- Sanitized research artifact was generated offline as `STIGLER_GCLOUD_R02_RESEARCH_PACKAGE.zip`, with source-summary extracts, 60 preliminary labels, per-page source SHA256 and codebook.

## Frozen preliminary findings

Of 60 unique document-classification candidate listings evaluated in an **AI-assisted single-analyst first pass against supplier statements**, 13 expressly advertised automatic document classification, 6 were ambiguous, and 41 lacked a clear matching feature statement. No independent second human adjudicator has rated them. No product was tested.

Among 13 express functionality claims, 10 were indexed only by R01 search 'document classification', 2 only by 'document categorisation', 0 by both, 1 by neither. In the R01 stratified subset, 4/6 A-only, 1/6 B-only, and 0/3 overlap had an express functionality claim. **These are selected-sample descriptions, not recall, supplier-population estimates or procurement damages.**

The one claim outside both initial indexes was service 853854439618886, 'Intelligent Document Processing / OCR / ICR' (Reply Limited); the offer describes consulting/implementation, leaving equivalence to off-the-shelf SaaS unproved. One positively labeled listing (979101167705072) describes AI SaaS while stating it does not host customer data in a platform; the purported service's exact delivery mechanism remains unresolved.

## Why NO-GO

1. Lexical search sensitivity is well established in IR research. High raw result-set divergence is not itself original.
2. G-Cloud 15 official procedures involve buyer specifications, taxonomy/other filters, supplier checks, and possibly multiple queries. Public search != the actual Contracts Award Service buyer procedure.
3. Most functionality claims found in this enriched small sample were retrievable through the two search-term union, making systematic exclusion under a reasonable multi-query purchasing process unproven.
4. No independently established legally eligible supplier set, comparable prices, actual contract outcome, or AI-specific causal contribution. The comparison deliberately varies keywords, not AI involvement.
5. Richer source coverage would not remedy a missing original economic question; redirect exploration unless a genuinely new effect is found.

## Potential follow-up (separate research hypothesis, NOT assumed GO)

The supplier-facing pages declare whether services are resale of another company's software. This could support studying 'apparent number of vendors vs number of economically independent technology suppliers' after checking overlap with published 2026 G-Cloud 15 reseller studies (including Servnet's 49.2% in-scope reseller share), and independently establishing pricing/product substitutability. Do not rebrand the present null result as that paper without a separate novelty audit.

Scientific ground-truth design: NIST TREC how-to; Buckley et al. (2007), Bias and the Limits of Pooling for Large Collections; Soboroff (2025), Don't Use LLMs to Make Relevance Judgments. Any final labels should receive independent human judgments, uncertainty documentation, and a held-out evaluation.
