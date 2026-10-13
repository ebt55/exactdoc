# Holdout-4 sampling recipe, tranche 2 (RECIPE-2)

Written 2026-10-13 by the holdout-4 collector agent on the coordinator's
decision (supplementary tranche), BEFORE any tranche-2 candidate was looked at.
Tranche 1 (RECIPE.md) is closed and unchanged: its 24 documents stay as they
are. Nothing is ever converted by the collector. Deviations are appended at the
end under "Deviations", never edited in place.

## Target

12 more documents, all short (1-20 pages), all expected promised, so the
combined set is about 36 with at least 25 short promised. Sub-strata (quota):

| sub-stratum | what | quota |
|---|---|---|
| T1 | Word letters, memos, briefing notes, short reports from public bodies of Ireland, Canada, Australia, New Zealand (1 each) | 4 |
| T2 | university course outlines/syllabi published as PDF (Word, LibreOffice, Google Docs or TeX) | 3 |
| T3 | Google Docs exports (producer "Google Docs Renderer"), not resumes | 2 |
| T4 | Chrome web prints (found first; printed for the set only if fewer than 3 are found) | 3 |
| T6 | reserve: short arXiv LaTeX papers, used only to fill places T1-T4 leave empty, up to a tranche total of 12 | 0-12 |

## Mechanical selection rule (as in RECIPE.md)

Candidates are taken strictly in the order the source returns them; the first
N eligible fill the quota; the rest are not looked at; every candidate and its
fate is logged in cand/log2.jsonl; a candidate rejected for one sub-stratum is
never reallocated to another. "WebSearch(Q, D)" = the agent's WebSearch tool,
mode "standard", query Q, allowed_domains D (none if omitted), results in
returned order; a result that is an HTML page yields the first PDF link on it
that fits the sub-stratum (one candidate per result page), or, for T3, the
first docs.google.com/document link on it, exported as
`https://docs.google.com/document/d/<ID>/export?format=pdf`. At most 15
candidates are fetched per query for T3 and T4.

- T1-IE (1): WebSearch("letter 2025 pdf", [gov.ie]); fallback WebSearch("briefing note 2025 pdf", [gov.ie]).
- T1-CA (1): WebSearch("memorandum 2025 pdf", [canada.ca, gc.ca]); fallback WebSearch("briefing note 2025 pdf", [canada.ca, gc.ca]).
- T1-AU (1): WebSearch("letter 2025 pdf", [gov.au]); fallback WebSearch("briefing note 2025 pdf", [gov.au]).
- T1-NZ (1): WebSearch("letter 2025 pdf", [govt.nz]); fallback WebSearch("briefing note 2025 pdf", [govt.nz]).
  T1 producer: Word, LibreOffice or the Google Docs renderer; 1-20 pages; max 1 per organisation.
- T2 (3): WebSearch("course outline pdf 2025 university"); fallback
  WebSearch("module handbook pdf 2025"). Producer Word, LibreOffice, Google
  Docs renderer or a TeX engine; 1-20 pages; max 1 per university.
