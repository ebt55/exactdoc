# exactdoc

**PDF → DOCX that keeps the design, survives Google Docs, and measures whether it worked.**

> **Status: alpha (0.1.0a1). Nothing has been released yet.** It works well on the
> documents it was developed against and it fails on pagination for PDFs it has
> never seen. Both numbers are below, in the same table, on purpose.

Most PDF-to-Word converters either redesign your page (Word's reflow), turn every
line into a floating frame that Google Docs then mangles (LibreOffice import), or
throw the design away entirely and emit Markdown (Docling, Marker, MinerU).
[`pdf2docx`](https://pypi.org/project/pdf2docx/), the usual Python answer, is no
longer actively maintained by Artifex.

exactdoc decompiles the page instead: it recovers paragraphs, tables, callouts,
columns and rules as real editable Word constructs, restricted to the subset
Google Docs imports faithfully — no text boxes, no VML, no embedded fonts.

Then it checks its own work. Every claim below is a number produced by
[`testkit/`](testkit/README.md), which shares no code with the converter.
[STATUS.md](STATUS.md) is the authority on all of them:

| | 16-document corpus | 4 wild PDFs (holdout) |
|---|---|---|
| gate passed | 13/16 | **0/4** |
| page count 1:1 | 15/16 | fails |
| live (editable) text recovered | 96.5% | 94–97% |
| words within 2pt of source | 51.0% | — |
| median per-word vertical drift | 0.69pt | — |

The corpus has been developed against; the [holdout](testkit/fetch_holdout.py)
never has. The gap between those two columns is the honest measure of how far
along this is: **the text survives, the pagination does not.** Everything in the
corpus column is the `--refine` lane, the shipped default; the uncontaminated
no-refine lane is in [STATUS.md §1](STATUS.md#1-where-the-converter-stands) and
both are always reported, because the refine loop tunes against the same renderer
the gate measures with.

## Install

Not on PyPI yet — the first published release will be the Apache-2.0 one (see
[Versions](#versions)). Until then:

```bash
pip install git+https://github.com/ebt55/exactdoc.git
```

Optional extras: `[test]` for the measurement harness, `[pdfium]` for the
experimental permissive parser, `[gdocs]` for the Google Docs oracle. None is
needed for a plain conversion.

`--verify` and `--refine` additionally need LibreOffice on PATH; without it,
conversion still works and simply skips the feedback loop.

## Usage

```bash
exactdoc input.pdf                       # writes input.docx
```

```bash
exactdoc input.pdf --target gdocs        # tune for Google Docs specifically
```

```bash
exactdoc *.pdf --dpi 300 --verify        # batch, high-res figures, with a report
```

```python
from exactdoc.convert import convert
convert("whitepaper.pdf", "whitepaper.docx", target="gdocs", refine_rounds=2)
```

## Why a "target" matters

There is no single correct DOCX. The *same file* lays out differently in Word,
LibreOffice and Google Docs, and the gap is not cosmetic — on a document where
LibreOffice places 99% of words within 2pt of the source, **Google Docs places
1%**. Docs adds a one-off gap after the first heading plus roughly 3pt at every
paragraph boundary, and it accumulates down the page.

Most converters are tuned against one renderer and silently assume it
generalises. It does not. exactdoc makes the target an explicit choice, so
`--target` chooses which program the output should look right in, and the
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

16 generated documents across four producer dialects — Chromium/Skia (8),
ReportLab (6), fpdf2 (1), LibreOffice/Word-native (1) — measured by `testkit/`,
which shares no code with this package. WeasyPrint and LaTeX/pdfTeX are covered
by real documents outside the gate corpus; LaTeX is the worst case and the
largest open defect (see below).

Both lanes, because only the pair is meaningful:

| | no-refine | refine (shipped default) |
|---|---|---|
| gate passed | 12/16 | 13/16 |
| page count 1:1 | 13/16 | 15/16 |
| live (editable) text | 96.5% | 96.5% |
| words within 2pt of source | 36.1% | **51.0%** |
| median per-word vertical drift | 2.79pt | **0.69pt** |

`refine()` optimises against the same renderer the gate scores with, so a
refined-only number can improve because the loop memorised the oracle rather
than because the converter got better. Reporting one lane would hide that.

Run it yourself (needs the `[test]` extra, LibreOffice for the render-back, and
Chrome to generate the Chromium half of the corpus):

```bash
python testkit/gen_corpus.py testkit/adv && python corpus/make_corpus.py
```

```bash
REFINE=lanes python testkit/runall.py testkit/adv corpus/pdfs
```

It exits non-zero on regression, so it doubles as CI.

**Do not use SSIM as the headline number.** It is dominated by whitespace and
it *rewards* a rasterised page: a resume converted into two flat images scored
0.594, comparable to genuinely good conversions. `live_text_cov` and
`within2pt` are what distinguish a document from a photograph of one.

## Known-broken

Every entry is measured. See [STATUS.md](STATUS.md) for the full register with
severity, evidence and the reproduction command for each.

- **LaTeX/pdfTeX pagination** — the largest open defect. Text is recovered
  (94–97% live) but page counts inflate 25–90%; the holdout set is 0/4.
- **Nested tables** flatten, with borders misplaced (`c3_tables`, 3 → 4 pages).
- **Rounded-corner "stat card" rows** stack diagonally: `border-radius` makes
  the card a curve, and the card-row detector requires a rect.
- **Letter-spaced headings** lose their spaces — "TECHNICAL SKILLS" →
  "TECHNICALSKILLS".
- **Mixed page geometry** is discarded: page size and orientation are taken
  from page 1 for the whole document.

## Limitations

- Word/Docs cannot bleed content into side margins from a normal section;
  cover bands bleed via a dedicated section, continuation strip headers span
  content width.
- Chart labels live inside the rasterized figure image (by design).
- Line-break-exact justification depends on metric-compatible fonts; exotic
  embedded fonts fall back to the closest safe family.
- Scanned/OCR PDFs are out of scope (no OCR pass).

## Is a pixel-perfect result possible?

For text-flow documents — whitepapers, papers, reports, resumes — near-perfect
*and editable* is reachable. These are hard limits, not bugs:

1. **Pixel-perfect and editable is a contradiction.** Text re-flowed by a
   different engine will occasionally break a line differently, and everything
   below a changed break moves. You can make it rare, not impossible.
2. **OOXML quantises font size to 0.5pt.** A 10.1pt source font cannot be
   emitted at 10.1pt. Compensable via wrap width; not removable.
3. **Google Docs ignores embedded fonts.** Metric-compatible substitution is
   the ceiling.
4. **Google Docs flattens per-section page geometry**, which puts full-bleed
   cover bands permanently at risk.
5. **Gradients, rounded corners and rotated text** have no paragraph-flow
   equivalent and must rasterise.

## Versions

Nothing has been published, so the version numbering is being reset once, now,
while it is free to do so:

| Version | What it means |
|---|---|
| `0.1.0a1` | today — alpha, AGPL (inherited from PyMuPDF), git install only |
| `0.2.0a1` | the first *published* release, Apache-2.0, after the permissive parser reaches zero parity regressions |
| `0.x` betas | gated on the holdout number improving, not on the corpus number |
| `1.0` | not before wild PDFs stop failing on pagination |

No AGPL wheel will ever be published: the licence swap lands before the first
release, not after it.

## Documentation

- [STATUS.md](STATUS.md) — the authority on every number, the defect register,
  and the measurement mistakes that produced confident wrong answers
- [SESSIONS.md](SESSIONS.md) — the working log: what each session expected to
  happen before it ran
- [THEORY.md](THEORY.md) — the fidelity model, what worked, what didn't, and why
- [FINDINGS.md](FINDINGS.md) — a frozen independent audit with reproductions.
  Its "v1.1" is a pre-release internal label from before this repo had versioned
  releases; it does not correspond to any tag or published artifact.
- [testkit/README.md](testkit/README.md) — the measurement harness and its metrics

## Contributing

The fastest way to help is a PDF that breaks it. Producer dialects differ far
more than content does, and the corpus is thin on LaTeX, Typst, InDesign and
Quartz. Run `python testkit/runall.py testkit/adv` — it exits non-zero on
regression, so it doubles as CI.

## License

[AGPL-3.0-or-later](LICENSE). exactdoc links PyMuPDF, which is AGPL-3.0; the
copyleft is inherited, not chosen.

Relicensing means replacing the parser, and the obstacle is not the API — it
is that every threshold downstream was tuned against the *shape* of PyMuPDF's
output, especially its grouping of glyphs into lines and blocks. Measured over
20 documents (`testkit/backend_probe.py`, ratio to PyMuPDF):

| axis | median | range |
|---|---|---|
| chars | 1.00 | 0.84 – 1.00 |
| lines | 0.98 | 0.73 – 1.79 |
| blocks | **1.39** | 0.55 – **3.67** |
| drawings | 1.00 | **0.04** – 1.12 |

So pdfminer.six is not a drop-in — it loses up to 16% of text and sees 4% of
the vector paths on arXiv papers. pypdfium2 (Apache-2.0) extracts text and
paths but provides no line/block grouping, so that clustering has to be
written here.

A pypdfium2 backend is written and selectable (`EXACTDOC_BACKEND=pdfium`,
requires the `[pdfium]` extra), but it is **not** the default and the licence has
**not** changed. Measured against PyMuPDF over the corpus it stands at **7
regressions** on fine placement — `within2pt` 0.510 → 0.291, median word drift
0.69pt → 2.02pt. Extraction is at parity (text character-identical, paths
exact); positional precision is not.

The gap is attributed, not guessed. Geometry is ruled out by direct measurement:
baselines identical on 4,734 of 4,734 matched lines, leadings 99–100%, sizes to
0.005pt, font names identical. What is left is **grouping** — the two parsers
put the same lines into different blocks, and grafting PyMuPDF's block
boundaries onto pdfium's geometry recovers roughly half the failing documents
outright. The other half is code-heavy and still unexplained; naming a cause for
it before measuring one is how this project has been wrong before.

Two documents diverge on purpose, both verified by rendering, and on both the
new backend is the *correct* one: RTL text (PyMuPDF returns visual order, so
its output renders Arabic backwards) and gradient bands (PyMuPDF drops them,
leaving white text invisible on white).

`testkit/golden_ir.py` freezes the current parser's output per corpus document
and checks it in CI, so the remaining work is a diff rather than a rewrite. See
[`exactdoc/backend.py`](exactdoc/backend.py) for the contract and
[STATUS.md](STATUS.md) for the numbers.

**Until the swap lands, please do not send patches to `parse.py`** —
relicensing needs every contributor's consent, and the change is confined to
that one module. Contributions anywhere else cost nothing.
