# exactdoc status

This is the current measured state. The corpus is 16 frozen fixtures pinned by
SHA-256; canonical figures come from the pinned Linux/LibreOffice environment.
Regression baselines answer “did this get worse?” They are not an absolute claim
that every document meets release quality.

## Shipping quality

The shipping product remains quality-first:

```text
pymupdf/standard/libreoffice/refine3@240dpi
```

`raw` is PyMuPDF/standard with the refinement loop off. PyMuPDF is core;
PDFium is optional through `[pdfium]`.

| Canonical profile | Page match | Mean within 2pt | Mean live text | Median dy50 |
|---|---:|---:|---:|---:|
| product | 15/16 | 0.4981 | 0.9652 | 0.675pt |
| raw | 13/16 | 0.3349 | 0.9652 | 2.2pt |

Known product limitations remain:

- `c3_tables`: nested-table reconstruction and page fragmentation.
- D10 rasterised text regions in `c5_graphics` and `04_exec_brief`.
- Heavy LaTeX, highly designed/vector pages, and nested tables are deferred;
  scan/OCR PDFs are unsupported.

The project prioritises ordinary digital text, multi-column pages, common
tables, and i18n. A rasterised figure can be the honest fallback for a designed
region, but its text is counted as non-live by the quality metrics.

## PDFium migration candidate — not shipping

`PDFIUM_GDOCS_CANDIDATE` is the explicit non-shipping profile:

```text
pdfium/gdocs/none/refine0@240dpi
```

| Candidate measurement | Page match | Mean within 2pt | Mean live text | Median dy50 |
|---|---:|---:|---:|---:|
| open loop | 14/16 | 0.2429 | 0.9568 | 2.425pt |
| candidate-refined diagnostic | 15/16 | 0.3381 | 0.9568 | 2.06pt |

Same-profile PDFium/PyMuPDF parity is **7 regressions, 7 same, 2 better**.
Plain memo placement, complex scripts, and graphics are material regressions.
The candidate is not adopted and is not releasable.

A general bottom-margin relief fixed the candidate's `c1_whitepaper` and
`c2_paper2col` overflow while preserving the other 12 page-matching fixtures.
It intentionally does not treat `c3_tables` (nested table) or `c5_graphics`
(designed graphics) as a margin problem; they remain explicit candidate
limitations.

## Google Docs qualification

The packaged user CLI is `exactdoc-gdocs` (install `.[gdocs]`; for example,
`exactdoc-gdocs auth`). It provides authentication, cleanup attempts for created
Drive objects, orphan-ledger blocking, and safe evidence handling. Testkit
qualification separates preparation from a consented upload:

```bash
python testkit/gdocs_oracle.py prepare <dir>
python testkit/gdocs_oracle.py run <dir> --allow-cloud-upload
```

`prepare` is offline and hash-binds the exact candidate. `run` is the upload
operation and separately reports operational success and quality success. Drive
objects are always cleanup-attempted; an orphan ledger blocks continued work.

The final 2026-08-02 live run for `pdfium/gdocs/none/refine0@240dpi` is
operationally successful: all 16 documents were attempted and succeeded, with
zero failures, and no `.gdocs_orphans.json` remained after the run. Targeted
fixes improved page match 12/16 to 14/16, median dy50 6.07pt to 4.98pt, word
recall 0.8356 to 0.8745, SSIM 0.7475 to 0.7767, and ink IoU 0.1814 to 0.2108.
Mean within-2pt was effectively flat (0.1391 to 0.1378) and live text stayed
0.9568. `01_whitepaper_market` is now 3→3 and `04_exec_brief` 2→2.

Remaining page-count misses are `c3_tables` and `c5_graphics`. The former is
ordinary-document work: inference fragments its alternating-fill, multi-page
table into 1x1/1x4 tables and paragraphs, requiring a general cross-page table
assembler. The latter depends on gradient and rounded/rotated complex graphics
and remains a designed-page limitation. PDFium now preserves stretched literal
interword spaces, removing the `01_whitepaper_market` word staircase; PyMuPDF
shipping output is unaffected. `05_memo` geometry improved (dy50 22.67pt to
5.59pt), with a small tradeoff in word recall (0.9639 to 0.9398) and SSIM
(0.9167 to 0.9105).

That operational result leaves quality currently unqualified and unacceptable
for release. No reviewed `testkit/gdocs_quality_policy.json` exists, so the
recorded `quality_pass` and `overall_pass` are false. Review the evidence before
defining a quality policy; do not treat an operational pass as release approval.

## Input hardening

Encrypted PDFs map to an unsupported-input error. Malformed or truncated PDFs
map to parse errors. These failures preserve an existing destination atomically;
they are no longer raw backend exceptions.

## Licensing and release strategy

The project is AGPL-3.0-or-later today. PyMuPDF is core, which is the current
licensing blocker. PDFium is optional and is the migration path, not proof that
the switch is ready.

Apache-2.0 is the preferred future target because its patent grant and
business-friendly terms better suit the intended distribution. It is contingent
on same-profile PDFium parity and reviewed real Google Docs quality evidence,
plus the appropriate legal review. This is project strategy, not legal advice.

## Reproduce safely

```bash
bash scripts/bootstrap.sh --strict
python testkit/corpus_manifest.py verify
python testkit/runall.py
```

Use `testkit/runall.py --absolute` for release qualification, not the ordinary
regression check alone. Never re-record canonical numeric evidence from a local
machine or to silence a failure.
