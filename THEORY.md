# exactdoc — Theory & Findings

How to convert a PDF to a DOCX that opens in Google Docs looking like the
original — what worked, what didn't, and where the ceiling is.

> **Scope.** This is the *design* document: the model, the reasoning, the dead
> ends. For where the converter currently stands — measured fidelity, the
> defect register, what is pending — see **[STATUS.md](STATUS.md)**, which is
> the authority on numbers. Several claims below were later falsified by
> measurement; each is marked inline rather than deleted, because the wrong
> turn is part of the record.

Everything here was established empirically with a **render-back verification
loop**: convert the DOCX back to PDF (LibreOffice headless), image-diff every
page against the source (SSIM + mean absolute difference), and measure
line-by-line vertical drift by matching text lines between the two PDFs.
No fix below was accepted on theory alone; each one moved a measured number.

---

## Addition, 2026-07-30 — two things the permissive-parser port taught

Both were learned the expensive way during the pdfium convergence work, and both
generalise beyond it. Recorded here so a future session does not re-derive them.

### The renderer normalises whatever it is free to normalise

Three separate changes made the pdfium IR structurally identical to PyMuPDF's —
span boundaries, injected whitespace, trailing spaces — and **all three moved
`within2pt` by exactly zero.** The third explained the other two: in justified
text the renderer redistributes inter-word space to fill the measure, so the
*number of spaces in the source has no bearing on where words land*.

The general form: **a difference the renderer is free to normalise cannot show
up in a placement metric, however wrong it looks in the IR.** Whitespace,
run-splitting and span segmentation are all in that category for justified text.
This is not a reason to leave them wrong — the DOCX carries the text a user will
read and edit, and `live_text_cov` strips whitespace so it cannot see the
difference — but it *is* a reason not to expect them to move the gate, and a
reason to check which category a defect is in before spending a session on it.

### Anchor everything on baselines, including the page origin

§3.1 established that vertical placement is anchored on baselines because line
boxes are unreliable. That principle was applied to paragraphs and not to the
page: `infer()` still derives `margin_t` from the topmost line's box *top*.

Line-box height turns out to be the single least portable quantity in the whole
model. Two correct parsers disagree about it because each reads it from font
metric tables the other does not have — PyMuPDF puts Helvetica's box 1.075× the
type size above the baseline, pdfium 0.905×, and on Symbol, where both fall back
to the *embedded* font's metrics, they agree to three decimals. That difference
propagates into the page origin and displaces every word on the page by a
constant.

Completing the principle — deriving the origin from
`baseline − (leading − 0.21·size)` like everything else — was tried and
**reverted**. It reached exact backend agreement on 14 of 16 documents and still
made the *default* backend worse, because `space_before` is computed against the
running position and is therefore calibrated on the old origin. The lesson is
not "baselines were the wrong idea"; it is that **the vertical model is a chain,
and half-converting a chain desynchronises it.** Doing it properly means moving
the origin, `_para_box` and the spacing chain in one change — recorded in
[ROADMAP.md](ROADMAP.md) as the open item it is.

---

## 1. The problem

A PDF is a *painting*: absolutely positioned glyphs, paths and images with no
semantics. A DOCX is a *program*: a flow of paragraphs, tables and sections
that a renderer lays out again from scratch. Conversion is therefore
**decompilation** — recovering the program that would repaint the same page.

Existing tools fail in characteristic ways:

- **pdf2docx** — table-centric heuristics; drops or mangles decorative
  vectors (bands, callout boxes, rules), crude font mapping, no verification.
- **LibreOffice PDF import** — every line becomes an absolutely positioned
  frame: looks right, edits terribly, and Google Docs mangles frames.
- **Word's own PDF reflow** — reasonable text, but it *redesigns* the page.
- **ML converters (marker, docling, nougat)** — target markdown; design is
  discarded by construction.

The extra constraint here: output had to open in **Google Docs** with the
design intact. That kills the easiest high-fidelity trick (absolutely
positioned text boxes) because Docs breaks floating text boxes on import, and
it ignores embedded fonts. So the entire document must be rebuilt from a
**Docs-safe vocabulary**: styled paragraphs, fixed-layout tables with per-side
borders and shading, section geometry, true column sections, inline images,
headers/footers with fields, tab stops, hyperlinks. Nothing else.

