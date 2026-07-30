# exactdoc

**PDF → DOCX that keeps the design, survives Google Docs, and measures whether it worked.**

> **Status: alpha (0.1.0a1). Nothing has been released yet.** It works well on the
> documents it was developed against and it fails on pagination for PDFs it has
> never seen. Both numbers are below, in the same table, on purpose.
>
> **Next: the permissive relicence.** The AGPL is inherited from PyMuPDF. Every
> stage of the pipeline can now run without it — but the shipped default still
> uses it, and the parity gate currently **fails on 2 unwaived regressions** that
> a weaker comparison had been reporting as "same". The flip to Apache-2.0 is the
> next milestone; [ROADMAP.md](ROADMAP.md) has the sequence and the distance.
>
> Numbers below were measured on the canonical Linux environment and recorded in
> `testkit/gate_baseline.json`. Where they come from local commits that GitHub
> Actions has not yet run, that is stated rather than implied.

Most PDF-to-Word converters either redesign your page (Word's reflow), turn every
line into a floating frame that Google Docs then mangles (LibreOffice import), or
throw the design away entirely and emit Markdown (Docling, Marker, MinerU).
[`pdf2docx`](https://pypi.org/project/pdf2docx/), the usual Python answer, is no
longer actively maintained by Artifex.

exactdoc decompiles the page instead: it recovers paragraphs, tables, callouts,
columns and rules as real editable Word constructs, restricted to the subset
Google Docs imports faithfully — no text boxes, no VML, no embedded fonts.

Then it checks its own work. Every claim below is a number produced by
[`testkit/`](testkit/README.md), which shares no code with the converter, and
every one of them traces to a single machine-readable artifact —
`testkit/batch/evidence.json`, keyed to the commit, the dependency versions and
the LibreOffice build that produced it. [STATUS.md](STATUS.md) is the authority
on what they mean:

| | 16-document corpus | 4 wild PDFs (holdout) |
|---|---|---|
| gate passed | 13/16 | **0/4** |
| page count 1:1 | 15/16 | fails |
| live (editable) text recovered | 96.5% | 94–97% |
| words within 2pt of source | 51.2% | — |
| median per-word vertical drift | 0.62pt | — |

The corpus has been developed against; the [holdout](testkit/fetch_holdout.py)
never has. The gap between those two columns is the honest measure of how far
along this is: **the text survives, the pagination does not.**

The corpus column is the `product` lane — the profile a bare `exactdoc file.pdf`
or `convert(file)` actually runs, which is now the same profile the numbers are
measured on. It was not: the API ran 0 refine rounds, the CLI ran 2, and these
figures came from a CI lane that ran 3, so "reproduce it with `convert()`"
produced the raw number with nothing anywhere to say why. There is one profile
now ([`exactdoc/options.py`](exactdoc/options.py)), and the uncontaminated
zero-refine `raw` lane is reported beside it always, because the refine loop
tunes against the same renderer the gate measures with.

## Install

Not on PyPI yet — the first published release will be the Apache-2.0 one (see
[Versions](#versions)). Until then:

```bash
pip install git+https://github.com/ebt55/exactdoc.git
```

Optional extras: `[test]` for the measurement harness, `[pdfium]` for the
permissive parser, `[gdocs]` for the Google Docs oracle. None is needed for a
plain conversion.

`--verify` and `--refine` additionally need LibreOffice on PATH; without it,
conversion still works and simply skips the feedback loop.

**`--backend pdfium` needs no PyMuPDF at any stage. The shipped default still
does.** Those are two different statements and only the first is finished. The
*code paths* — parsing, figure rasterisation, table measurement, the refinement
loop, the verifier — now go through the backend seam or the IR's own facts, and
[`tests/test_no_pymupdf.py`](tests/test_no_pymupdf.py) proves it by making `fitz`
*unimportable* and then converting a fixture per capability. But `pymupdf` is
still the default backend and still a hard runtime dependency in
`pyproject.toml`, so `pip install exactdoc` installs it and an unmodified
conversion uses it.

What changed is that the licence flip is now a dependency-and-default change
rather than a rewrite, which is what it had been described as while five stages
past the parser still imported `fitz` directly. See
[STATUS.md §7](STATUS.md#7-the-permissive-runtime-boundary).

One feature is knowingly outside the boundary: `--ladder` predicts a re-wrap,
which means shaping text that has no source line to measure, so it needs the
`[mupdf]` extra and reports plainly when it has no shaper. It is off by default.

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
from exactdoc import convert
convert("whitepaper.pdf", "whitepaper.docx", target="gdocs")
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

`--refine N` writes the DOCX, renders it back through the chosen target, measures
page overflow and per-page offsets, corrects the layout and rewrites — keeping the
best round. Without an oracle available it degrades to a single ordinary write, so
conversion never depends on it.

The default is 3, and it is 3 everywhere: the CLI, the Python API and the lane
every published number is measured on all read it from one place
([`exactdoc/options.py`](exactdoc/options.py)). `--refine 0` is the deliberate
open-loop control.

Python API — same profile, no arguments needed:

```python
from exactdoc import convert
convert("whitepaper.pdf", "whitepaper.docx")
```

## How it works

1. **Parse** (`backend.py` → `parse.py` or `parse_pdfium.py`) — the chosen
   backend extracts every text span (font, size, weight, color, exact position),
   vector drawing, image and link into an intermediate model. The backend is
   selected **once per conversion** and carried through writing, refinement and
   verification, so those stages ask it for a clip render or a page's text lines
   rather than importing a parser of their own — which is what they used to do,
   and why the wheel could not run without PyMuPDF.
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
   side-by-side comparison images. These are *diagnostics about your document*,
   not release evidence: the audit excludes rasterised regions from its own
   denominator, which lets the converter grade its own homework.
   [`testkit/`](testkit/README.md) is the independent measurement and shares no
   code with any of the above.

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

| | `raw` (0 refine rounds) | `product` (shipped) |
|---|---|---|
| gate passed | 12/16 | 13/16 |
| page count 1:1 | 13/16 | 15/16 |
| live (editable) text | 96.5% | 96.5% |
| words within 2pt of source | 34.9% | **51.2%** |
| median per-word vertical drift | 2.20pt | **0.62pt** |

Every figure comes from `testkit/gate_baseline.json`, which records the numeric
value of every gated metric for every document in both lanes, together with the
environment that produced it — Linux, LibreOffice 24.2.7.2, the Liberation metric
fonts, and the exact dependency versions. Three environments (CI Linux, a local
`ubuntu:24.04` container, Windows) agree on every structural number and differ in
the third decimal of `within2pt`; the gate's tolerances are sized from that
spread.

`refine()` optimises against the same renderer the gate scores with, so a
refined-only number can improve because the loop memorised the oracle rather
than because the converter got better. Reporting one lane would hide that — and
until recently the exit code did exactly that, gating on the refined lane while
the control lane could regress freely.

Run it yourself (needs the `[test]` extra, LibreOffice for the render-back, and
Chrome to generate the Chromium half of the corpus):

The 16 inputs are frozen in `testkit/fixtures/` and pinned by SHA-256, so no
browser is involved in reproducing a number — a regenerated corpus is not the same
corpus, and proving that cost three red CI runs:

```bash
python testkit/corpus_manifest.py verify && python testkit/runall.py
```

Both lanes gate the exit code, so it doubles as CI. Add `--absolute` for the
release-qualification gate, which **fails today** — D3 and D10 sit below
threshold, and the point of a separate absolute gate is that it says so instead
of being folded into "nothing got worse".

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

- [ROADMAP.md](ROADMAP.md) — what is done, what is left, and how far. Start here
  if you want to know where this is going
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
Quartz. Run `python testkit/runall.py` — both lanes gate the exit code, so it
doubles as CI, and `python tests/test_gate_mutations.py` checks the gate itself
in about a second without needing a corpus or an oracle.

## License

[AGPL-3.0-or-later](LICENSE) **today, Apache-2.0 next.** exactdoc links PyMuPDF,
which is AGPL-3.0; the copyleft is inherited, not chosen — and the permissive
replacement parser is now measured good enough to take over. The flip is the
next milestone, and no AGPL wheel will ever be published: see
[ROADMAP.md](ROADMAP.md).

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

A pypdfium2 backend is written and selectable (`--backend pdfium`, or
`EXACTDOC_BACKEND=pdfium`; requires the `[pdfium]` extra). It is not the default
*yet* — but it is no longer the blocker it was, and the rest of the pipeline no
longer needs PyMuPDF either.

Measured against PyMuPDF over the corpus, under the acceptance policy in
[`testkit/parity_policy.json`](testkit/parity_policy.json), with **both** lanes
reading end-to-end through their own backend — mean within-2pt 0.5118 for PyMuPDF
against 0.4431 for pdfium:

| verdict | count | which |
|---|---|---|
| **unwaived regression** | **2** | `05_memo`, `f1_fpdf_brief` — both vertical drift |
| same | 5 | |
| better | 3 | incl. `04_exec_brief`, `l1_word_native` |
| expected divergence | 2 | `c4_i18n`, `c5_graphics` — pdfium is the *correct* one, verified by rendering |
| **provisional** accepted shortfall | 4 | all core-14, all STATUS D2, each bounded by a recorded numeric floor |

**The parity gate fails today, and that is the honest state.** It reported "0
regressions" until the comparison was fixed to judge every dimension
independently — it had been stopping at the first dimension outside its margin, so
one improvement suppressed every regression after it, and vertical drift was not
among the dimensions at all. Two documents were drifting by more than a point
while the gate said "same".

The four accepted shortfalls are **provisional**: waiving four of sixteen
documents rather than two is a product decision awaiting the maintainer, not a
measurement. The two new regressions are fully attributed — both are D2, in its
two known locations, confirmed by re-running with refinement off — and are
deliberately *not* waived. [STATUS.md D2](STATUS.md) has the measurements,
including the cleanest statement of D2 in the repository: on `05_memo` the two
parsers agree on every baseline to 0.00pt and disagree on every line-box top by
1.5pt, which is exactly the page-origin shift.

Down from 9 regressions. Those six documents used to be prose: the code exited on
`regressions == 0` while the docs said two of them were formally accepted, so CI
marked the step `continue-on-error` to keep the build usable — which retired the
only gate the whole relicensing effort was aimed at. The policy is now data the
test executes, every acceptance carries a numeric floor that fails when crossed,
and an acceptance that stops describing reality fails as stale. The step is
required.

The accepted set grew from two documents to four, and that is worth reading
carefully, because it is a *measurement* getting more honest rather than a
converter getting worse. Until the permissive runtime boundary landed, `refine.py`
read its measurement through PyMuPDF whichever backend had parsed — so the
candidate lane was pdfium parsing with MuPDF measuring, a configuration nobody
could install. Reading both through the backend that parsed adds two ReportLab
documents to the accepted set under the same proven-unreachable cause: on core-14
fonts PDFium reports a generic ascent where MuPDF reports the real one, and the
metric-compatible render font agrees with MuPDF. Every document that embeds its
fonts is unaffected. [STATUS.md §7](STATUS.md#7-the-permissive-runtime-boundary)
has the arithmetic and the fix that was tried and measured wrong.

The remaining two are attributed, and the attribution is why they are being
accepted rather than chased: `infer()` derives the page's vertical origin from
line-box *tops*, which is the one vertical quantity two correct parsers
legitimately disagree about, because each reads it from font-metric tables the
other does not have. PyMuPDF puts Helvetica's box 1.075× the type size above the
baseline; pdfium says 0.905×. On Symbol, where both fall back to the *embedded*
font's metrics, they agree to three decimals — which is how we know it is the
tables and not the code. pdfium exposes exactly one vertical font metric and the
parser already uses it, so matching PyMuPDF would mean vendoring MuPDF's own
base-14 table into a permissive tree. That is not something this project will
do. See [STATUS.md](STATUS.md) D2 and [ROADMAP.md](ROADMAP.md) §4.

Everything else that separated the two parsers has been closed: extraction was
always at parity (text character-identical, baselines identical on 4,734 of
4,734 lines, paths exact), and grouping, path geometry, span segmentation and
whitespace now match the incumbent exactly on every document where they can.

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
