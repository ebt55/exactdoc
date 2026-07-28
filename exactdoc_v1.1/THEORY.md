# exactdoc — Theory & Findings

How to convert a PDF to a DOCX that opens in Google Docs looking like the
original — what worked, what didn't, and where the ceiling is.

Everything here was established empirically with a **render-back verification
loop**: convert the DOCX back to PDF (LibreOffice headless), image-diff every
page against the source (SSIM + mean absolute difference), and measure
line-by-line vertical drift by matching text lines between the two PDFs.
No fix below was accepted on theory alone; each one moved a measured number.

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
PDF ──parse──▶ IR ──infer──▶ Layout model ──write──▶ DOCX ──verify──▶ diff report
      PyMuPDF        heuristics          python-docx + raw OOXML     LibreOffice + SSIM
```

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

## 7. Producer dialects (why "PDF" is not one format)

| Behavior | ReportLab (Claude default) | WeasyPrint (HTML→PDF) |
|---|---|---|
| List markers | same text block, gap ≥ 4pt | separate blocks, flush (gap 0), several markers per block |
| Decorative rules | thin stroked/filled rects | even-odd frame paths (bbox swallows content) |
| Duplicate paths | no | yes (borders emitted twice) |
| Paragraph blocks | one block per flowable | blocks merge items when spacing ≈ leading |
| Fonts | core-14 (Helvetica/Times/Courier) | Liberation/DejaVu subsets |
| Justify artifacts | none | stretched gaps extract as doubled spaces |

A converter tuned on one dialect *will* break on the other — this is exactly
what the first run on a real WeasyPrint paper demonstrated (12 pages from 10,
SSIM 0.49), and why the verification loop, not the corpus score, is the
product.

## 8. Is this the ceiling? What's left

**Fundamental limit** — re-flowed justified text in a different layout engine
will occasionally break a line one word earlier/later. Everything downstream
of a different break (paragraph height ±1 line) is unfixable *while keeping
the text editable*. Mitigations already in place (metric-compatible fonts,
wrap-width pinning via indents, exact leading) get most paragraphs identical;
they cannot get all of them. Pixel-perfect + fully editable is a
contradiction at the engine boundary.

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

**Honest scorecard today:** structure/text ≈ 99.6–100% recovered; pagination
1:1; visual similarity 0.7–0.94 by SSIM with the residual dominated by
antialiasing and ±1-line re-wraps, not by layout errors.

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
  license** constrains distribution (see §10) — a licensing limit, not a
  technical one.

## 10. Should this be published?

Yes — the niche is real: "pdf2docx but it actually preserves design, targets
Google Docs compatibility, and *proves* fidelity with a render-back diff" is
a genuinely unserved corner. The verification loop alone (SSIM + drift table)
is a contribution; no popular converter ships one.

Do these first:

1. **Licensing (the important one).** PyMuPDF is **AGPL-3.0**: the repo must
   be AGPL too, unless the parser is swapped to a permissive stack
   (pypdfium2 — Apache/BSD, plus pdfplumber for text) to allow MIT/Apache.
   AGPL is fine for an open tool; it mainly deters closed commercial reuse.
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
