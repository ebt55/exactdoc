# The beta bar

**Ratified by the owner on 2026-10-05** ("option A": the independent bar
review's proposal, adopted exactly).

**0.3.0b1 is not tagged while any gating criterion fails.** Criteria 1–6, 8 and
10–12 gate the beta. Criteria 7, 9 and 13 are reported for the beta and gate
the 1.0 release (GA). An unmeasured gating criterion is not a pass either.

`python testkit/beta_readiness.py --runs <folder>` reads the latest
measurements against this bar and prints one line per criterion: PASS,
FAIL by N, REPORTED or UNMEASURED, with the documents that miss. The
thresholds live in `BAR` at the top of that file; changing one changes a
ratified bar, so it needs the owner and an edit to this page in the same
commit.

## Which documents

Most criteria grade the **promised** documents: the kinds the README says
work. An expansion document is promised unless the README disclaims its kind
(academic papers, slides, heavily designed layouts, the scripts it marks
"Partly", scans, refused documents); the rule and the list are in
[corpus-expansion.md §14](corpus-expansion.md) and in each document's
`promised` field in `testkit/corpus_expansion.json`. Of the 16 gated
documents, the 13 the ratified Google Docs policy tiers `ordinary_digital` are
promised. Today that is 62 documents: 41 of 20 pages or fewer, 21 longer.

**Lanes** are where the DOCX is opened: LibreOffice (the raw sweep, rendered in
the pinned container), Word (the Word lane, rendered by Word itself), and
Google Docs (live: uploaded, converted by Google and exported).

## The criteria

| # | Criterion | Threshold | Data | Why |
|---:|---|---|---|---|
| 1 | Crash-free | 0 conversion errors on any document in any input; every `unsupported` document refused with a typed exit code (17 scan, 19 form, 20 page cap) | every sweep and lane read | A crash is the one failure a tester cannot work around |
| 2 | Time | Product profile ≤ 60 s for documents of ≤ 40 pages, ≤ 1.5 s per page above; raw ≤ 1 s per page | `convert_s` in the product and raw sweeps | The product profile is what `exactdoc file.pdf` runs when LibreOffice is installed; minutes per document reads as a hang |
| 3 | Word opens cleanly | 100% open with no repair prompt; compatibility mode recorded | Word lane rows (open, repair, compat) | A repair prompt tells a tester the file is broken, whatever it looks like |
| 4 | Short documents exact | Promised documents of ≤ 20 pages: 100% page-exact in each lane | LibreOffice raw, Word, Docs live | A memo or letter that gains a page is visibly wrong at a glance |
| 5 | Long documents close | Promised documents over 20 pages: on ≥ 80% of them, \|Δpages\| ≤ max(1, 2% of the pages) and word recall ≥ 0.85, in each lane | LibreOffice raw, Word, Docs live | Long reports are what people convert; page drift there breaks every cross-reference |
| 6 | No catastrophe | 0 promised documents with char recall < 0.5 or \|Δpages\| > 20%, in any lane | LibreOffice raw, Word, Docs live | One unusable result on a promised kind costs more trust than many small faults |
| 7 | Placement *(reported; GA gate)* | Promised ≤ 20 pages: word recall ≥ 0.9 and median vertical drift (dy_p50) ≤ 10 pt on ≥ 90% | the three lanes | Looks-like-the-original, beyond the page count |
| 8 | No regression | No document worse than in the last accepted sweep beyond `testkit/gate.py`'s tolerances, over all documents | raw sweep vs the accepted sweep | The beta must not lose what earlier work won |
| 9 | Editability *(reported; GA gate)* | Promised documents: text-box share ≤ 0.05, one-cell tables ≤ 1 per page, real list numbering on ≥ 90% of list paragraphs where lists exist | `editability` in the raw sweep | "Editable" is the product's promise, and placement metrics cannot see it |
| 10 | Fonts | Every family the DOCX declares is in the stock Windows + Microsoft 365 set, or listed in the README | static census of the kept DOCX files | A family a tester's Word lacks is substituted, and the layout moves |
| 11 | Gated 16 | Both gate lanes PASS | the canonical gate's lane verdicts | The frozen corpus is the contract every change is held to |
| 12 | README is current | Every number the README cites matches the release sweep; no cited evidence file older than the newest measurement by more than 7 days | README.md against the inputs | Testers read the README first; a stale claim there is a false one |
| 13 | Google Docs policy *(reported; GA gate)* | The ratified per-document thresholds in `testkit/gdocs_quality_policy.json` (page match, live text, recall, SSIM, drift) on ≥ 90% of promised documents | Docs live | The Docs qualification bar, applied beyond the gated 16 |

"FAIL by N" is the number of offending documents for an all-must-pass
criterion, and for a share criterion the number of further documents that
would have to pass, summed over lanes.
