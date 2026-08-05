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

### The specific ones, with numbers

Generated from the ratified quality policy and the live pass-7 evidence rather
than from recollection. Where a number is quoted it is measured.

**Long, dense, multi-column documents inflate their page count — badly.** This
is the largest known defect and it is not subtle. Real published documents,
measured on the non-gating expansion corpus: an 80-page NIST publication comes
out at 106 pages, a 114-page one at 161, a 126-page IRS instruction booklet at
337. Document recall stays around 0.90 while word recall collapses toward
0.11–0.24, because everything after the first overflow lands on the wrong page
and stops matching. The gated corpus is 1–7 pages and cannot compound a per-page
error into a page-count error, which is exactly why this class is measured
separately. **If your documents are long dense booklets, this release is not for
them yet.** Tracked as the headline post-release item (n-column reconstruction).

**Interactive forms are refused, by contract.** A fillable AcroForm whose
content lives in its field values converts to a convincing-looking non-form —
measured at 0.085 SSIM on IRS Form 1040 while exiting zero, which is worse than
failing. `InteractiveFormError`, **exit code 19**. The threshold is a per-page
widget census: a page is a form page at 12+ widgets and the document is a form
when form pages are a tenth of it.

**There is a page cap, and it is a decision you can make.** 250 pages by
default. Over it, `PageLimitError`, **exit code 20** — the one resource refusal
you can answer: `--max-pages N` raises it, `--max-pages 0` removes it. Its own
exit code rather than a generic resource error precisely because it is
answerable.

**Image-only scans are refused.** `OcrRequiredError`, **exit code 17**. No OCR
engine is bundled.

**Google Docs adds about 14.6pt of white above a page-one cover band, and we
cannot remove it.** Probe-measured on Docs itself: requested top margins of
0/4/8/14.4/20pt render as 14.55/18.83/22.83/29.23/34.83 — an *addition*, not a
clamp, so no requested value reaches the paper edge. The writer compensates what
is compensable and accepts the floor. It costs `01_whitepaper_market` structural
similarity (mean_ssim 0.6909 against a 0.70 bar) and that document carries a
bounded, self-retiring waiver in the ratified policy. Side margins, by contrast,
Docs honours exactly, so a true side bleed is reachable and is used.