## 2. Architecture

```
PDF ─parse─▶ IR ─normalise─▶ IR ─infer─▶ Layout ─write─▶ DOCX ─refine─▶ DOCX
     PyMuPDF     dialect.py      heuristics    OOXML      render, measure,
     pypdfium2                              subset       correct, rewrite
```

Two stages were added after the original design and are load-bearing:

- **Normalise** (`dialect.py`) sits between parse and infer, and exists because
  producer differences were being absorbed as thresholds scattered through
  `infer.py`. It rewrites the IR into one shape — dropping page backdrops,
  turning glyph-drawn bullets into text markers, splitting rotated stamps out
  of flow, coalescing row fragments, joining ruled bands. Keyed on *page
  evidence*, never on the `/Producer` metadata string. See §7.
- **Refine** (`refine.py`) closes the loop: the converter renders its own
  output, measures the drift, and rewrites. See §4.

1. **Parse** (`parse.py`) — every text span (font, size, bold/italic/mono,
   color, bbox, *baseline origin*), every vector path (classified:
   rect / hline / vline / curve / complex), every placed image, every link.
   Two non-obvious jobs live here: *deduplicating* identical paths (producers
   emit borders twice) and *decomposing even-odd frame paths* (outer rect
   minus inner rect) into their 4 visible edge bars — otherwise a decorative
   frame's bounding box swallows everything inside it.
2. **Infer** (`infer.py`) — the semantic decompiler:
   - repeating headers/footers across pages; page numbers become live
     `PAGE`/`NUMPAGES` fields only after **cross-page verification** (the
     digit must equal the page number on ≥2 pages — "v3.2" stays text);
   - cover bands, continuation strips, grid tables (lattice from h/v edges),
     booktabs tables (rules + text-column clustering), zebra stripes,
     stat-card rows, callout/quote/code boxes, figure regions;
   - paragraphs: alignment, exact leading, indents, hanging list markers,
     heading levels, inline style runs, hyperlinks, underlines, superscripts;
   - multi-column regions with explicit column breaks;
   - reading order, page-relative spacing, margins from x/y clustering.
3. **Write** (`docxout.py`) — emits OOXML with the fidelity model below.
4. **Verify** (`verify.py`) — text-coverage audit (trigram overlap of
   normalized text, figure-region text excluded) + the render-back diff.

## 3. The fidelity model (the theory that made it work)

### 3.1 Baseline anchoring — the single most important idea

PDF line bounding boxes are **taller than Word's natural line height** (font
bbox ascender/descender vs. typographic metrics), and Word **bottom-aligns
glyphs inside an "exactly" line box**. If you place paragraphs by bbox tops,
every paragraph lands a few points low and the error compounds down the page.

The fix: anchor on **baselines**, the only geometry both worlds agree on.

```
para_top(Word) = first_baseline − (leading − 0.21·font_size)   # 0.21 ≈ descent
para_height    = n_visual_lines × leading                       # exact line rule
space_before   = para_top − cursor;   cursor += para_height
```

With `w:spacing w:lineRule="exact"` this reproduces ReportLab/WeasyPrint
semantics *exactly* (both also allocate `n × leading`). Measured drift on
plain body pages after this change: **±0.4pt** (from ~+5pt/paragraph before).

### 3.2 Content-driven table heights

`w:trHeight hRule="atLeast"` is interpreted **divergently**: Word treats it as
total row height (cell margins inside), LibreOffice adds cell margins *on
top* (measured: a 50.5pt row rendered 66.5pt = 50.5 + 2×8 margins). The
renderer-stable strategy: **never pin heights on rows that contain text**.
Instead, derive cell margins from geometry (top pad = first para top − cell
top, bottom pad = cell bottom − last para bottom) so pads + exact-leading
paragraphs *sum to the source height* — identical arithmetic in every
renderer. `trHeight` is only used for text-empty rows.

### 3.3 Page-break discipline

Every source page ends with an explicit break, so pagination can never drift
more than one page's worth of error. Two traps:

- python-docx's `add_section()` parks the old `sectPr` in a **fresh unstyled
  paragraph** (~23pt tall with the default template). On a full page it
  silently spills a **blank page**. Crush every section-break paragraph to a
  1pt exact line.
