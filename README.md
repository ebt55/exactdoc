# exactdoc

PDF to editable DOCX for ordinary digital documents: text reports, papers,
multi-column pages, common tables, and international text. This is an alpha;
use the measurements below rather than assuming every PDF dialect is supported.

## Current shipping profile

Shipping is quality-first:

```text
pymupdf/standard/libreoffice/refine3@240dpi
```

PyMuPDF is a core dependency. The `raw` comparison profile is the same
PyMuPDF/standard path with LibreOffice refinement disabled. PDFium is an
optional `[pdfium]` migration candidate, not the shipped backend.

The canonical LibreOffice regression record is not an absolute quality pass; it
asks whether a result got worse than its recorded value. The separate absolute
qualification still exposes known limitations.

| Profile | Page match | Mean within 2pt | Mean live text | Median dy50 |
|---|---:|---:|---:|---:|
| shipping product | 15/16 | 0.4981 | 0.9652 | 0.675pt |
| raw control | 13/16 | 0.3349 | 0.9652 | 2.2pt |

Current product limitations include `c3_tables` nested tables and rasterised
text regions (D10) in `c5_graphics` and `04_exec_brief`.

## Install and use

```bash
git clone https://github.com/ebt55/exactdoc && cd exactdoc
pip install -e ".[test]"
exactdoc report.pdf -o report.docx
```

The shipping correction loop uses LibreOffice. Conversion is local; it does not
upload a document. The API equivalent is:

```python
from exactdoc import convert

convert("report.pdf", "report.docx")
```

For the non-shipping PDFium candidate, install `.[pdfium]` and select an
explicit candidate profile in development tooling. It is not a release option.

Input errors are deliberately stable: encrypted PDFs report unsupported input;
malformed or truncated PDFs report parse errors. Failed input acquisition leaves
an existing destination untouched.

## PDFium/Google-Docs candidate

`PDFIUM_GDOCS_CANDIDATE` is explicitly non-shipping:

```text
pdfium/gdocs/none/refine0@240dpi
```

After the bounded bottom-margin correction it records 14/16 page match, 0.2429
within-2pt, 0.9568 live text, and 2.425pt median dy50. Its LibreOffice-refined
diagnostic records 15/16, 0.3381, 0.9568, and 2.06pt. Same-profile parity is 7
regressions, 7 same, and 2 better; the material regressions include ordinary
memo placement, complex scripts, and graphics. It is therefore neither adopted
nor releasable.

The bottom-margin change fixes the candidate's `c1_whitepaper` and
`c2_paper2col` overflow while preserving the other 12 page-matching documents.
Candidate page-count misses remain `c3_tables` (nested table) and
`c5_graphics` (designed graphics); these are stated limitations, not reasons to
silently change the shipping profile.

## Google Docs qualification

The packaged user CLI is `exactdoc-gdocs` (install `.[gdocs]`; for example,
`exactdoc-gdocs auth`). It handles authentication and attempts cleanup of Drive
objects; an orphan ledger blocks unsafe follow-on work and evidence avoids
credential data. Testkit qualification is intentionally separate and two-step:

```bash
python testkit/gdocs_oracle.py prepare <dir>
python testkit/gdocs_oracle.py run <dir> --allow-cloud-upload
```

`prepare` is offline and binds the exact candidate by hash. `run` is the only
operation that may upload, requires explicit consent, and reports operational
and quality verdicts separately.

The final live qualification on 2026-08-02 completed its operational work for
`pdfium/gdocs/none/refine0@240dpi`: all 16 documents were attempted and
succeeded, with zero failures, and cleanup left no `.gdocs_orphans.json`.
Targeted Google-Docs fixes improved page match from 12/16 to 14/16, median
dy50 from 6.07pt to 4.98pt, word recall from 0.8356 to 0.8745, SSIM from
0.7475 to 0.7767, and ink IoU from 0.1814 to 0.2108; mean within-2pt was
effectively flat (0.1391 to 0.1378) and mean live text remained 0.9568.
`01_whitepaper_market` now remains 3 pages and `04_exec_brief` 2 pages. The
remaining page-count misses are `c3_tables` and `c5_graphics`.

`c3_tables` needs a general cross-page table assembler: its alternating-fill
table is inferred before DOCX generation as fragmented 1x1/1x4 tables and
paragraphs. `c5_graphics` depends on gradients and rounded/rotated complex
graphics, a deliberately deferred designed-page limitation. PDFium also now
preserves stretched literal interword spaces, removing the visible word
staircase in `01_whitepaper_market`; the shipping PyMuPDF profile is unchanged.

This is an operational success, not an acceptable quality qualification.
`testkit/gdocs_quality_policy.json` is still missing, so `quality_pass` and
`overall_pass` are both false. The evidence must be reviewed before defining a
quality policy; the candidate remains non-shipping and non-releasable.

## Scope and limits

Priorities are ordinary digital text, multi-column documents, common tables, and
i18n. Heavy LaTeX, highly designed/vector pages, and nested tables remain
deferred. Scanned/OCR-only PDFs are unsupported.

Some designed regions are rasterised so the surrounding document stays editable;
the live-text metric counts that trade-off rather than hiding it.

## Licensing

exactdoc is [AGPL-3.0-or-later](LICENSE) today because PyMuPDF is core. The
project's preferred future target is Apache-2.0 for its patent grant and
business-friendly distribution model, but only after PDFium same-profile parity
and real Google Docs quality gates pass. PDFium is the migration path; it does
not yet unblock relicensing. This is project strategy, not legal advice.

## Verification

```bash
bash scripts/bootstrap.sh --strict
python testkit/corpus_manifest.py verify
python testkit/runall.py
python tests/test_gate_mutations.py
```

See [STATUS.md](STATUS.md) for the measured state and defects, and
[ROADMAP.md](ROADMAP.md) for sequencing.
