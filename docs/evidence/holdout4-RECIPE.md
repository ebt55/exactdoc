# Holdout-4 sampling recipe (v1)

Written 2026-10-13 by the holdout-4 collector agent, BEFORE any candidate was
looked at (only the exclusion set had been built, from the repo and the
holdout-1/2/3 manifests). Nothing in this set is ever converted by the
collector. Deviations, if any, are appended at the end under "Deviations",
never edited in place.

## Target

40 public PDFs, in seven strata (quota in brackets), roughly holdout-3's mix:

| stratum | what | quota | promised |
|---|---|---|---|
| S1 | short letters, memos, audit/report summaries (<= 20 pp) from public bodies, universities, NGOs (S1a UK 3, S1b EU 3, S1c US 3) | 9 | yes |
| S2 | resumes / CV samples published by organisations as samples or templates (S2a university career-centre samples 5, S2b Google Docs templates 2, S2c LaTeX templates 2) | 9 | yes |
| S3 | LaTeX papers and theses from arXiv (S3a short <= 20 pp: 4; S3b long > 20 pp: 2 theses + 1 paper) | 7 | yes |
| S4 | Google Docs exports, not resumes | 3 | yes |
| S5 | Chrome (Skia/PDF, not the Google Docs renderer) web prints | 3 | yes |
| S6 | long Word reports, 21-250 pp (S6a UK 2, S6b US state 2, S6c EU 1) | 5 | yes |
| S7 | "Not yet" controls: designed reports / annual reports (S7a UK 2, S7c EU 1) and a multi-column booklet (S7b 1) | 4 | no |

## Mechanical selection rule

For each sub-stratum, candidates are taken strictly in the order the named
source returns them; each is tested against the eligibility rules below; the
first N eligible candidates fill the quota; the rest are not looked at. A
candidate that fails is logged with its failure reason (cand/log.jsonl) and
never reconsidered for any other stratum. No candidate is chosen or dropped
because it looks easy or hard. If a source is exhausted before its quota is
filled, its listed fallback is used in the same way; if that is exhausted too,
the shortfall is recorded and the set is smaller.

"WebSearch(Q)" means the agent's WebSearch tool, mode "standard", query Q
exactly as written, results in returned order. When a result is an HTML page
rather than a PDF, the first PDF link on that page that fits the sub-stratum
description is the candidate (one per result page). "GOV.UK(T)" means
`https://www.gov.uk/api/search.json?filter_content_store_document_type=T&order=-public_timestamp&count=100&filter_public_timestamp=to:2026-10-01`,
results in returned order; the candidate is the first PDF attachment listed by
`https://www.gov.uk/api/content<link>`. "arXiv(Q)" means
`http://export.arxiv.org/api/query?search_query=Q&sortBy=submittedDate&sortOrder=ascending&max_results=100`,
entries in returned order, PDF from `https://arxiv.org/pdf/<id>` (the version
current on retrieval).

### Sources

- S1a (3): GOV.UK(correspondence); fallback GOV.UK(foi_release). Producer must
  be Word (producer or creator names Microsoft Word / PDFMaker for Word).
  Max 1 per GOV.UK organisation.