- Never delete "empty" paragraphs blindly during cleanup — a section-break
  paragraph has no runs, and removing it **deletes the whole section** (this
  produced a bleed-margin cover section evaporating at save time).

### 3.4 Column sections

- Word/Docs/LO apply the first paragraph's `space_before` after a continuous
  section break to the **entire column region**, not just column 1 (measured:
  the right column landed exactly `sb_left + sb_right` too low). Hoist the
  shared gap *above* the section break as a spacer paragraph; first elements
  in each column then carry `sb ≈ 0`.
- Original column distribution is enforced with explicit **column breaks**,
  which Google Docs supports.

### 3.5 Full-bleed cover bands

Three attempts, one survivor:

1. ✗ Band as first-page **header** (header distance 0, body pushed down) —
   push semantics differ per renderer.
2. ✗ Bleed L/R margins on a **mid-page continuous section** — the XML is
   valid, Word honors it, LibreOffice does **not** honor L/R margin changes
   at a mid-page continuous break (rendered the whole page at bleed width).
3. ✓ The whole cover page is **one bleed-margin section** (L/R ≈ 4pt); the
   band table spans it; every other page-1 element is pushed back to its
   original x with **indents** (universally honored), including shifted tab
   stops in the cover's footer clone. Page 2+ restores normal margins via a
   next-page section.

### 3.6 Font strategy — why re-wrap mostly matches

Embedded PDF fonts can't survive into Google Docs (it ignores embedded fonts),
so every font maps to a **metric-compatible, Docs-available family**:
Helvetica→Arial, Times/Liberation Serif/DejaVu Serif→Times New Roman,
Courier/DejaVu Sans Mono→Courier New, and Google-native families (Roboto,
Lato, Montserrat, Merriweather, Source Code Pro…) pass through. Because the
substitutes share advance widths with the originals, justified paragraphs
usually re-wrap onto the **same line breaks** — which is what keeps paragraph
heights (n × leading) truthful.

### 3.7 Neutralize the template

python-docx's default template carries Normal = 1.08× line + 8pt space-after,
and inline images inherit it (a 168pt chart grew by 13pt). Set Normal to
1.0×/0pt and pin image paragraphs with `atLeast(image height)`.

## 4. Verification-driven development (the method)

The loop that found every bug above:

1. `convert()` → DOCX
2. LibreOffice `--convert-to pdf` → re-render
3. per-page SSIM + page-count check + side-by-side strips
4. **line-drift table**: match identical text lines source↔converted, print
   `y_src, y_conv, Δ` — the microscope. A constant Δ is an anchoring bug; a
   growing Δ is a height-model bug; a Δ that jumps at one element type
   indicts that element's builder.
5. text-coverage audit (nothing silently dropped).

SSIM interpretation: 0.9+ means near-identical; cover pages sit lower
(0.55–0.75) because large solid-color areas amplify ±2pt offsets and font
rasterization differences — visually they read as the same page. Page-count
match + coverage + drift table matter more than the absolute SSIM number.

Two later corrections to this method, both of which mattered more than any
single fix:

**The loop is now closed, not just observed.** Steps 1–5 above *report*. A
render-back that only reports leaves the converter guessing. `refine.py` feeds
the measurement back: convert → render → fit per-page drift → re-emit with
corrected `space_before`. This was justified before it was built — decomposing
word drift into a per-page affine trend plus a residual showed **77% of the
vertical error was systematic**, i.e. whole pages sitting a few points off
rather than paragraphs mis-sized internally. Mean |dy| went 4.01pt → 0.93pt.
A closed loop can only remove the systematic part, so measuring that share
first is what made it worth building.

**The verifier must not be the converter.** `verify.py` called `infer()` to
decide what counted as text, then excluded from the *source* side anything the
converter had chosen to rasterise. A fully-rasterised page therefore scored
`text_coverage 0.0 / 0.0` — the document deleted itself from its own
denominator, and the tool reported success. Everything in `testkit/` shares no
code with the converter for this reason. See STATUS.md §4.5.

## 5. What worked (ranked by measured impact)

