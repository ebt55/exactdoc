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
python3 -m exactdoc.cli input.pdf -o out.docx --verify
python3 -m exactdoc.cli *.pdf --dpi 300              # batch, high-res figures
```

Python API:

```python
from exactdoc.convert import convert
convert("whitepaper.pdf", "whitepaper.docx")
```

## How it works

1. **Parse** (`parse.py`) — PyMuPDF extracts every text span (font, size,
   weight, color, exact position), vector drawing, image and link into an
   intermediate model.
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

Five synthesized Claude-style PDFs (cover bands, callouts, shaded + booktabs
tables, lists, code blocks, vector charts, stat cards, two-column paper,
footers with page fields). Page counts match 1:1; text coverage ≈ 100%;
LibreOffice render-back SSIM 0.71–0.94 (covers score lowest because solid
color panels amplify ±2pt offsets; visually they are near-identical).

## Limitations

- Word/Docs cannot bleed content into side margins from a normal section;
  cover bands bleed via a dedicated section, continuation strip headers span
  content width.
- Chart labels live inside the rasterized figure image (by design).
- Line-break-exact justification depends on metric-compatible fonts; exotic
  embedded fonts fall back to the closest safe family.
- Scanned/OCR PDFs are out of scope (no OCR pass).
