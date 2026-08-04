# exactdoc

**exactdoc converts PDFs into editable DOCX files that look like the original.**

Most PDF→Word converters give you either a pile of text boxes frozen at absolute
positions (looks right, unusable to edit) or reflowed text that has lost the
layout (editable, looks wrong). exactdoc aims at both at once for ordinary
digital documents: it infers the *semantic* structure — margins, paragraphs,
headings, lists, tables, multi-column sections, headers/footers, hyperlinks —
and writes real flowing Word constructs whose rendered geometry matches the
source page to within points, verified by measurement.

This is an alpha. Every claim below is measured against a frozen 16-document
corpus; use those measurements rather than assuming every PDF dialect works.

## What it does

- **Editable output, not text boxes.** Paragraphs are real paragraphs with
  correct spacing, indents, alignment and line leading; tables are real DOCX
  tables; lists keep their markers; hyperlinks and internal TOC links stay live.
- **Measured fidelity.** A closed refinement loop renders the produced DOCX
  back to PDF (LibreOffice headless by default), compares word positions
  against the source, and corrects page overflow and per-page offsets. The
  test harness reports word recall, horizontal/vertical drift percentiles,
  SSIM and ink IoU per document.
- **Honest degradation.** Designed regions it cannot represent as flowing text
  (gradient graphics, rotated art) are rasterised so the rest of the document
  stays editable — and the live-text metric counts that trade-off instead of
  hiding it. Image-only scans are rejected with an explicit OCR-required error
  rather than silently converted to blank output.
- **Two parser backends.** PyMuPDF (core, shipping) and PDFium via pypdfium2
  (optional `[pdfium]`, migration candidate). Shared inference contains no
  backend conditionals; a parity harness compares the two.
- **A Google Docs output profile.** `output_profile="gdocs"` writes OOXML that
  survives Google Docs' importer (which mistranslates exact line heights,
  ignores cell margins in places, and inserts extra paragraph spacing) using a
  static, offline translation layer — no upload required.

## Install

```bash
git clone https://github.com/ebt55/exactdoc && cd exactdoc
pip install -e .            # core (PyMuPDF backend)
# optional extras:
pip install -e ".[pdfium]"  # PDFium backend (migration candidate)
pip install -e ".[gdocs]"   # exactdoc-gdocs CLI (Google auth + qualification)
pip install -e ".[test]"    # test/measurement toolkit
```

The refinement loop uses LibreOffice headless (`soffice`) if present.
Conversion is local; nothing is uploaded.

## Usage

```bash
exactdoc report.pdf -o report.docx
```

```python
from exactdoc import convert

convert("report.pdf", "report.docx")

# Google-Docs-safe OOXML, still fully offline:
convert("report.pdf", "report.docx", output_profile="gdocs", oracle="none",
        refine_rounds=0)
```

Batch conversion over folders is deterministic and safe to re-run:

```bash
exactdoc --input-dir pdfs --out-dir docx --recursive --result-json batch.json
```

Use `--continue-on-error`, `--overwrite`, or `--scan-only` as appropriate.
Discovery is case-insensitive and preserves relative paths; existing outputs
require `--overwrite`; batch runs are serial today (`--workers` must be `1`).
Limits are 500 documents, 250 pages/document, 2,000 pages/run, 250 MiB/file.
Result JSON is atomically published and contains only relative paths, safe
errors, hashes, counts and options.

Input errors are deliberately stable: encrypted PDFs report unsupported input;
malformed or truncated PDFs report parse errors; high-confidence image-only
scans exit with an explicit OCR-required code (17, or 18 for partial batch
failures). Output publication is transactional: candidates stay private until
structural DOCX validation succeeds, then replace the destination atomically —
a failed conversion never corrupts an existing output.

## What to expect (quality examples)

Typical results from the measured corpus, described rather than screenshotted:

- **A three-page business whitepaper** (cover band, headings, callout boxes,
  a bar chart, numbered and bulleted lists, footer with page numbers) converts
  to a fully editable document: the coloured cover band is a real table with
  live text, the chart is rasterised in place, callouts keep their tinted
  backgrounds and border bars, and body text lands within ~1–2pt of the
  source. You can retitle the cover and re-wrap paragraphs like any Word file.
- **A two-column academic paper** with an inset abstract keeps its two-column
  section: column boundaries, the abstract inset, superscripts and references
  survive, and the column geometry is inferred from the page itself — no
  template assumptions.
- **A technical report with code blocks** keeps code as monospace text in
  shaded single-cell tables with preserved indentation — editable, not an
  image.
- **A 45-row striped table** spanning three pages becomes one continuous
  editable DOCX table with every row present exactly once, paginating
  naturally.
- **An international text page** (CJK, Cyrillic, Greek, accented Latin)
  retains live, correctly positioned text through metric-compatible font
  mapping.

## Limitations, in tiers

**Tier 1 — works today (the target class).** Ordinary digital documents:
reports, memos, letters, whitepapers, academic papers, multi-column pages,
common (striped/ruled) tables, code listings, headers/footers, hyperlinks and
TOC links, most Latin/CJK/Cyrillic text. This is what the corpus measures and
the numbers below describe.