| Fix | Effect |
|---|---|
| Baseline-anchored spacing + exact leading | body drift ±5pt/para → ±0.4pt |
| Explicit page breaks per source page | unbounded drift → page-local |
| Content-driven table heights (no trHeight) | +7…17pt/table-row → ~0 |
| Crushed section-break paragraphs | phantom blank pages eliminated |
| Even-odd frame decomposition | title blocks stopped rasterizing |
| List-marker re-attachment (separate/flush marker boxes) | −140pt cascades → 0; the WeasyPrint killer |
| Column pre-gap hoisting | right column −80pt → ±2pt |
| Metric-compatible font mapping | justified wraps mostly identical |
| Marker-aware paragraph splitting | list items stopped fusing |
| Centered-block explosion (width-variance test) | author blocks stopped collapsing |
| Inset-justify detection (right-indent pinning) | indented abstracts wrap identically |
| Cross-page digit verification for PAGE fields | "v3.2" ≠ page number |
| Chart rasterization with overlap-aware label absorption | axis labels stopped leaking as stray text |

## 6. What didn't work (dead ends worth remembering)

- **`trHeight atLeast` for text rows** — renderer-divergent (see 3.2).
- **Anchored text boxes everywhere** ("exact mode") — pixel-perfect in Word,
  broken in Google Docs; rejected as the default early.
- **Cover band in the first-page header** — body push-down behavior varies.
- **Mid-page L/R margin change via continuous section** — LO ignores it.
- **Bbox-top anchoring** — systematically low; the wrong mental model.
- **Auto-hyphenation as a re-wrap fix** — built it, then measured the actual
  document: zero hyphenated line endings. The re-wrap drift had a different
  cause (fitz extracting justify-stretched gaps as doubled spaces — and
  collapsing those measured ≈ no change either; the real fixes were the
  marker/paragraph bugs). Lesson: **measure before theorizing**; two
  plausible theories in a row were simply wrong.
- **Single gap threshold for list markers** — ReportLab separates markers by
  ≥4pt; WeasyPrint butts them flush (gap = 0.0) with the separator as a
  trailing space *inside* the marker span. Producer dialects differ at the
  half-point level; thresholds must encode the union of dialects.
- **Trusting python-docx section semantics** — `add_section`'s sectPr
  shuffling had to be pinned down empirically and re-applied defensively.
- **Tuning a threshold that cannot exist** — the last table/paragraph gap
  discriminator oscillated at 3, 3, 4 regressions across a day of tuning.
  Plotting the two gap distributions ended it: both had median 4.7em and
  overlapped almost completely. No threshold on that axis could separate them,
  so the decision was moved to where the evidence actually is — the ruling
  lines. **Before tuning a parameter, check the distributions it separates.**
- **Two compensators that worked and were switched off** — the quality ladder
  (line-locking) and the half-point wrap correction. Each fixes something real
  and measurable; neither improved page counts, and the wrap correction *costs*
  a page unless the page-capacity model knows the predicted line count before
  the first write. Shipping a measured regression is worse than shipping
  nothing. **The ladder was switched back on 2026-08-05**: "neither improved
  page counts" was measured with the ladder alone, and alone it does not,
  because a second defect was cancelling it. c1's cover band lost a line to a
  re-wrap (−11.7pt on every element below) while its stat-card row was emitted
  as a vertical stack (+115pt); each error hid the other, and fixing only the
  first made the composite metric *worse*. Landed together, c1's raw lane goes
  2/3 → 2/2 pages and dy_p50 101.0 → 2.0. **A compensator that does not pay
  alone has not been shown not to pay — check what is cancelling it.**
- **Turning a global default on, measured against sixteen documents** — the
  ladder flip above passed the gated corpus with zero regressions and was
  landed on that evidence. The expansion sweep then found four candidate-side
  regressions and a degraded reference arm that sixteen documents could not
  see. The gate is not a sample of the world; it is sixteen documents that
  happen to be pinned. **A change to a default that every document flows
  through is measured on both corpora before it lands, never on the gated
  sixteen alone.**
