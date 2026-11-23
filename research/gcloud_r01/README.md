# Stigler Center G-Cloud R01 — Search Exposure Pilot (2026-11-23)

Status: **exploratory exposure pilot only**; this is NOT evidence of market harm, price effects, legally eligible suppliers, or how a logged-in buyer uses Contract Award Service.

## Precommitted questions
- Does the PUBLIC G-Cloud 15 Lot 2b SaaS keyword search return different visible service/supplier sets for two semantically related, generic buyer phrases referring to the same procurement use case?
- Population baseline: official Lot 2b (software-as-a-service) public listing, no taxonomy / social-value / security / supplier filters.
- 12 query pairs are frozen in `run.py` before the first automated run. They represent simulated purchasing concepts and are NOT sampled actual government statements of requirements.
- Primary DESCRIPTIVE endpoints: raw result count, displayed first-page service overlap (URL service ID), first-page supplier overlap. The cutoff is the site's observed first-page list, usually 30 entries. Full-index overlap and legally compliant shortlist exclusion are NOT measurable at this stage.
- Field discovery must verify the search parameter changes official results; otherwise the script aborts. Every response URL, HTTP code and HTML SHA256 is logged.
- Positive controls: the same browser/HTTP method should reproduce a search when rerun. Stronger controls and independent eligibility labels are required before a substantive claim.
- Fixed limitations: no inference of actual service capability, lawful qualification, government purchasing, procurement outcomes, algorithmic ranking exposure beyond the first page, or AI-induced changes.
- Ethics: public anonymous pages only; gentle sequential requests; no login, no award, no form submission beyond ordinary public GET search.

## Reproduce
```bash
python -m pip install requests beautifulsoup4
python research/gcloud_r01/run.py
```

Artifact: `research/gcloud_r01/results/` is created by the run, uploaded via Actions for inspection. No claim of completeness until run logs validated.

Official protocol: https://www.webprod-cms.gca.gov.uk/agreements/RM1557.15
Official public service catalog: https://www.applytosupply.digitalmarketplace.service.gov.uk/g-cloud/search?lot=saas

Interpretation gates:
- **Gate A0:** source accessible, response reliably parsed, counts and service IDs reproducible.
- **Gate A1:** genuine content-equivalent search pairs produce substantial differences in independently verified eligible suppliers, with recall estimated against a union/reference candidate set not formed by the tested search alone.
- **Gate B:** market-relevant independent supplier choice / genuinely comparable price, with non-equivalent products excluded.
- **Gate C:** measured AI-specific influence or credible AI relevance, separately from generic public-procurement search friction.

This folder is deliberately isolated from other research in the shared public execution repository.