**Small residual drift on cover-heavy pages.** After the band itself is placed
correctly, a rasterised figure region can render a few points taller than its
source (measured +5.91pt on `c1_whitepaper`'s merged stat-card row), and the
error accumulates gently down a dense page. `c1_whitepaper` lands at dy_p50
5.56pt live against a 10.0pt bound — inside, and not zero.

**Page-top spacing after a hard break.** Renderers drop `w:spacing w:before` at
the top of a page following a hard break, so a paragraph that should start low
on a fresh page starts flush. Measured at −53pt on one gated document's page 2.
Emitting an explicit spacer paragraph is the shape of the fix; it is not done.

**Designed/vector pages score poorly and that is the honest outcome.**
`c5_graphics` is a page out and recalls 17% of its words, because the page *is*
artwork: the text is inside rasterised regions and counted as non-live by
design. It sits in the policy's non-blocking `designed_stress` tier for that
reason, not as an excuse.

**The `[mupdf]` extra changes nothing about output.** Both installs produce
identical DOCX content on all 16 gated fixtures, proven by content hash. It
exists only for the legacy PyMuPDF parser path and as the reference arm for
parity measurement — and it is AGPL-3.0-or-later, so installing it changes your
obligations for anything you distribute.

## Measured state

Shipping profile (quality-first): `pdfium/standard/libreoffice/refine3@240dpi`.
`raw` is the same path with refinement off. Canonical figures come from the
pinned Linux/LibreOffice CI environment:

| Canonical profile | Page match | Mean within 2pt | Mean live text | Median dy50 |
|---|---:|---:|---:|---:|
| product | 16/16 | 0.5241 | 0.9588 | 1.15pt |
| raw | 15/16 | 0.3471 | 0.9588 | 1.95pt |

Measured 2026-08-06, both lanes PASS. The regression record asks "did anything
get worse?", not "is everything perfect"; the absolute qualification still
exposes the Tier 2/3 items above.

**These numbers moved when the default parser did, and slightly for the worse.**
The baseline was re-recorded because `profile_id` changed from `pymupdf/…` to
`pdfium/…`, which makes the old record a description of a configuration nothing
ships. Every one of the 32 per-document movements reproduces
`docs/evidence/parity-expanded-2026-08-05f.json` — measured and ratified
*before* the swap — to the recorded digit, and a control run confirmed the old
parser still reproduces the old record exactly from this tree, so the movement
is the parser and nothing else. See
[docs/evidence/parser-default-flip-2026-08-06.json](docs/evidence/parser-default-flip-2026-08-06.json).

**These figures describe every install.** They did not for one day: the
measurement environment carries the `[mupdf]` extra for the parity reference
arm, the quality ladder needed that extra to shape text, and a default install
therefore ran an inert ladder and produced worse output on `c1_whitepaper`,
`l1_word_native` and `c4_i18n`. `exactdoc/metrics.py` now ships the published
Adobe AFM widths, so both installs shape text with the same tables — verified by
converting all 16 fixtures in a virtualenv that never had PyMuPDF and comparing
the DOCX content hash against the measurement environment's. Identical on all
16, so `profile_id` needs no text-metrics term. See
[docs/evidence/permissive-shaper-2026-08-06.json](docs/evidence/permissive-shaper-2026-08-06.json).

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

### The Google Docs profile — measured live, still not the shipping profile

`pdfium/gdocs/none/refine0@240dpi`. The parser in that name is now simply the
default; what still makes this profile non-shipping is the pair of axes after
it — Google-safe serialisation with the correction loop off.

**Four** consented live Google qualifications ran on 2026-08-04, all
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
true` with zero blocking findings, and a second fresh consented run made two
clean passes — which is what the migration gate asked for.

Same-profile PDFium/PyMuPDF parity is **ratified and closed**
([docs/evidence/parity-expanded-2026-08-05f.json](docs/evidence/parity-expanded-2026-08-05f.json)),
which is what let the parser default change. Four findings sit at the shipping
profile — `02_research_paper` and `03_tech_report_code` (within-2pt and drift),
`r1_reportlab_report` (within-2pt), and `c4_i18n` (complex-script runs becoming
raster, a D10 shortfall). Those four are why the gate baseline moved, and all of
them were measured and adjudicated *before* the swap, against Google's own
exports rather than the LibreOffice proxy. **No policy here was ratified merely
to turn a gate green**, and a ratified finding is not a fixed one: each stays
floored in both directions, and clearing one entirely still fails as a stale
record. See [STATUS.md](STATUS.md) for the full numbers.

Google qualification is separate, two-step and consent-gated:

```bash
python testkit/gdocs_oracle.py prepare <dir>              # offline, hash-binds the candidate
python testkit/gdocs_oracle.py run <dir> --allow-cloud-upload   # the only step that uploads
python testkit/gdocs_oracle.py assess <gdocs_qualification.json> # re-assess without uploading
```

## Licensing

**exactdoc is [Apache-2.0](LICENSE).** A default `pip install exactdoc` resolves
eight packages and none of them carries a copyleft term — the shipping PDF
parser is PDFium via pypdfium2 (Apache-2.0/BSD-3).

**The optional `[mupdf]` extra pulls in PyMuPDF, which is AGPL-3.0-or-later.**
Installing it changes your obligations for anything you distribute. Nothing
installs it for you, nothing needs it to convert a PDF, and **it does not change
the output**: it exists solely as the independent reference arm every parity
measurement is written against. Asking for `backend="pymupdf"` without it raises
a typed error naming it rather than failing obscurely.

It briefly did change the output. The quality ladder shapes text, the only
shaper was MuPDF's base-14 tables, and that made the extra a quality axis. The
tables are published Adobe AFM data, so `exactdoc/metrics.py` now carries them
(from reportlab's BSD-3 copy, generated by `testkit/gen_base14_widths.py`) and
the axis is gone.

That distinction is verified rather than asserted. `tests/test_no_pymupdf.py`
makes `fitz` unimportable and converts the corpus through the shipping profile
anyway, and
[docs/evidence/base-wheel-proof-2026-08-06.json](docs/evidence/base-wheel-proof-2026-08-06.json)
goes further: it builds the wheel, installs it into a virtualenv that never had
PyMuPDF, and records the package list, the conversions and the test run there.
[docs/evidence/permissive-shaper-2026-08-06.json](docs/evidence/permissive-shaper-2026-08-06.json)
then closes the one cost that proof found, and shows the two installs producing
identical DOCX content on all 16 fixtures.

[docs/license-audit.md](docs/license-audit.md) is the audit the switch rests on:
every dependency licence read from installed metadata, the 16 components inside
the PDFium binary (including the AGG 2.3-vs-2.4 question, which had to be
checked rather than recalled), the redistribution basis of every committed
corpus PDF, and the four migration gates. **Its open items did not close with
the migration** — in particular the provenance of the source itself, and legal
review of the corpus bases — and neither did the fact that this is engineering
work rather than legal advice. Sole authorship removes no third-party
obligation.

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