- **A prediction that exists is not a prediction that is right** — the ladder's
  `_predictable` checked that a font FAMILY maps to a base-14 name and never
  that the CHARACTERS were in that font's WinAnsi repertoire. Measured with
  `get_text_length` at 11pt, base-14 resolves Latin glyph by glyph
  ("aaaaaaaaaa" 48.84pt vs "mmmmmmmmmm" 85.58pt) and returns an *identical*
  13.75pt for narrow and wide Cyrillic. It was not approximating those scripts,
  it was not seeing them — and returning a number anyway. The honest failure
  mode of a metric is `None`; a metric that guesses silently is worse than one
  that refuses, because every caller downstream believes it.
- **Guessing at the pdfium placement gap** — "most likely baseline or line-box
  geometry" was written into the defect register and survived a full revision
  of it. Direct measurement found baselines identical on 4,734 of 4,734 lines;
  the cause was block grouping plus a serif-flag bug. Same lesson as the
  hyphenation dead end above, relearned.

## 7. Producer dialects (why "PDF" is not one format)

| Behavior | ReportLab (Claude default) | WeasyPrint (HTML→PDF) | Chromium / Skia (print-to-PDF) | pdfTeX / LaTeX |
|---|---|---|---|---|
| List markers | same text block, gap ≥ 4pt | separate blocks, flush (gap 0), several markers per block | 3×3pt bezier circles — *drawings*, not text | text, tight |
| Decorative rules | thin stroked/filled rects | even-odd frame paths (bbox swallows content) | rects, plus a page-sized white backdrop | rules as filled rects |
| Duplicate paths | no | yes (borders emitted twice) | no | no |
| Paragraph blocks | one block per flowable | blocks merge items when spacing ≈ leading | one per CSS box | per TeX paragraph |
| Fonts | core-14 (Helvetica/Times/Courier) | Liberation/DejaVu subsets | system fonts, often no descriptor | Computer Modern subsets |
| Text matrix | identity | identity | **0.75** (CSS px → pt) | identity |
| Justify artifacts | none | stretched gaps extract as doubled spaces | none | ligatures, tight kerning |

A converter tuned on one dialect *will* break on the other — this is exactly
what the first run on a real WeasyPrint paper demonstrated (12 pages from 10,
SSIM 0.49), and why the verification loop, not the corpus score, is the
product.

Chromium proved the point far more violently, and it is the dialect that
matters most: it is what *anything printed from a browser* produces, including
HTML artifacts exported to PDF. Three of its quirks compounded into total
failure. The invisible page-sized white backdrop touched every other drawing,
so cluster-unioning collapsed the whole page into one region; a single bullet
rendered as a bezier made that region a "figure"; and the figure grew without
bound because its absorption threshold was derived from the box being grown
(measured: a 490×2pt seed of two hairlines reached 494×153pt, **103× in area**).
A browser-printed résumé came out as two full-page JPEGs — visually plausible,
and not a document. Live text: 0.0%.

The fourth column also carries the one dialect quirk that is pure arithmetic:
Chromium lays out in CSS pixels and applies a 0.75 text matrix, so
`FPDFText_GetFontSize`, which reports the size *before* the matrix, was 4/3 too
large. That inflated leading, then paragraph heights, then page counts — seven
source pages rendered as twenty. The effective size is the reported size times
the matrix's vertical scale.

The lesson that shaped `dialect.py`: normalise on **page evidence**, never on
the `/Producer` string. Metadata is absent, wrong, or rewritten by every tool
in the chain, and a converter that dispatches on it fails silently on the
document that was edited after export.

## 8. Is this the ceiling? What's left

**Fundamental limit** — re-flowed justified text in a different layout engine
will occasionally break a line one word earlier/later. Everything downstream
of a different break (paragraph height ±1 line) is unfixable *while keeping
the text editable*. Mitigations already in place (metric-compatible fonts,
wrap-width pinning via indents, exact leading) get most paragraphs identical;
they cannot get all of them. Pixel-perfect + fully editable is a
contradiction at the engine boundary.

> **Corrected.** The *contradiction* stands; the claim that observed re-wrap
> was mostly it does not. Most of the re-wrap measured here was a compensable
> unit error: OOXML stores font size in half-points, so 10.1pt body text is
> emitted at 10.0pt, glyphs run ~1% narrow, ~1% more text fits per line, and
> nearly every justified paragraph breaks differently. Sweeping the wrap width
> against line-break agreement moved it 0.599 → 0.796, with the optimum
> narrowing at 0.8–1.0% — matching 10.0/10.1 = 0.990 exactly. Line breaking is
> scale-invariant, so that is a principled correction, not a fudge. The engine
> boundary is the *last* 20% of re-wrap, not the first. (The correction is
> written and measured but gated off; see §6.)

