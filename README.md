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

Current product limitations include complex/nested table layouts and rasterised
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
malformed or truncated PDFs report parse errors. Writer and refinement
candidates stay private until structural DOCX validation succeeds, then replace
the public destination atomically; failures preserve existing bytes and leave no
predictable adjacent `.best` artifact.

For folders of PDFs, the backward-compatible CLI also supports deterministic
batch conversion:

```bash
exactdoc --input-dir pdfs --out-dir docx --recursive --result-json batch.json
```

Use `--continue-on-error`, `--overwrite`, or `--scan-only` as appropriate.
Discovery is case-insensitive and preserves relative paths; existing outputs
require `--overwrite`. Batch runs are intentionally serial today (`--workers`
must be `1`); Google cloud qualification is not a batch operation. Result JSON
is atomically published and contains only relative paths, safe errors, hashes,
counts, and options. Limits are 500 documents, 250 pages/document, 2,000
pages/run, and 250 MiB/file.

The local scan detector refuses only high-confidence image-only scans with an
explicit OCR-required error (exit 17, or 18 for a batch with OCR-required or
other partial failures). Mixed and digital PDFs proceed; blank PDFs are
distinguished. No OCR engine is bundled.

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

The latest live qualification on 2026-08-02 completed its operational work for
`pdfium/gdocs/none/refine0@240dpi`: 16 documents attempted, 16 succeeded, zero
failed, with no `.gdocs_orphans.json` after cleanup. Against the prior live
candidate, page-count match improved 14/16→15/16, mean word recall
0.8745→0.9064, SSIM 0.7767→0.7878, and ink IoU 0.2108→0.2138; mean live text
remained 0.9568 and mean within-2pt was 0.1378→0.1443. Median dy50 is
4.98→6.68pt because `c3_tables` now matches many more words and changes the
median ordering, not because of a broad regression. The only page-count mismatch
is the deferred `c5_graphics` (1→2).

The qualified candidate adds a conservative ordinary striped-table
assembler. It makes the `c3_tables` long table one editable 46-row × 4-column
DOCX table, with IDs 1–45 exactly once, and lets it paginate naturally without
inventing a repeating header the source does not contain. It also consolidates
`c1_whitepaper`'s 5-row comparison table. It accepts only strong striped-table
evidence and rejects ambiguous multiline content, cards, and callouts; pages
are coalesced only at a page edge with matching geometry. Complex/nested
regional tables remain outside this narrow fix. `c5_graphics` depends on
gradients and rounded/rotated complex graphics and remains deliberately
deferred. PDFium also now preserves stretched literal interword spaces, removing
the visible word staircase in `01_whitepaper_market`; shipping PyMuPDF is
unchanged.

Local LibreOffice review was indicative only; the live Google result is now
available. `c3_tables` is 3→3 rather than 3→4, with live text 0.9226 and
document recall 0.9359 unchanged, word recall 0.3120→0.8215, within-2pt
0→0.1076, SSIM 0.5785→0.7573, and IoU 0.0973→0.1448. Its dy50/dy90 are
2.94→7.85pt and 80.52→103.34pt because the continuous table matches many more
words. Visual review found all 45 table rows, editable in one continuous table
across three pages, though their page distribution differs from the source.
`c1_whitepaper` remains 2→2 with live/document/word recall 0.9654/0.9697/0.9697
and dy50/dy90 9.30/54.79pt unchanged; within-2pt, SSIM, and IoU have tiny
0.0719→0.0688, 0.8006→0.7993, and 0.1568→0.1563 visual tradeoffs.

This is an operational success, not an overall quality-gate pass. A strict draft
v2 policy now separates 13 blocking `ordinary_digital` fixtures from three
nonblocking `designed_stress` fixtures and keeps unsupported inputs out of cloud
qualification. Existing evidence can be reassessed without another upload:

```bash
python testkit/gdocs_oracle.py assess <gdocs_qualification.json>
```

The current offline assessment is operationally valid but fails quality: the
policy is deliberately unratified, and only 9/13 ordinary fixtures meet every
draft threshold. Blocking findings are `01_whitepaper_market` SSIM;
`c2_paper2col` horizontal/vertical drift and SSIM; `c7_code` horizontal drift;
and `l1_word_native` horizontal/vertical drift. The candidate therefore remains
non-shipping and non-releasable; the policy must not be ratified merely to turn
the gate green.

## Scope and limits

Priorities are ordinary digital text, multi-column documents, common tables, and
i18n. Proven PDF annotations and internal TOC navigation are next, followed by
heading/list semantics; RTL waits for a logical-Unicode-ordering contract. Heavy
LaTeX, highly designed/vector pages, and complex/nested tables remain deferred.
Scanned/OCR-only PDFs are explicitly unsupported rather than silently converted
to blank output.

Some designed regions are rasterised so the surrounding document stays editable;
the live-text metric counts that trade-off rather than hiding it.

## Licensing

exactdoc is [AGPL-3.0-or-later](LICENSE) today because PyMuPDF is core. The
preferred future target is Apache-2.0, but not yet: PyMuPDF must first be absent
from the core/default path, and the project needs a dependency, provenance, and
license audit (including bundled PDFium dependencies). pypdfium2/PDFium are
liberally licensed, but that alone does not settle distribution obligations.
The author being the sole project author does not remove third-party obligations.
This is project strategy, not legal advice.

## Verification

```bash
bash scripts/bootstrap.sh --strict
python testkit/corpus_manifest.py verify
python testkit/runall.py
python tests/test_gate_mutations.py
```

See [STATUS.md](STATUS.md) for the measured state and defects, and
[ROADMAP.md](ROADMAP.md) for sequencing.