**Tier 2 — partially supported, measured limitations.**

- *Complex and nested tables*: regional/nested table layouts are deferred;
  only conservative, strongly-evidenced striped tables are assembled.
- *Designed/vector-heavy pages*: gradients, rounded and rotated artwork are
  rasterised regions inside an otherwise-editable document, not recreated
  vector art (`c5_graphics`, parts of `04_exec_brief`).
- *Google Docs as the renderer*: the offline `gdocs` profile compensates for
  measured importer quirks (line-height mistranslation, ignored cell margins,
  per-boundary spacing), but Docs fidelity currently trails LibreOffice/Word
  fidelity and is qualified separately.

**Tier 3 — explicitly out of scope for now.**

- *Heavy LaTeX/mathematics*: stacked scripts and equation layout are not
  reconstructed as editable math.
- *Highly designed pages* (magazine spreads, posters): not representable as
  flowing Word constructs; expect rasterised regions at best.
- *RTL scripts* (Arabic, Hebrew): waiting on a logical-Unicode-ordering
  contract; not converted correctly today.
- *Scanned / image-only PDFs*: rejected with an explicit OCR-required error.
  No OCR engine is bundled — by design, a wrong-but-confident transcription is
  worse than an honest refusal.

## Measured state

Shipping profile (quality-first): `pymupdf/standard/libreoffice/refine3@240dpi`.
`raw` is the same path with refinement off. Canonical figures come from the
pinned Linux/LibreOffice CI environment:

| Canonical profile | Page match | Mean within 2pt | Mean live text | Median dy50 |
|---|---:|---:|---:|---:|
| product | 16/16 | 0.5161 | 0.9652 | 0.675pt |
| raw | 14/16 | 0.3349 | 0.9652 | 2.79pt |

Measured 2026-08-04, both lanes PASS. The regression record asks "did anything
get worse?", not "is everything perfect"; the absolute qualification still
exposes the Tier 2/3 items above.

A separate, deliberately **non-gating** corpus of 16 further ordinary documents
lives in `testkit/fixtures_expansion/`. It is measured by `testkit/expansion.py`,
has no baseline, and gates nothing — see [docs/corpus-expansion.md](docs/corpus-expansion.md).
Its first run found that running headers, footers and browser page furniture
dominate the geometry error in ordinary documents, a construct the frozen 16
barely sample.

### PDFium / Google Docs candidate — not shipping

`pdfium/gdocs/none/refine0@240dpi` is the explicit non-shipping migration
candidate. Its latest consented live Google qualification (2026-08-04) was
operationally successful — 16/16 documents attempted and succeeded, zero
failures, zero orphaned Drive objects — and **fails the draft quality policy:
11 blocking findings across 8 of the 13 `ordinary_digital` fixtures**, so 5 of
13 clear every threshold. The 3 `designed_stress` fixtures produce 9 further
findings, tracked and non-blocking. The policy is also still a draft, which
cannot pass by construction whatever the numbers say.

Two previously blocking findings cleared live: `c7_code` horizontal drift and
`c2_paper2col` horizontal drift. What replaced them is a broader set of
**vertical** drift blockers — `03_tech_report_code`, `c1_whitepaper`,
`c2_paper2col`, `c6_long`, `c8_toc_links`, `l1_word_native` and
`r1_reportlab_report` all exceed the draft 10pt `dy_p50` bar — plus SSIM on
`01_whitepaper_market`, `c2_paper2col` and `c6_long`, and horizontal drift on
`l1_word_native`. **The cause is under investigation** and is not settled here;
a per-boundary spacing compensation is one line of enquiry, not a conclusion.
Fixing a horizontal defect and surfacing a vertical one is the ordinary shape
of this work, and the honest reading is that the blocking count went up.

One parser fix has landed since that live run and has **not** been re-measured
against Google: `c1cbc2a` absorbs a superscript into its host line, which moved
`c2_paper2col` substantially on the LibreOffice proxy. The live findings above
stand until a fresh consented run replaces them.

Same-profile PDFium/PyMuPDF parity is 7 regressions, 6 same, 3 better as raw
measurement; adjudicated against the profile-bound policy that is no unwaived
regressions and two tracked provisional findings. The candidate is neither
adopted nor releasable, and the policy will not be ratified merely to turn the
gate green. See [STATUS.md](STATUS.md) for the full numbers.

Google qualification is separate, two-step and consent-gated:

```bash
python testkit/gdocs_oracle.py prepare <dir>              # offline, hash-binds the candidate
python testkit/gdocs_oracle.py run <dir> --allow-cloud-upload   # the only step that uploads
python testkit/gdocs_oracle.py assess <gdocs_qualification.json> # re-assess without uploading
```

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

See [STATUS.md](STATUS.md) for the measured state and defects,
[ROADMAP.md](ROADMAP.md) for sequencing, and [THEORY.md](THEORY.md) for the
laws the codebase is built around.
