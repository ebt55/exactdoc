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
- **Two parser backends.** PDFium via pypdfium2 (core, shipping) and PyMuPDF
  (optional `[mupdf]`, the reference arm every parity record is measured
  against). Shared inference contains no backend conditionals; a parity harness
  compares the two. A default install contains no AGPL code.
- **A Google Docs output profile.** `output_profile="gdocs"` writes OOXML that
  survives Google Docs' importer (which mistranslates exact line heights,
  ignores cell margins in places, and inserts extra paragraph spacing) using a
  static, offline translation layer — no upload required.

## Install

```bash
git clone https://github.com/ebt55/exactdoc && cd exactdoc
pip install -e .            # core (PDFium backend) — no AGPL code
# optional extras:
pip install -e ".[mupdf]"   # PyMuPDF reference backend — AGPL-3.0, see Licensing
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
  measured importer quirks (line-height mistranslation, ignored cell margins),
  but Docs fidelity currently trails LibreOffice/Word fidelity and is qualified
  separately. A per-boundary spacing compensation was also applied and has been
  **retired** — remeasurement against Google's own exports put Docs' boundary
  contribution at about +0.1pt, so the compensation was subtracting space Docs
  never added.

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

A separate, deliberately **non-gating** corpus of 21 further documents — 16
generated, 5 real documents this project did not write — lives in
`testkit/fixtures_expansion/`. It is measured by `testkit/expansion.py`, has no
baseline, and gates nothing; see
[docs/corpus-expansion.md](docs/corpus-expansion.md). It is already earning its
keep, and not flatteringly:

- running headers, footers and browser page furniture dominate the geometry
  error in ordinary documents — a construct the frozen 16 barely sample;
- **long documents double their pagination.** An 80-page real document came out
  158 pages and a 114-page one came out 314. Document recall stays around
  0.90 while word recall collapses to ~0.13, because everything after the first
  overflow lands on the wrong page. The gated 16 are 1–7 pages and cannot
  compound a per-page error into a page-count error, so no gated number has ever
  moved in response to this;
- a 199-widget fillable form classified `unsupported` **converted anyway**: the
  page and byte ceilings are enforced, but nothing rejects interactive form
  logic.

### PDFium / Google Docs candidate — not shipping

`pdfium/gdocs/none/refine0@240dpi` is the explicit non-shipping migration
candidate. **Four** consented live Google qualifications ran on 2026-08-04, all
operationally successful — 16/16 documents attempted and succeeded, zero
failures, zero orphaned Drive objects — with blocking quality findings falling
**11 → 4 → 3 → 1** across the day. The vertical-drift blockers were a 3pt
per-boundary spacing compensation, retired after remeasurement against Google's
own exports put the real figure near +0.1pt; `l1_word_native` horizontal drift
was a font-substitution error, fixed by adopting Libre Baskerville from
Docs-measured metrics (39.82 → 1.35pt); `c2_paper2col` cleared its similarity
bound on a scoped section-break compensation (0.6772 → 0.7087).

Twelve of the thirteen blocking fixtures now clear every threshold unaided. The
thirteenth, `01_whitepaper_market`, misses only structural similarity, because
Google Docs adds space above a page-leading cover band unconditionally — probe
measured, an addition rather than a clamp, and the writer already compensates
what is compensable. The quality policy has been **ratified** with a single
bounded waiver for exactly that metric on exactly that document, floored just
below the measured value, and it retires itself: if `01` reaches the bar unaided
the waiver goes stale and blocks until it is deleted.

Assessed against the fourth pass, the ratified policy returns `overall_pass:
true` with zero blocking findings. **That is one clean pass. The migration gate
asks for two, and the second must be a fresh consented run** — so this is
progress toward a decision, not a release.

Same-profile PDFium/PyMuPDF parity is 7 regressions, 6 same, 3 better as raw
measurement; adjudicated against the profile-bound policy that is no unwaived
regressions and two tracked provisional findings, neither of them ratified —
that is a separate file and a separate decision from the Google Docs quality
policy above. The candidate is neither adopted nor releasable, and no policy
here gets ratified merely to turn a gate green. See [STATUS.md](STATUS.md) for
the full numbers.

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

[docs/license-audit.md](docs/license-audit.md) is the first pass at that audit:
every dependency licence read from installed metadata, the 16 components inside
the PDFium binary, the redistribution basis of all 47 committed corpus PDFs, and
the four migration gates as a live status table. Its finding is that PyMuPDF is
the only code-licence blocker in the dependency graph — which narrows the work
without doing it.

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
