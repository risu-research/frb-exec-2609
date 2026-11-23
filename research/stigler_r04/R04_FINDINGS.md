# Stigler R04 — 2026-11-23
Decision: A commerce observational audit HOLD, B companion operator liability HOLD, C EU/US search-data remedial access GO for bounded evidence feasibility (not submission GO). R02/R03 original lobbying NO-GO maintained. No actual access, certification, application, or market effect measured.
## A
Public observability limitation explicitly acknowledged by existing October audit (https://evdev.dev/blog/shopify-ai-shopping-readiness-2026). Additional overlap https://sempite.com/research/agentic-commerce-readiness/ ; https://mcp.storeinspect.com/blog/shopify-agentic-commerce ; https://borowiecki.dev/pdf/2611.20378 . Shopify merchant eligibility https://help.shopify.com/en/manual/online-sales-channels/agentic-storefronts/products ; API terms https://shopify.dev/docs/agents/catalog . No merchant experiment conducted due to confounding and admin-only eligibility.
## B
CT PA26-15 §4(1)(B)(vii), pp 9–10, exemption for supplier that does not solely determine specific use case, UI or deployment context. §5 safety and disclosure, §6 minor protections effective 2027-01-01. https://cga.ct.gov/2026/ACT/PA/PDF/2026PA-00015-R00SB-00005-PA.PDF (text read, page screenshot 502). Illustrative same model self-operated vs licensed to independently controlling deployer: different actor-level obligations under CT statute, not elimination of downstream duty and not general tort immunity. CO enacted summary https://www.leg.colorado.gov/bills/hb26-1263 . Existing cross-state trackers and CRS https://www.everycrsreport.com/reports/R49189.html ; cannot infer costs or market structure from scope alone.
## C
EU case DMA.100209 final 2026-07-16, official summary https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:52026DMA100209 ; exact commercial eligibility from Commission https://digital-markets-act.ec.europa.eu/businesses-portal/data-access/alphabet-specification-proceedings-sharing-google-search-data_en and Google implementation https://developers.google.com/search/help/about-search-data-program . Official summary says at least EUR50m but detailed Commission page and Google both say MORE THAN; corporate age under 2 years required for investment branch. Final full official PDF link https://ec.europa.eu/competition/digital_markets_act/cases/202629/DMA_100209_2712.pdf returned 404; mirrored full decision recital 128(c), 165–171 and final measures paragraph 3(c) https://librejustice.fr/decision/eu/ymaSSepNnH5w ; secondary redline https://research.eutechreg.com/dossiers/google-search-data-sharing-dma/ . April preliminary official PDF section 1 paragraphs 1–2 visually checked: no quantitative thresholds there; separate investment credibility audit in paragraph 68. https://digital-markets-act.ec.europa.eu/document/download/b3aed7f6-c45c-4bfa-b032-b8975a48bb06_en?filename=DMA.100209+-+Preliminary+measures.pdf . Final recital 170 explains discretion reduction; 171 rejected Alphabet request for higher user floor. No claim of lobbying capture. Additional safeguards, independent audit and data geography; eligibility not guaranteed by passing numerical gate.
## US
Final Judgment 2025-12-05 Doc 1462 §IX.V, §IV, §V https://www.justice.gov/atr/media/1421546/dl (p33 screenshot checked), no explicit numerical thresholds in judgment, conditional investment plan, security, national security and audits; annual recertification. Different remedy scope; US live syndication distinct from data sharing; 40% cap first year. Implementation not verified. Named entities list from joint status report 2026-08-14 Doc1542 p3 visually checked https://www.justice.gov/atr/media/1458106/dl?inline= : Anthropic, Brave, DeepSeek, DuckDuckGo, Ecosia, Meta, Microsoft, OpenAI, Perplexity, Yahoo, SpaceXAI. NOT certified applicants, list is proposed employment-conflict list, nonexhaustive, usable for independently documented candidate pilot only.
## Logical pilot
Assuming OSE and all other conditions, quantitative screen = (EU OSE service >= 24 months OR (undertaking age < 24 months AND capital > EUR50m)) AND EU average monthly users past year >=50k. Months simplified, actual dates needed. Eight synthetic checks executed, all match expectations; not empirical cases. Temporal reversal describes screen evaluated at successive hypothetical application dates, NOT automatic loss of an already granted license.
[
  {
    "case": "new well-funded",
    "age": 23,
    "service": 12,
    "capital": 60,
    "users": 50000,
    "expected": true,
    "result": true
  },
  {
    "case": "same company at second anniversary",
    "age": 24,
    "service": 13,
    "capital": 60,
    "users": 50000,
    "expected": false,
    "result": false
  },
  {
    "case": "same company after two years operating",
    "age": 35,
    "service": 24,
    "capital": 60,
    "users": 50000,
    "expected": true,
    "result": true
  },
  {
    "case": "old firm recent entry",
    "age": 60,
    "service": 12,
    "capital": 600,
    "users": 50000,
    "expected": false,
    "result": false
  },
  {
    "case": "new firm exactly threshold",
    "age": 23,
    "service": 12,
    "capital": 50,
    "users": 50000,
    "expected": false,
    "result": false
  },
  {
    "case": "new firm below users",
    "age": 23,
    "service": 12,
    "capital": 60,
    "users": 49999,
    "expected": false,
    "result": false
  },
  {
    "case": "established low capital",
    "age": 60,
    "service": 24,
    "capital": 1,
    "users": 50000,
    "expected": true,
    "result": true
  },
  {
    "case": "established below users",
    "age": 60,
    "service": 24,
    "capital": 100,
    "users": 49999,
    "expected": false,
    "result": false
  }
]
## Real candidate anchor
Anthropic founded 2021 https://www.anthropic.com/news/anthropic-raises-series-b-to-build-safe-reliable-ai ; global paid web search announced May 1 2025 https://claude.com/resources/articles/integrations?cmid=ea37f93d-8283-4183-beec-3c381ff690c3 ; March 20 2025 launch earlier. https://claude.com/blog/web-search ; 2023 capital well above threshold https://www.anthropic.com/news/anthropic-series-c . Conditional example only; EU OSE classification, prior qualifying service, applicant entity, EU user base and actual application unverified. OpenAI search launch Oct31 2024, free rollout later https://openai.com/index/introducing-chatgpt-search/ ; not proof of first qualifying EU service.
## Prior art and gate
Existing comparison https://laweconcenter.org/resources/comparing-the-eu-dma-to-the-search-query-data-sharing-remedy-in-us-v-google/ (2025); consultation analysis https://kgi.georgetown.edu/research-and-commentary/designing-europes-search-data-sharing-rules-for-competition-in-the-ai-era/ ; preliminary/final clause redline by EUTechReg already exists. Threshold alone not novel. R05 precommit candidate cohort and historical dates, independent EU user estimates or bounds, actual entity identities, timing and alternative routes, examine whether at least two real candidates have verified screen difference or duration and no alternative qualification route. Unknowns remain unknown. Seek full official decision, actual applicant/recipient evidence. Stop if only formal counterexample or no independently grounded material access differences. Main unchanged.
