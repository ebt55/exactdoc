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

- Complex/nested table layouts remain deferred. The ordinary striped long table
  in `c3_tables` is now assembled as one editable table.
- D10 rasterised text regions in `c5_graphics` and `04_exec_brief`.
- Heavy LaTeX and highly designed/vector pages are deferred; image-only scan/OCR
  PDFs are explicitly rejected as OCR-required rather than silently converted.

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
It intentionally does not treat `c5_graphics` (designed graphics) as a margin
problem. Complex/nested tables remain an explicit candidate limitation.

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

The latest 2026-08-02 live run for `pdfium/gdocs/none/refine0@240dpi` is
operationally successful: 16 attempted, 16 succeeded, zero failed, and no
`.gdocs_orphans.json` remained. Compared with the prior live candidate,
page-count match improved 14/16→15/16; mean within-2pt 0.1378→0.1443; mean live
text stayed 0.9568; mean word recall 0.8745→0.9064; mean SSIM 0.7767→0.7878;
and mean IoU 0.2108→0.2138. Median dy50 is 4.98→6.68pt because `c3_tables` now
matches many more words and changes median ordering, not because of a broad
regression. Only `c5_graphics` remains a page-count mismatch (1→2).

The qualified conservative striped-table assembler makes
the `c3_tables` long table one editable 46-row × 4-column DOCX table, IDs 1–45
exactly once, and paginates it naturally without inventing a repeating header.
It also consolidates the 5-row `c1_whitepaper` comparison table. It rejects
ambiguous multiline content, cards, and callouts and coalesces pages only at an
edge with matching geometry; it does not claim to solve complex/nested regional
tables. Local LibreOffice review was indicative only; live Google evidence now
shows `c3_tables` 3→3 rather than 3→4, live 0.9226/doc recall 0.9359 unchanged,
word recall 0.3120→0.8215, within-2pt 0→0.1076, SSIM 0.5785→0.7573, and IoU
0.0973→0.1448. dy50/dy90 are 2.94→7.85pt and 80.52→103.34pt because the table
now matches many more words. Visual review found all 45 rows in an editable
continuous three-page table; row distribution differs from the source.
`c1_whitepaper` remains 2→2 with live/document/word recall
0.9654/0.9697/0.9697 and dy50/dy90 9.30/54.79pt unchanged; within-2pt,
SSIM, and IoU have tiny 0.0719→0.0688, 0.8006→0.7993, and 0.1568→0.1563
tradeoffs. PDFium preserves stretched literal interword spaces, removing the
`01_whitepaper_market` word staircase; shipping PyMuPDF output is unaffected.

That operational result remains unacceptable for release. A strict draft
`testkit/gdocs_quality_policy.json` now defines blocking ordinary documents,
tracked designed-stress documents, unsupported-input refusal, exact metrics,
and explicit owner ratification. The offline `assess` command hash-binds its
source evidence and never performs a cloud operation.

Applied to the latest Google evidence, operational pass remains true but quality
and overall pass remain false: the policy is unratified and 9/13 ordinary
fixtures meet every threshold. Seven blocking findings span four fixtures:
`01_whitepaper_market` SSIM; `c2_paper2col` dx/dy/SSIM; `c7_code` dx; and
`l1_word_native` dx/dy. The three stress fixtures produce nine additional
nonblocking findings. This is an actionable gap report, not release approval.

## Conversion safety, batch, and scan handling

Encrypted PDFs map to an unsupported-input error. Malformed or truncated PDFs
map to parse errors. Writer and refinement candidates remain private until DOCX
structural validation succeeds; only then is an existing destination replaced
atomically. Failures preserve existing bytes and do not leave predictable
adjacent `.best` artifacts.

The CLI keeps positional single-file conversion and adds deterministic serial
batch conversion: `exactdoc --input-dir pdfs --out-dir docx --recursive
--result-json batch.json`. It discovers PDFs case-insensitively, preserves
relative paths, avoids symlinks/output subtree, requires `--overwrite` for
existing outputs, and atomically publishes a privacy-safe result JSON. It caps
files at 500 documents, 250 pages/document, 2,000 pages/run, and 250 MiB/file.
`--workers` currently accepts only `1`; it does not pretend to parallelise.
Google cloud qualification is rejected for batches.

`--scan-only` and normal conversion use a conservative local detector. Only
high-confidence image-only scans are rejected as OCR-required; mixed documents
proceed and blank/digital/mixed are distinguished. No OCR engine is included.
All 16 frozen fixtures avoid false OCR-required classification.

## Verified local checks

The current working tree passes 67 native `unittest` tests (2 platform skips),
the batch suite (14 pass, 1 Windows symlink skip), corpus purity (16/16), the
no-PyMuPDF PDFium smoke check, atomic-output checks, and the 16-entry corpus
manifest check. These are local verification results, not canonical LibreOffice
or Google qualification evidence.

## Licensing and release strategy

The project is AGPL-3.0-or-later today. PyMuPDF is core, which is the current
licensing blocker. PDFium is optional and is the migration path, not proof that
the switch is ready.

Apache-2.0 is the preferred future target because its patent grant and
business-friendly terms better suit the intended distribution. It remains
contingent on removing PyMuPDF from the core/default path, expanded PDFium
parity and two clean Google passes, plus dependency/provenance/license audit
(including bundled PDFium dependencies) and appropriate legal review. This is
project strategy, not legal advice.

## Reproduce safely

```bash
bash scripts/bootstrap.sh --strict
python testkit/corpus_manifest.py verify
python testkit/runall.py
```

Use `testkit/runall.py --absolute` for release qualification, not the ordinary
regression check alone. Never re-record canonical numeric evidence from a local
machine or to silence a failure.
