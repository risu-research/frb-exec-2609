# Stigler 2027 / R00 — Competitive public-source prospect screen

Recorded 2026-11-23. Aim: choose a publishable, concrete institutional market/democracy finding **before** committing to full-scale experiments. This record does **not** claim a novel completed paper or causal regulatory capture.

## Candidate A: AI safety bills as competition rules

Sources: 
- HI SB3001 introduced: https://data.capitol.hawaii.gov/sessions/session2026/bills/SB3001_.HTM
- HI SB3001 CD1 enacted Act 248: https://data.capitol.hawaii.gov/sessions/session2026/bills/SB3001_CD1_.HTM
- CO HB26-1263 introduced: https://www.leg.colorado.gov/bill_files/112332/download
- CO HB26-1263 signed: https://www.leg.colorado.gov/bill_files/116851/download
- IA SF2417: https://www.legis.iowa.gov/docs/publications/LGE/91/attachments/SF2417.html
- GA SB540 signed: https://gov.georgia.gov/document/2026-signed-legislation/sb-540/download
- OR SB1546 enacted: https://www.oregonlegislature.gov/bills_laws/lawsstatutes/2026orLaw0085.pdf

Actual verified legal-text pilot:
- HI introduced: public conversational AI broadly defined; explicit embedded-features exclusion; the definition of user/account holder expressly includes guest/temporary users.
- HI enacted: affirmative definition now AI companion with joint memory, unsolicited emotional questions, sustained personal dialogue; old explicit list removed; user definition now account/profile based. Removing exceptions therefore DOES NOT mechanically imply increased coverage; the coverage change need not be monotonic.
- GA and OR enacted: similar conjunctive 3-feature companion approach, but different exceptions and remedies.
- IA: broad conversational AI with six explicit categories of exclusions and narrower minor *account-holder* specific duties (read the precise section before concluding how guest protection differs).
- CO introduced: six categories of exclusion; CO signed: twelve numbered categories in statutory definition, corroborated by official PDF pages and NPR. **Scanned signed Colorado PDF has no machine-readable text in Python pypdf**. It has an authoritative SHA, but all coded textual signals for it are NULL and MUST NOT be inferred as absent.
- These are *statutory wording checks* only. Do not classify real companies as legally immune. Do not call any changes due to a particular lobbyist without independently tracing documented amendments and statements.

Novelty warning: 2026 Future of Privacy Forum defined 5 chatbot and 3 companion definition types (Feb 2026), 2026 NPR documented same clauses crossing states and industry contacts, VA JCOTS 2026 recommended coverage of all chatbots and developers/deployers. A 2025 Lancieri et al. article already examines AI capture and regulatory arbitrage.
Conditional next test: collect **all** 2025-26 state chatbot laws (enacted + important failed) with chronological versions and stage-specific public testimony. Independently pre-code functional scenarios with explicit burdens, ambiguity and legal counsel validation; estimate scope transitions and compare expansion vs narrowing of obligations, without claiming actual economic injury without product-population data or market outcomes.

## Candidate B: Independence cost in federal NAIRR research access

Source: https://submit-nairr.xras.org/resources.json. Resource allocation rules: https://nairrpilot.org/opportunities/allocations
Snapshot SHA256: d506e8d11f9090de05f94da158852a5891b9a9b271ac4a7d7a91c79c938e6b4c (2026-11-23 22:38 UTC)
Total 47 resources (25 Compute, 13 Cloud Platform, 8 Program, 1 Observing Facility). Status category: 39 Active, 3 Paused, 1 Retired, 4 status unlisted. Note status features may overlap other category features.
Specific four *Active*-tagged model resources explicitly contain text that they are **unable to accept additional NAIRR Pilot awards**: Groq LPU Inference Engine, Anthropic Model API, OpenAI API, SambaCloud. Fifth not-accepting resource NVIDIA DGX Cloud is marked Retired. AWS, Google Cloud and Microsoft Azure are marked Paused.
Resource categories include 27 'Federal agency systems', 6 'Private sector model access', 6 'Private sector computational resource', and 7 'Other private sector contribution'; some category memberships overlap and are not mutually exclusive. Critically 'Federal agency systems' is NOT by itself proof that an option remains available if a researcher opts out of non-governmental partner review.
The program allows investigators to exclude non-governmental partner proposal access, but then they must choose only government agency resources. Claims of actual allocation loss, review discrimination or financial costs are UNSUPPORTED by the public feed.
Novelty warning: 2026-11-17 CRS report explicitly discusses NAIRR's potential to entrench large incumbents; CalCompute catalog (2026-11-10) already noted five resources not accepting additional awards. Current data's four Active-vs-unavailable inconsistencies are concrete but insufficient by themselves for Stigler 2027 full paper.
Follow-up if pursued: verify government-only resource classification directly from program, record category/status snapshots over time and capacity, define fixed research tasks then ask whether optout causes loss of unique model capability. No inferences about actual applicant access from resource tags alone.

## Triage
- Illinois data center job target bunching: NO-GO (NCSL and Nov 2026 University of Illinois work).
- 2026 political ad spending, agentic onchain payments, generic model-market concentration: NO-GO as bare descriptions (existing direct empirical studies).
- Current G-Cloud lexical-choice study: R02 NO-GO.
- **Candidate A: conditional research-priority 1**, uniquely appropriate to Stigler 2027 'AI lobbying and regulatory capture' but the paper must produce *new outcome-level, economically meaningful evidence*.
- **Candidate B: exploratory backup**, better 'AI in academic research process', but unclear independent-access effect and many source-level observations already public.
- No final paper GO issued here.

## Reproduce
Run `python research/stigler_r00/run.py` after `pip install requests beautifulsoup4 pypdf` in a networked environment. Official source snapshots, SHA256, word-presence audit fields and NAIRR JSON are archived in CI artifacts. Discard/flag any machine-unreadable PDF, do not convert NULL to false.

Independent analyst adjudication and legal review remain future work.