**A second law, found later and worth stating separately.** Google Docs and
LibreOffice do not agree on `w:spacing lineRule="exact"`. Docs treats the
value as a *minimum* against the font's natural line height rather than an
exact box, so every paragraph set tighter than its natural height grew. The
fix is a per-font table of natural-height factors applied when targeting Docs
— a static translation, no loop required, and worth roughly a factor of ten on
the affected documents. This is the clearest evidence that a LibreOffice-only
verification loop measures the wrong renderer.

**Engineering headroom (real, unbuilt):**

1. **Wrap prediction** — shape each paragraph with real font metrics
   (HarfBuzz/fontTools) at write time, *predict* Word's line breaks, and when
   they'd diverge, nudge character spacing by ±0.1pt (`w:spacing` on rPr) or
   adjust the wrap width by fractions of a point. This attacks the
   fundamental limit head-on and could plausibly push body pages to ~0.95+.
2. **A true Google Docs oracle** — drive the actual Docs import (browser or
   Drive API export back to PDF) inside the verification loop instead of the
   LibreOffice proxy.
3. **Real Word footnotes** — superscript markers currently stay inline text;
   mapping detected footnote regions to `w:footnote` parts would survive
   editing better.
4. Nested tables, rotated text, gradients→DrawingML, TOC field
   reconstruction, RTL/CJK shaping, OCR pass for scanned PDFs, forms.
5. **More dialects** — LaTeX (pdfTeX ligatures/kerning quirks), Chromium
   print-to-PDF, fpdf2, Typst. Each is a day of measured fixes, not a
   redesign: the architecture (IR → semantic inference → safe vocabulary +
   verification loop) has absorbed two dialects without structural change.

**Honest scorecard** — *superseded; see [STATUS.md](STATUS.md) §1 for the
current figures.* What this section used to claim, and why it was wrong, is
worth keeping:

> structure/text ≈ 99.6–100% recovered; pagination 1:1; visual similarity
> 0.7–0.94 by SSIM…

Three things were wrong with that. **Pagination was not 1:1** — it is 15/16 on
the corpus and fails on every LaTeX document, which inflate 25–90%. **SSIM was
the wrong headline**: a fully-rasterised résumé scored 0.594, inside the band
quoted here as success and *higher* than a document that kept 100% of its text
(0.365). SSIM cannot tell a document from a photograph of one, and no metric
here measured editability at all. And the corpus behind those numbers was one
self-authored dialect, so it measured tuning, not generalisation — the current
holdout figure on wild PDFs is **0/4**.

Corpus scores are reported in two lanes (`product` and `raw`) for the same
reason: `refine()` tunes against the same renderer the gate measures with, so a
refined-only number can improve because the loop memorised the oracle. Only the
pair means anything — and both now gate the exit code, because for a while only
the refined lane did, which left the control lane free to regress unanswered.

One more failure of the same shape, and it is the reason `exactdoc/options.py`
exists: the numbers above were measured on a profile no shipping surface ran. The
API refined 0 times, the CLI 2, the quoted lane 3. A measurement that describes no
shipping configuration is a coincidence, however carefully it was taken. There is
one profile now, and every surface reads its defaults from it.

## 9. Is Python the limitation?

No — and it's worth being precise about why:

- The **hot paths aren't Python**. Parsing/rasterizing is PyMuPDF (C, MuPDF);
  image diffing is NumPy (C); rendering oracle is LibreOffice. Python is the
  orchestration and heuristics layer, where iteration speed *was* the
  bottleneck that mattered — this project is ~2.5k lines that were rewritten
  dozens of times against measurements. A systems language would have made
  that slower, not better.
- **Fidelity is capped by OOXML semantics and renderer behavior**, not by
  compute. Nothing in sections 3–8 gets easier in Rust/C++.
- The one place a language choice *could* matter — text shaping for wrap
  prediction — is available in Python via HarfBuzz bindings (uharfbuzz) and
  fontTools, which are the reference tools in that space anyway.