- T3 (2): WebSearch("school handbook 2025 pdf"), then WebSearch("newsletter
  2025 pdf"), then WebSearch("club constitution pdf"). Producer must contain
  "Google Docs Renderer"; 1-20 pages; not a resume; max 1 per organisation.
- T4 (3), phase 1 (found): WebSearch("syllabus spring 2026 pdf"), then
  WebSearch("course policies pdf 2026"). Producer "Skia/PDF" without "Google
  Docs Renderer", or creator containing Chrome, Chromium or HeadlessChrome;
  1-20 pages; max 1 per organisation.
- T4 phase 2 (printed for the set), only for the places phase 1 leaves empty:
  the pages below, in this order, each printed once with Chrome 155.0.8059.40
  on this machine, default print settings, a fresh empty profile:

      "C:\Program Files\Google\Chrome\Application\chrome.exe" --headless --disable-gpu --user-data-dir=C:\lotmp\rv_hold4\pp --print-to-pdf=C:\lotmp\rv_hold4\cand2\print_<n>.pdf <URL>

  1. https://cs50.harvard.edu/x/2024/syllabus/
  2. https://ocw.mit.edu/courses/6-0001-introduction-to-computer-science-and-programming-in-python-fall-2016/pages/syllabus/
  3. https://www.w3.org/Consortium/cepc/
  4. https://www.apache.org/foundation/policies/conduct.html
  5. https://www.rust-lang.org/policies/code-of-conduct
  6. https://ocw.mit.edu/courses/18-06-linear-algebra-spring-2010/pages/syllabus/
  7. https://www.ox.ac.uk/students/academic/guidance/skills/plagiarism
  8. https://www.debian.org/social_contract

  A page is eligible if it answers HTTP 200 to curl and its printed PDF passes
  the eligibility rules (1-20 pages). Printed documents are recorded as
  "printed for the set" with the command, the URL and the print time; their
  `url` field is the page URL.
- T6 reserve: arXiv(`cat:C AND submittedDate:[202509160000 TO 202509162359]`)
  for C cycling in the order cs.DL, stat.AP, cs.HC, physics.ed-ph, cs.CY,
  one per category per cycle; producer a TeX engine (incl. arXiv GenPDF
  tex2pdf); 1-20 pages; until the tranche totals 12 or the lists run out.

## Eligibility (as RECIPE.md rules 1-9, with these additions)

- The exclusion set also holds every URL and SHA-256 of tranche 1: the 24
  selected documents and every candidate and result page tranche 1 looked at
  (cand/log.jsonl), so their hosts fall under rule 3 too (repositories
  excepted, as before).
- Host caps across the combined set: arxiv.org 12; docs.google.com 5; GOV.UK
  hosts 7; any other host 3.
- People: descriptions and reasons in the manifest name no individual; the URL
  is the only pointer.

## Classification (as RECIPE.md)

T1/T2/T3 by producer (Google Docs renderer -> ordinary-gdocs, TeX ->
ordinary-latex, else ordinary-word); T4 -> web-print (promised, as in
holdout-3); T6 -> ordinary-latex. promised_narrowed true unless a README
disclaimer applies (dense equations > 3% math characters). Written before
registering, never revised after a result.

## Deviations

(none yet)

- D1 (reading of "the first PDF link on it that fits the sub-stratum", as
  written): on a result page whose first PDF is not of the sub-stratum's kind,
  the first PDF that is was taken as the candidate: T1-AU result 1 (the first
  PDF is 55-page minutes; the letter on the same page was the candidate), T2
  (KIT pages: a study plan and a GenAI handout skipped for the module handbook
  links; Clarendon: the academic calendar skipped for the first syllabus PDF).
- D2: the Highland Council results (T3 query 1) now redirect to listing pages
  (the 2025-26 files were withdrawn); the listing's first handbook was the
  candidate, one per listing.
- D3: tranche 2 printed with Chrome 155.0.8059.40 as listed; list item 3's
  URL redirects to https://www.w3.org/policies/code-of-conduct/ (printed as
  served). Items 5-8 were never printed.

## Outcome

| sub-stratum | quota | taken | note |
|---|---|---|---|
| T1-IE | 1 | 1 | |
| T1-CA | 1 | 1 | |
| T1-AU | 1 | 1 | |
| T1-NZ | 1 | 0 | 403 walls, non-Word producers, thin text |
| T2 | 3 | 0 | outlines behind logins; handbooks 186-587 pages; producers |
| T3 | 2 | 2 | |
| T4 | 3 | 3 | 0 found (phase 1); 3 printed for the set (phase 2, list items 2-4) |
| T6 reserve | 4 | 4 | cs.DL, stat.AP, cs.HC, cs.CY (physics.ed-ph had none) |
| total | 12 | 12 | |