- S1b (3): WebSearch("letter to the European Commission 2025 pdf") restricted
  to allowed_domains [europa.eu]; fallback WebSearch("EU agency opinion letter
  2025 pdf"), then WebSearch("European NGO open letter 2025 pdf"). Producer
  Word, LibreOffice or Google Docs. Max 1 per organisation.
- S1c (3): WebSearch("faculty senate memorandum 2025 pdf"); fallback
  WebSearch("city council memorandum 2025 pdf"), then WebSearch("nonprofit
  comment letter 2025 pdf"). Producer Word, LibreOffice or Google Docs. Max 1
  per organisation.
- S2a (5): WebSearch("sample resume pdf university career center"); fallback
  WebSearch("resume examples pdf career services"), then WebSearch("CV
  samples pdf graduate students career"). Any producer except design tools
  (InDesign, Illustrator, Canva, Affinity, Quark, Publisher), which make the
  candidate ineligible. Max 1 per university.
- S2b (2): WebSearch("resume template google docs career center"); the
  candidate is a docs.google.com/document link on the result page (or the
  result itself), exported as `https://docs.google.com/document/d/<ID>/export?format=pdf`.
  Producer must be the Google Docs renderer. Fallback WebSearch("google docs
  resume template university").
- S2c (2): WebSearch("latex resume template github"); the candidate is the
  example PDF committed in the result repository (first .pdf in the repo
  root, else in an examples/ directory). Producer must be a TeX engine.
  Fallback WebSearch("latex cv template github example pdf").
- S3a (4): arXiv(`cat:C AND submittedDate:[202509150000 TO 202509152359]`)
  for C in order cs.CL, cs.CY, q-bio.PE, econ.GN, physics.soc-ph, cs.SE; the
  first eligible paper of each category, until 4 are taken. Producer a TeX
  engine, 1-20 pages.
- S3b (3): two theses: arXiv(`co:thesis AND submittedDate:[202509010000 TO 202509302359]`),
  TeX producer, 21-250 pages; one long paper: the S3a category queries in
  the same order, the first TeX paper with 21-250 pages.
- S4 (3): WebSearch("docs.google.com document syllabus 2025"); fallback
  WebSearch("docs.google.com document meeting minutes 2025"), then
  WebSearch("docs.google.com document policy handbook"). Exported as in S2b;
  producer must be the Google Docs renderer; not a resume. Max 1 per owner
  institution.
- S5 (3): WebSearch("course syllabus fall 2025 pdf"), then
  WebSearch("privacy policy pdf"), then WebSearch("terms of service pdf"),
  then WebSearch("meeting agenda 2025 pdf"); at most the first 30 PDF
  results per query are fetched. Producer must be Skia/PDF without "Google
  Docs Renderer" (or creator Chrome/Chromium/HeadlessChrome).
- S6a (2): GOV.UK(research), producer Word, 21-250 pages; max 1 per
  organisation; fallback GOV.UK(independent_report).
- S6b (2): WebSearch("state auditor performance audit report 2025 pdf");
  fallback WebSearch("state legislative audit report 2025 pdf"). Producer
  Word, 21-250 pages. Max 1 per state.
- S6c (1): WebSearch("final report study 2025 pdf") restricted to
  allowed_domains [europa.eu]; producer Word, 21-250 pages.
- S7a (2): GOV.UK(corporate_report); creator must be a design tool
  (InDesign, Illustrator, Affinity, Quark, Publisher). Max 1 per organisation.
- S7b (1): WebSearch("consumer booklet pdf") restricted to allowed_domains
  [consumer.ftc.gov, consumerfinance.gov, fdic.gov, usa.gov]; must be a
  multi-column booklet made in a design tool.
- S7c (1): WebSearch("annual report 2024 pdf") restricted to allowed_domains
  [europa.eu]; creator must be a design tool.

## Eligibility (every rule must hold)

1. Public: fetched with curl, no login, cookie wall, paywall or token; HTTP
   200; the body starts with `%PDF`; not encrypted against opening.
2. Not already used: neither its URL nor its SHA-256 appears in the exclusion
   set (every URL and 64-hex string in testkit/**/*.json, docs/**/*.md,
   docs/evidence/holdout*-manifest.json, the holdout-1/2/3 manifests in
   C:/lotmp/rv_hold*, and the SHA-256 of every PDF in those set directories
   and in testkit/fixtures*).
3. Not the same source or series: its host is not a host of any excluded URL,
   except the repositories arxiv.org, docs.google.com, github.com,
   raw.githubusercontent.com, www.gov.uk, assets.publishing.service.gov.uk;
   inside a repository it is not the same document (any version/edition), the
   same GitHub repository or the same Google Docs owner institution as an
   excluded one, nor another part or edition of a used document series.
   Explicitly out: any Inspector General office already used (DHS, OPM, ED,
   DOE, DOL, TIGTA, VA, Peace Corps, SBA, NASA, USDA, NSF, HUD), oversight.gov,
   the career centres of CMU, Memphis, Boise State, UBalt, ECU, Harvard, MIT,
   Wikipedia's PDF renderer, CTAN package manuals, Awesome-CV, AltaCV,
   sb2nov/resume, europecv, Dallas council memos, SJSU syllabi.
4. Text layer: `pdftotext -layout` yields >= 100 non-space characters on at
   least 90% of pages (S7: 70%), and the document is not a scan (no page whose
   only content is one image covering >= 85% of the page, on any of the first
   5 pages that have < 100 characters; no scanner/OCR producer such as Paper
   Capture, ABBYY, OmniPage, scanner firmware).
5. Not a form: no AcroForm with fields (pypdf `get_fields()` empty) and no XFA.
6. Inside the README's other limits: 1-250 pages; Latin-script, mainly
   English or another European language; not slides (fewer than half the
   pages landscape with aspect > 1.25).
7. People: a resume/CV only when an organisation publishes it as a sample or
   template; letters from organisations only; nothing whose subject is a
   private individual.
8. Diversity caps: at most 3 documents per host across the set, except
   arxiv.org (7), docs.google.com (5), GOV.UK hosts (5 together), github.com +
   raw.githubusercontent.com (2 together).
9. The sub-stratum's own producer and page constraints above.

## Classification (written before anything is converted, never revised after)

- producer / creator: the PDF Info dictionary as read by pypdf (empty string
  when absent).
- pages: pypdf's page count. Short = <= 20 pages, long = > 20.
- design_class: S1/S4 by producer: Google Docs renderer -> ordinary-gdocs, TeX
  -> ordinary-latex, else ordinary-word; S2 -> resume; S3 short ->
  ordinary-latex, S3 long -> long-report-ordinary; S5 -> web-print; S6 ->
  long-report-ordinary; S7 -> designed-report, annual-report (title says
  annual report / annual report and accounts) or multicolumn-booklet.
- promised_narrowed (amendment 6 point 2): true for S1-S6 (Word, Google Docs,
  LibreOffice or LaTeX flowing text, and Chrome web prints read as promised as
  in holdout-3), except that a document hitting a README disclaimer that the
  eligibility test does not already exclude (dense equations: more than 3% of
  extracted non-space characters are Greek or mathematical symbols) is false
  with that reason; false for S7.
- reason: one line saying why.

Field names and key order follow docs/evidence/holdout3-manifest.json.

## Deviations

(none yet)

- D1 (2026-10-13, before any GOV.UK candidate was fetched): the diversity cap
  "GOV.UK hosts (5 together)" contradicts the GOV.UK quotas (S1a 3 + S6a 2 +
  S7a 2 = 7). The quotas stand; the GOV.UK cap is read as 7 (still max 1 per
  organisation within each sub-stratum).
- D2: arXiv's own PDFs carry producer "pikepdf" and creator "arXiv GenPDF
  (tex2pdf:...)"; that creator is read as "a TeX engine" (arXiv compiles them
  from TeX source).
- D3: one arXiv PDF (2509.11706, physics.soc-ph) was fetched by a loop overrun
  after the S3a quota was already full; it was not considered or selected.
- D4 (bookkeeping, no effect on selection): S1b fallback-1 results 2,3,4,5,7,9,10
  are op.europa.eu pages served by the same download handler that returned the
  portal home page for result 1; they were logged as not fetchable without a
  separate fetch each. S1c result 8 was fetched before result 7; 8 failed, so
  the take order is unchanged. Several "download" links (UNM filestore, Ketley
  download page, Canvas file) were followed to the PDF they serve.
- D5 (observation, rule unchanged): eligibility rule 4 (>= 100 characters on
  >= 90% of pages) rejected short Word letters whose last page holds only
  signatory logos (S1b EU4Health letter, the SOTEU letter of intent).
- D6 (2026-10-13, after the session resumed, before anything else was
  fetched): the recipe is kept unchanged as instructed by the coordinator.
  Every download was re-verified (size and SHA-256 against the log, %%EOF,
  opens in pypdf); the six non-PDF error pages were renamed *.notpdf.html; one
  truncated download (S7c EIOPA, curl 18 twice) was rejected as not fetchable
  intact.

## Outcome (recipe followed to exhaustion; no source added)

| stratum | quota | taken | shortfall |
|---|---|---|---|
| S1a | 3 | 3 | 0 |
| S1b | 3 | 1 | 2 |
| S1c | 3 | 3 | 0 |
| S2a | 5 | 1 | 4 |
| S2b | 2 | 2 | 0 |
| S2c | 2 | 0 | 2 |
| S3a | 4 | 4 | 0 |
| S3b | 3 | 3 | 0 |
| S4 | 3 | 1 | 2 |
| S5 | 3 | 0 | 3 |
| S6a | 2 | 2 | 0 |
| S6b | 2 | 0 | 2 |
| S6c | 1 | 1 | 0 |
| S7a | 2 | 2 | 0 |
| S7b | 1 | 0 | 1 |
| S7c | 1 | 1 | 0 |
| total | 40 | 24 | 16 |