- Real Python-adjacent constraints, for honesty: python-docx's API is thin
  (much of the writer is raw lxml/OOXML — fine, just verbose), single-file
  conversion is ~1–3s (irrelevant at this scale), and **PyMuPDF's AGPL
  license** constrains distribution (see §10) — ~~a licensing limit, not a
  technical one~~.

  > **Falsified.** Calling the licence "not a technical" limit was the most
  > expensive wrong sentence in this document, because it made the swap look
  > like paperwork. A permissive backend was written against pypdfium2 and the
  > parity harness reported zero regressions, so the default was flipped,
  > `parse.py` deleted and the project relicensed to Apache-2.0 — before anyone
  > noticed the harness did not measure fine placement. It had cost within-2pt
  > 0.510 → 0.291. All of it was reverted. See §10 and STATUS.md D2.

## 10. Should this be published?

Yes — the niche is real: "pdf2docx but it actually preserves design, targets
Google Docs compatibility, and *proves* fidelity with a render-back diff" is
a genuinely unserved corner. The verification loop alone (SSIM + drift table)
is a contribution; no popular converter ships one.

Do these first:

1. **Licensing (the important one).** PyMuPDF is **AGPL-3.0**: the repo must
   be AGPL too, unless the parser is swapped to a permissive stack. AGPL is
   fine for an open tool; it mainly deters closed commercial reuse.

   The swap turned out to be the hardest single item in this list, and the
   reasoning above understates it in two ways.

   **pdfminer.six is not a candidate.** Measured over 20 documents, it loses up
   to 16% of characters on LaTeX and sees **4% of the vector paths** on arXiv
   papers — materially worse on the dialect that is already weakest.

   **pypdfium2 extracts perfectly and groups differently, and grouping is what
   inference reads.** It offers no line or block clustering at all, so that had
   to be written. Extraction reached parity — baselines identical on 4,734 of
   4,734 lines, paths 1.00× exactly, text character-identical — and the port
   still costs 7 placement regressions, because block boundaries decide
   paragraph assembly and line boundaries decide what a figure region absorbs.

   Writing the clustering ourselves is what makes this tractable rather than
   endless: we *control* the grouping, so the existing tuning stops being a
   liability and becomes the specification. The port is correct when it
   reproduces the frozen golden IR (`testkit/golden_ir.py`). A verifiable port,
   not a rewrite.

   Two consequences worth stating plainly. The swap **buys no fidelity** — it
   is pure licence work, and it must be held to not-worse, not to better. And
   until it lands, **do not accept external contributions to `parse.py`**:
   relicensing needs every contributor's consent, and the swap is confined to
   that one module, so contributions anywhere else cost nothing.

   > **Landed, 2026-08-06.** exactdoc is Apache-2.0; PDFium ships and PyMuPDF is
   > the optional `mupdf` extra. Two corrections this passage earns.
   >
   > "Held to not-worse" was the right instinct and the wrong bar, and it was
   > not met literally: four ratified findings at the shipping profile made the
   > aggregate slightly worse, and they were adjudicated as an acceptable price
   > *before* the swap rather than argued away after it
   > (`docs/evidence/parser-default-flip-2026-08-06.json`). A rule that admits
   > no priced exceptions gets quietly reinterpreted instead of applied.
   >
   > "The port is correct when it reproduces the frozen golden IR" was
   > **abandoned**, and `exactdoc/backend.py` records why in full: the golden
   > moves with PyMuPDF's own releases, so it cannot be a specification. The
   > parity gate is the contract; the golden IR is a microscope for locating
   > disagreements.
2. Package properly: `pyproject.toml`, console entry point, pinned deps,
   `pip install exactdoc`.
3. CI: run the corpus + a WeasyPrint sample through the verification loop and
   fail on page-count mismatch / SSIM regression — the loop *is* the test
   suite. LibreOffice in CI via a docker image.
4. README with side-by-side screenshots and the honest limits section (§8) —
   credibility comes from stating the re-wrap caveat plainly.
5. Name check on PyPI, `--verify` documented, sample corpus included
   (synthetic, no copyrighted content).
6. Issues to expect immediately: LaTeX papers, scanned PDFs (out of scope —
   say so), CJK, forms.
