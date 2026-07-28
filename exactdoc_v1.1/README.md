# exactdoc — high-fidelity PDF → DOCX

A ground-up PDF-to-Word converter built for **design preservation**, tuned for
**Claude-generated whitepapers and research papers**, with output restricted to
constructs that **Google Docs imports faithfully**.

Existing tools (pdf2docx, LibreOffice import, Word's own PDF reflow) lose
decorative vector art, callout boxes, cover bands, exact spacing and colors.
exactdoc reconstructs the document semantically and reproduces the design.

## Usage

```bash
python3 -m exactdoc.cli input.pdf                    # writes input.docx
python3 -m exactdoc.cli input.pdf --target gdocs     # tune for Google Docs
python3 -m exactdoc.cli input.pdf -o out.docx --verify
python3 -m exactdoc.cli *.pdf --dpi 300              # batch, high-res figures
```

### Pick a target renderer

There is no single "correct" DOCX. Word, LibreOffice and Google Docs lay the
same file out differently, and the gap is not small: on a document where
LibreOffice places 99% of words within 2pt of the source, Google Docs places
1% — Docs adds a one-off gap after the first heading plus ~3pt at every
paragraph boundary, which accumulates down the page.

So `--target` chooses which program the output should look right in, and the
closed-loop pass (below) optimises for that renderer:

| `--target` | Oracle | Notes |
|---|---|---|
| `libreoffice` | LibreOffice headless | default; fast, offline, a good proxy for Word |
| `gdocs` | Google Docs via the Drive API | needs credentials; slowest; the only oracle that answers the question this project asks |
| `none` | — | no feedback loop, deterministic, no dependencies |

Measured, opening the result in Google Docs: tuning for `gdocs` instead of
`libreoffice` moved `c8_toc_links` from dy₅₀ 41.4pt to 4.6pt, and
`02_research_paper` from 3 pages to the correct 2.

### Closed-loop correction

`--refine N` (default 2) writes the DOCX, renders it back through the chosen
target, measures page overflow and per-page offsets, corrects the layout and
rewrites — keeping the best round. Without an oracle available it degrades
silently to a single ordinary write, so conversion never depends on it.

Python API:

```python
from exactdoc.convert import convert
convert("whitepaper.pdf", "whitepaper.docx")
```

## How it works

1. **Parse** (`parse.py`) — PyMuPDF extracts every text span (font, size,
   weight, color, exact position), vector drawing, image and link into an
   intermediate model.
1b. **Normalise** (`dialect.py`) — rewrite producer-specific idioms into one
   canonical form, so the heuristics below stop encoding "how ReportLab draws
   things". Drops page-backdrop fills (Chromium paints an opaque white page
   rect that otherwise merges every drawing into one region), rewrites vector
   list markers as text markers (a CSS `disc` bullet reaches the PDF as a 3×3pt
   bezier circle, not a character), and moves rotated text out of the flow.
   Driven by evidence in the page, never by the `/Producer` string — those are
   absent, rewritten by post-processors, and version-dependent.
2. **Infer** (`infer.py`) — heuristics reconstruct semantics:
   - repeating headers/footers, with page numbers converted to live
     `PAGE`/`NUMPAGES` fields (verified across pages so "v3.2" never becomes a
     field)
   - full-width cover bands and continuation strips
   - grid tables, booktabs (ruled) tables, zebra striping, stat-card rows
   - callout boxes (left-accent), warning boxes, quote bars, code blocks
     (blank lines reconstructed from baseline gaps)
   - bullet/numbered lists, headings (outline levels), hyperlinks, underlines
   - multi-column layouts with true section columns + column breaks
   - chart/diagram regions -> rasterized at high DPI with overlap-aware text
     absorption (axis labels ride along in the image)
3. **Write** (`docxout.py`) — python-docx + raw OOXML emits a DOCX using only
   the Google-Docs-safe vocabulary: styled paragraphs, fixed-layout tables
   with per-side borders/shading, section geometry & columns, inline images,
   headers/footers, tab stops, fields. No floating text boxes, no VML, no
   embedded fonts.
4. **Verify** (`verify.py`) — text-coverage audit plus an optional render-back
   loop (LibreOffice) that scores per-page visual similarity (SSIM) and emits
   side-by-side comparison images.

## Fidelity model (the hard-won parts)

- **Baseline anchoring.** Word bottom-aligns glyphs inside "exact" line boxes
  and PDF line bboxes are taller than Word's natural line. All vertical
  spacing is therefore anchored on *baselines*:
  `para_top = baseline − (leading − 0.21·size)`, paragraph height =
  `n_lines × leading` (exact line rule).
- **Content-driven table heights.** LibreOffice adds cell margins *on top of*
  `trHeight atLeast`, Word doesn't. Rows carry no explicit height when they
  contain text; padding + exact-leading paragraphs sum to the source height,
  which renders identically everywhere.
- **Page-break discipline.** Every source page ends with an explicit break, so
  pagination cannot drift. Section-break paragraphs are crushed to 1pt (a
  default-styled one can silently spill a blank page).
- **Column sections.** Space-before on the first paragraph after a continuous
  break pushes the whole column block down in some renderers — the shared gap
  is hoisted into a spacer *before* the break, and original column
  distribution is enforced with explicit column breaks.
- **Full-bleed cover pages.** The cover lives in its own near-zero-margin
  section; every non-band element is shifted back into place with indents
  (mid-page L/R margin changes via continuous breaks are not honored by all
  renderers).
- **Font mapping** targets Google-Docs-available, metric-compatible families:
  Helvetica→Arial, Times→Times New Roman, Courier→Courier New; Roboto, Lato,
  Montserrat, Merriweather, Source Code Pro etc. pass through (`fonts.py`).

## Verified corpus results

18 documents across five producer dialects (Chromium/Skia, WeasyPrint,
ReportLab, fpdf2, LibreOffice), measured by `testkit/`, which shares no code
with this package:

| | |
|---|---|
| gate passed | 15/18 |
| page count 1:1 | 17/18 |
| live (editable) text | 96.9% mean |
| words within 2pt of source | 40.4% mean |
| median per-word vertical drift | 1.02pt |
| SSIM (LibreOffice render-back) | 0.809 mean |

Run it yourself: `python testkit/runall.py testkit/adv my_samples`. It exits
non-zero on regression, so it doubles as CI.

**Do not use SSIM as the headline number.** It is dominated by whitespace and
it *rewards* a rasterised page: a resume converted into two flat images scored
0.594, comparable to genuinely good conversions. `live_text_cov` and
`within2pt` are what distinguish a document from a photograph of one.

## Known-broken

- **Nested tables** flatten, with borders in the wrong places (`c3_tables`).
- **LaTeX/pdfTeX** papers still inflate their page count substantially. Text is
  recovered (≈95% live) but pagination is not; the multi-column author block on
  a paper's first page explodes into a vertical cascade.
- **Rounded-corner "stat card" rows** stack diagonally instead of forming a row:
  `border-radius` makes the card a curve, and the card-row detector requires a
  rect.
- **Letter-spaced headings** lose their spaces — "TECHNICAL SKILLS" comes out
  "TECHNICALSKILLS".
- **Mixed page geometry** is discarded: page size and orientation come from
  page 1 and apply to the whole document.

## Limitations

- Word/Docs cannot bleed content into side margins from a normal section;
  cover bands bleed via a dedicated section, continuation strip headers span
  content width.
- Chart labels live inside the rasterized figure image (by design).
- Line-break-exact justification depends on metric-compatible fonts; exotic
  embedded fonts fall back to the closest safe family.
- Scanned/OCR PDFs are out of scope (no OCR pass).
