# exactdoc v1.1 — independent test report

> **This is a frozen audit of v1.1 as it was found, not a description of the
> tool today.** It is kept because the defects it names are the reason for most
> of the architecture that followed, and because §6 is the plan that was then
> executed. Nearly every root cause in §2 has since been fixed, and the numbers
> in §1 are historical. Two claims here were later falsified by measurement and
> are marked inline.
>
> "v1.1" is a pre-release internal label from before this repository had
> versioned releases. It corresponds to no tag and no published artifact; the
> version line starts at `0.1.0a1` (see the README's Versions table). The
> 18-document corpus measured here is also not the current one — today's gate
> corpus is 16 generated documents.
>
> For current state: **[STATUS.md](STATUS.md)**. For the design: **[THEORY.md](THEORY.md)**.

18 documents, 4 producer engines, measured with `testkit/` (shares no code with
the converter). Every number below is reproducible via
`python testkit/runall.py testkit/adv my_samples exactdoc_v1.1/corpus/pdfs`.

---

## 1. Headline

The architecture is sound and the engineering is real. The tool is also
**over-fitted to one PDF producer**, and its own verification loop is
structurally unable to detect that.

| Producer dialect | Docs | Verdict |
|---|---|---|
| ReportLab | 6 | **Good.** Page counts match, 94–100% live text, median word drift 1–9pt |
| WeasyPrint | 1 (real) | **Good.** 10/10 pages, 98.2% live text, dy₅₀ 3.2pt |
| fpdf2 | 1 | **Good.** 100% live text, dy₅₀ 1.2pt |
| LibreOffice / Word-native | 1 | **Fair.** Page match, but dy₅₀ 13.3pt; only 1% of words within 2pt |
| **Chromium / Skia** | **9** | **Broken.** 5 of 9 wrong page count; one document rasterised 100% |

Chromium/Skia is the producer for *anything printed from a browser* — including
your own resume, and including HTML artifacts exported to PDF. It is the single
most likely input for the stated use case, and it was not in the corpus.

### Your two samples

| | Whitepaper (WeasyPrint) | Resume (Chromium) |
|---|---|---|
| Pages | 10/10 ✅ | 2/2 ✅ |
| Live (editable) text | 98.2% | **0.0%** |
| Words placed correctly | 98.5% | 0% |
| Images embedded | 4 | **2 — one per page** |
| Median vertical drift | 3.2pt | n/a |

The resume was converted into **two full-page pictures**. It *looks* right, and
it is not a document: no text, no editing, no reflow, 1 MB from a 152 KB source.

---

## 2. Root causes

### 2.1 Chromium's invisible page-background rectangle (critical)

`probe.py` on the resume shows drawing #0:

```
0 rect fill bbox=(42.8, 36.8, 552.8, 804.8) fill=#ffffff
```

Chromium paints an opaque white backdrop covering the page. It is invisible, but
`_clusters()` (infer.py:655) unions any two drawings whose boxes touch within
6pt — and the backdrop touches everything. All 13 drawings on the page collapse
into **one page-sized cluster**.

### 2.2 One bullet poisons a cluster

`_classify_cluster()` (infer.py:683):

```python
if any(d.shape in ("curve", "complex", "line") for d in ds):
    return "figure"
```

CSS `list-style: disc` bullets are emitted by Chromium as 3×3pt bezier circles,
i.e. `shape == "complex"`. A single bullet makes its whole cluster a "figure".
Combined with 2.1: the entire page becomes a figure and is rasterised.

### 2.3 `build_figure` grows without bound (critical)

infer.py:1029–1043 absorbs nearby text lines, six times:

```python
small = (lb[3]-lb[1]) <= 45 and (lb[2]-lb[0]) <= max(1.06 * (bb[2]-bb[0]), 60)
```

The width threshold is derived from the box **currently being grown**. Absorbing
a line widens `bb`, which loosens the threshold, which absorbs more lines. It is
positive feedback with no cap. Measured on `c2_paper2col.pdf`: a seed of two
hairline rules, 490×2pt, grew **103× in area** to 494×153pt and swallowed the
title block and abstract — exactly the 24% of text that stopped being live.

A horizontal rule spans the column, so `max(1.06 × 490, 60) = 519pt` — *every*
line on the page qualifies as "small".

### 2.4 Half-point font quantisation causes every paragraph to re-wrap

docxout.py:68:

```python
f.size = Pt(round(run.size * 2) / 2)
```

OOXML stores font size in half-points. The whitepaper's body text is **10.1pt**
and is emitted as **10.0pt** — 1% narrower glyphs, so ~1% more text fits per
line, so nearly every justified paragraph breaks differently.

Measured with `exp_sweep.py`, using line-break agreement (fraction of source
lines reproduced verbatim):

| Correction | line agreement |
|---|---|
| none (current) | **0.599** |
| narrow wrap width by `emitted_size / source_size` | **0.796** |
| narrow by a hand-tuned 0.8% | 0.820 |

The optimum narrowing found by sweep is ~0.8–1.0%, matching 10.0/10.1 = 0.990.
Line breaking is scale-invariant, so this is a principled fix, not a fudge.

This contradicts THEORY §8's framing of re-wrap as the fundamental limit. Most
of the observed re-wrap here is **not** the engine boundary — it is a
compensable unit-quantisation error.

### 2.5 The vertical budget over-allocates — and 2.3/2.4 were hiding it

Fixing either 2.3 or 2.4 *increases* the page count (whitepaper 10→11,
resume 2→3, c2 1→2). Losing text and wrapping too wide were compensating for a
vertical model that allocates too much height. Two bugs were cancelling, which
is why the tool scored better than it was.

This is aggravated by the "explicit page break per source page" design: with
zero slack, any positive height error spills a page.

### 2.6 77% of the residual vertical error is systematic

`drift_decomp.py` on the whitepaper, fitting a per-page affine trend to word drift:

```
mean |dy| = 4.01 pt  ->  after removing per-page affine trend: 0.93 pt
so 77% of the vertical error is systematic (fixable by a second pass)
```

Pages 8 and 9 are internally near-perfect (residual 0.54pt and **0.03pt**) but
sit 12pt too high as whole pages. That is one anchoring bug, not a layout
problem — and it is precisely what a closed-loop second pass removes.

### 2.7 Other confirmed defects

- **Letter-spacing collapses**: "TECHNICAL SKILLS" → "TECHNICALSKILLS".
  Tracking-spaced headings lose their inter-letter spaces.
- **Stat-card rows fail on rounded corners**: `_classify_cluster` requires
  `shape == "rect"`; `border-radius` makes them curves, so the three cards in
  `c1_whitepaper` stack diagonally instead of forming a row.
- **Nested tables flatten** with broken borders (`c3_tables`).
- **Table rows collapse inconsistently** — some rows split into cells, others
  keep all columns in cell 1 (`c1_whitepaper`).
- **Phantom striped rows** appear after the last row of a zebra table.
- **Alignment misdetection**: a bullet in the whitepaper appendix came out
  `align=right`.
- **Hanging list indents are per-item and noisy** — a numbered list renders with
  markers at three different x positions (whitepaper p8).
- **Mixed page geometry is discarded**: `DocLayout` takes `page_w/page_h` from
  page 1 (infer.py:1065). A portrait+landscape+A3 document emits **one section**
  at one page size. `edge_cases.py` confirms this.
- `make_corpus.py` contains mojibake — bullets are `â€¢`, a UTF-8/cp1252 slip.

### 2.8 Robustness

No crashes on empty, image-only, landscape, mixed-size, rotated, tiny-page or
dense-microtype inputs. Encrypted and truncated PDFs raise raw PyMuPDF
exceptions (`ValueError: document closed or encrypted`) — should be caught and
reported as a clean unsupported-input error.

---

## 3. The verification loop is the weakest part

You suspected this, and you were right. It is the highest-leverage thing to fix,
because every other improvement is gated on being able to detect it.

**1. The converter defines its own ground truth.** `verify.audit()` calls
`exactdoc.infer()`, then removes from the *source* side any text that landed
inside a region the converter decided to rasterise. On the resume it reports:

```
exactdoc self-audit : {'src_chars': 0, 'docx_chars': 0, 'text_coverage': 0.0}
```

Zero source characters — the document deleted itself from its own denominator.
Anything the converter turns into a picture is invisible to its own coverage
metric. Independent measurement gives `live_text_cov = 0.000`.

**2. SSIM rewards the failure.** The fully-rasterised resume scores 0.594 —
squarely inside the "0.71–0.94" band the README reports as success, and *higher*
than `c6_long` (0.365), which kept 100% of its text. SSIM cannot tell a document
from a photograph of a document.

**3. The corpus is one dialect, self-authored.** Five ReportLab files, generated
by the same process that was tuned against them. THEORY §7 correctly identifies
producer dialects as the central risk, then the corpus tests one of them.

**4. LibreOffice is an unvalidated proxy for Google Docs.** Every fidelity claim
is measured through LibreOffice; the product goal is Google Docs. The two
renderers disagree exactly where the design is riskiest (see §5).

**5. No regression gate.** THEORY §10 lists CI as future work; without it,
nothing prevents a dialect fix from silently breaking another dialect.

**6. Nothing measures editability.** There is no metric for "is this still a
document". Rasterisation is the tool's most damaging failure mode and its most
invisible one.

`testkit/` addresses all six. `runall.py` exits non-zero on gate failure; it
currently reports **7/13 pass**.

---

## 4. Is Python holding you back?

**No, and it isn't close.** The evidence:

- Conversion is 0.04–0.76s for 1–10 pages. Nothing is compute-bound.
- The hot paths are already C: PyMuPDF (MuPDF), NumPy, LibreOffice.
- Every defect in §2 is a *modelling* error — a wrong threshold, a missing
  backdrop filter, an unbounded loop, a unit-quantisation oversight. None gets
  easier in Rust or C++. §2.3 is an unbounded feedback loop; a faster language
  runs it faster.
- The fidelity ceiling is set by OOXML semantics and by Word/Docs layout
  behaviour, neither of which Python touches.

Two honest caveats, neither of which is about Python:

- **No language has a library that reproduces Word's line breaker.** uharfbuzz
  gives you shaped advance widths; HarfBuzz explicitly does not do line
  breaking, hyphenation, or justification. You would implement the break
  algorithm yourself, against measured Word/Docs behaviour, in whatever
  language. §2.4 shows you can get most of the way with pure arithmetic and no
  shaping at all.
- **PyMuPDF is AGPL-3.0**, which forces the repo to AGPL unless the parser moves
  to pypdfium2 + pdfplumber. ~~That is a licensing constraint, correctly
  identified in THEORY §10 — not a technical one.~~

  > **Falsified.** The backend was built. pypdfium2 extracts *exactly* —
  > baselines identical on 4,734 of 4,734 lines, paths 1.00×, text
  > character-identical — and still costs 7 placement regressions, because it
  > groups glyphs into lines and blocks differently and inference reads
  > grouping, not glyphs. pdfminer.six is worse still: 16% of characters and
  > 96% of vector paths lost on arXiv papers. The constraint is technical as
  > well as legal, and it is the single item still blocking Apache-2.0.
  > See STATUS.md D2.

The one language-adjacent thing worth changing is python-docx: most of
`docxout.py` is already raw lxml, so the dependency buys little.

---

## 5. Is a "perfect look" technically feasible?

Partly. The honest split:

### Achievable — currently blocked by bugs, not physics

Everything in §2. A text-flow document (whitepaper, research paper, report,
resume) can plausibly reach **95%+ of words within 2pt** and 1:1 pagination.
The prototype in §6 moves `c6_long` from 13 pages to 7 with a ~40-line change.

### Achievable with real work

- Re-wrap: §2.4 shows most of it is quantisation, not the engine boundary. The
  irreducible part — genuine disagreement between Word's and the source
  engine's line breakers — is real but is the *last* 20%, not the first.
- Per-page anchoring: §2.6, 77% removable by a second pass.

### Not achievable — state these as limits

1. **Pixel-perfect *and* editable is a contradiction.** The moment text reflows
   in a different engine, some line breaks differ, and everything below a
   changed break moves. You can make it rare; you cannot make it impossible.
2. **OOXML quantises font size to 0.5pt.** A 10.1pt source font cannot be
   emitted at 10.1pt. You can compensate the wrap width; you cannot remove the
   quantisation.
3. **Google Docs ignores embedded fonts.** Metric-compatible substitution is the
   ceiling. A document set in a font with no metric twin will not match.
4. **Google Docs flattens multi-section page geometry.** Docs keeps page setup
   from the first section and does not support per-section margins the way Word
   does. Your full-bleed cover-band design (README §3.5) depends on exactly this
   — *a mid-document section with different L/R margins*. It works in
   LibreOffice, which is what you tested. **This is the single most likely
   silent failure of the actual product goal, and it has never been measured.**
5. **Docs recomputes table column widths**, so `w:tblLayout fixed` is advisory.
6. **No paragraph-flow equivalent exists** for gradients, rounded corners,
   rotated text, or arbitrary vector art. These must rasterise — that is a
   format limit, correctly chosen.
7. **Scanned PDFs** need OCR; out of scope, correctly stated.

The good news from `ooxml_audit.py`: the emitted vocabulary is genuinely
conservative — **no VML, no text boxes, no floating frames, no anchored
drawings**. The "Docs-safe" claim holds at the construct level. The risk is
concentrated in `w:sectPr` (23 instances) and `w:cols`.

---

## 6. What I'd do, in order

### P0 — correctness (days). Chromium dialect + the runaway.

1. **Drop backdrop fills**: a near-white fill covering >60% of the page is not
   content.
2. **Reclassify bullet glyphs**: a filled, roughly square shape ≤9pt is a list
   marker, not a figure. Re-express it as a text marker span so the existing
   marker-merging path handles it.
3. **Bound `build_figure`**: freeze the absorption threshold at the *seed*
   width; cap growth (≤2.5× seed area, ≤35% of the page); require ≥2
   non-trivial graphic primitives before a cluster can be a figure at all.
   Never let a hairline rule seed one.
4. **Raster budget guard**: refuse any figure that would swallow more than N% of
   a page's text, and fall back to flow.

Measured effect of a prototype of 1+2 alone (`testkit/exp_chromefix.py`,
monkey-patched, nothing edited):

| Document | Before | After |
|---|---|---|
| `c6_long` | 13 pages, place 0.515, dy₅₀ 31.3pt, ssim 0.365 | **7 pages (correct), place 1.000, dy₅₀ 1.2pt, ssim 0.788** |
| resume | **0% live text**, 2 images | **99.4% live text, 0 images** |
| `c2_paper2col` | 76.1% live text | **99.7% live text** |
| ReportLab / WeasyPrint / fpdf2 / LO | — | **every metric unchanged — no regression** |

### P1 — fidelity (weeks)

5. Compensate half-point quantisation via wrap width (§2.4, +20pt line
   agreement). Land it **together with** 6, since it exposes the height bug.
6. Fix the vertical over-allocation surfaced by §2.5; add a per-page fit check
   that detects overflow before emitting.
7. **Closed-loop second pass** — the biggest architectural win. Today the
   verifier only reports. Make it correct: convert → render → fit per-page
   affine drift → re-emit with corrected `space_before`. §2.6 says this removes
   77% of residual vertical error, taking mean |dy| from 4.0pt to ~0.9pt. The
   loop already exists; it just isn't wired back in.
8. Letter-spacing reconstruction via `w:spacing` on `rPr` (§2.7).
9. Per-page section geometry for mixed orientation.
10. Rounded-rect cards, nested tables, phantom stripe rows.

### P2 — trust

11. Replace `verify.audit()` with independent measurement. Never let the
    converter define its own denominator.
12. **Build the Google Docs oracle.** Drive API: upload the DOCX, export back to
    PDF, diff against source. Until this exists, every fidelity claim about
    Google Docs is an extrapolation from LibreOffice. Given §5.4, this is not a
    formality — it is likely to find that the cover-band design does not
    survive.
13. Multi-producer CI with the gate in `testkit/runall.py`. Add LaTeX/pdfTeX and
    Typst dialects.

---

## 7. On publishing

The niche is real and THEORY §10 argues it well — pdf2docx is no longer actively
maintained by Artifex, and the ML converters (Docling, Marker, MinerU) all
target Markdown, discarding design by construction. "Preserves design, targets
Google Docs, proves it with a render-back diff" is genuinely unserved.

I would not publish before P0. A converter that turns a browser-printed resume
into two JPEGs will be the first issue filed, and the Chromium dialect is the
most common input on the internet.

Fix P0, wire in P1.7, ship the testkit as the test suite, and the honest-limits
section from §5 as the README's credibility anchor.

---

## Reproducing

```bash
python testkit/gen_corpus.py testkit/adv
```

```bash
python testkit/runall.py testkit/adv my_samples exactdoc_v1.1/corpus/pdfs
```

```bash
python testkit/exp_chromefix.py off testkit/adv my_samples && python testkit/exp_chromefix.py on testkit/adv my_samples
```

```bash
python testkit/exp_sweep.py my_samples
```

```bash
python testkit/drift_decomp.py my_samples/Whose-Voice-Is-This-Corpus-Written-In_Ebin-Babu-Thomas.pdf testkit/batch/rendered/Whose-Voice-Is-This-Corpus-Written-In_Ebin-Babu-Thomas.pdf
```
