# exactdoc — status, defects, and how it was built

Every number here is measured and reproducible. Commands are given per item.
Where something is unknown, it says so; where a measurement is untrustworthy,
it says why.

Baseline for all figures: 16-document corpus, `--refine` (the CLI default),
LibreOffice render-back, PyMuPDF. **CI Linux is the number of record**
(`.github/workflows/gate.yml`); the Windows column is kept beside it because
having two independent environments agree is itself evidence. Reproduce with:

```bash
bash scripts/bootstrap.sh          # Linux: provisions the oracles, reports what it found
```

```bash
python testkit/gen_corpus.py testkit/adv --strict && python corpus/make_corpus.py
```

```bash
python testkit/corpus_manifest.py verify && python testkit/runall.py
```

---

## 1. Where the converter stands

| Metric | `raw` lane | `product` lane (shipped) | earlier CI run | Windows |
|---|---|---|---|---|
| Gate passed | 12/16 | 13/16 | 12 / 13 | 12 / 13 |
| Page count 1:1 | 13/16 | 15/16 | 13 / 15 | 13 / 15 |
| Live (editable) text | 0.9652 | 0.9652 | 0.965 | 0.965 |
| Words within 2pt of source | 0.3486 | **0.5118** | 0.366 / 0.529 | 0.361 / 0.510 |
| Median per-word vertical drift | 2.20pt | **0.62pt** | 2.20 / 0.68pt | 2.79 / 0.69pt |

The first two columns are the **recorded baseline** —
`testkit/gate_baseline.json`, measured on the canonical Linux environment
(LibreOffice 24.2.7.2, Liberation metric fonts, PyMuPDF 1.28.0 / MuPDF 1.29.0,
pypdfium2 5.12.1), which the file names in full beside the numbers. Beside them,
an earlier CI run
([#30455217670](https://github.com/ebt55/exactdoc/actions/runs/30455217670)) and
Windows.

The `within2pt` spread across those columns — 0.510 to 0.529 — is what different
LibreOffice builds and font sets cost, and it is why the gate's tolerances are
absolute-plus-proportional rather than exact. It is also why `dy_p50` gets a
proportional term: it is the one gated metric that is not a fraction, running
from 0.04pt to 101pt across the corpus, so a single absolute slack cannot serve
both ends.

**Three environments** — different fonts, three LibreOffice builds, three
Chromium builds — agree on every structural number (which documents pass, page
counts, live text, drift) and differ only in the third decimal of `within2pt`.
The harness is portable; it was only its *provisioning* that was folklore.

The gate is **both** a regression gate and, on demand, an absolute one, and it
runs fail-closed. Three documents have never cleared the thresholds, and naming
them precisely matters because an earlier version of this paragraph wrote
"D3, D4/graphics" and thereby merged two different documents with two different
causes:

| Document | Fails | Defect |
|---|---|---|
| `c3_tables` | page count, word recall 0.331, live text 0.923 | D3 nested tables |
| `c5_graphics` | live text 0.707, word recall 0.678 (raw: also page count) | D10 rasterised regions |
| `04_exec_brief` | live text 0.941, doc recall 0.934 | D10 rasterised regions |
| `c1_whitepaper` | raw lane only: page count, word recall 0.767 | D4 rounded cards |

Because those exist, `runall.py` used to exit non-zero on every run ever made and
the CI step had to ignore its own result. The record in
`testkit/gate_baseline.json` is now **numeric**: every gated metric of every
document, per lane, plus the defect ID each shortfall answers to. The gate asks
three separate questions of it —

- **regression** — is anything worse than the recorded number beyond tolerance?
  Every document, every metric, passing or not. This is the pull-request gate,
  and it is what closes the hole where a known 0.941 could have slid to 0.10
  while staying green, because the old record stored only the metric's *name*.
- **absolute** (`--absolute`) — does every document clear its release threshold?
  This is the release-qualification gate, and today it fails, by design and on
  the record.
- **stale** — does a recorded shortfall now pass? Then the record is wrong, and a
  wrong record silently re-admits the regression it exists to catch.

Both lanes gate the exit code. Gating on the refined lane alone meant the raw
lane — the control, whose whole purpose is to be untainted — was the one nobody
had to answer for. Every false-green path the previous gate had is now a test in
`tests/test_gate_mutations.py`, which needs no corpus and no oracle.

Two lanes are always reported because `refine()` tunes the layout against the
same renderer the gate measures with. A refined-only number can improve because
the loop memorised the oracle rather than because the converter got better;
only the pair is meaningful.

**Holdout: 0/4.** Four wild PDFs never used during development
(`testkit/fetch_holdout.py`). Text survives (94–97% live); pagination does not.
That is the honest generalisation number and it is worse than the corpus number
— the corpus has been developed against, the holdout has not.

### By producer dialect

| Dialect | Docs | In the gate corpus? | State |
|---|---|---|---|
| ReportLab | 6 | yes | good — page match, 94–100% live text |
| Chromium / Skia | 8 | yes | good after the P0 dialect work; was catastrophic |
| fpdf2 | 1 | yes | good |
| LibreOffice | 1 | yes | fair |
| WeasyPrint | 1 | **no** — a real document outside the corpus | good — 10/10 pages, 98% live |
| **LaTeX / pdfTeX** | **4** | **no** — the holdout | **worst — see D1** |

The third column was missing and the rows summed to 17 for a 16-document corpus,
which is the kind of arithmetic that survives in prose and cannot survive in
`testkit/corpus_manifest.json` — the manifest names all 16, their generator and
their dialect, and the gate fails if the run and the manifest disagree in either
direction.

---

## 2. Known defects, by measured severity

### D1 — LaTeX/pdfTeX pagination inflation · **severity: high**

Page counts inflate 25–90%. The dominant open defect, and the core use case
(research papers).

| Document | Source | Rendered | Inflation |
|---|---|---|---|
| `arxiv_transformer` | 15 | 18 | +20% |
| `arxiv_bert` | 16 | 20 | +25% |
| `arxiv_gpt3` | 75 | 143 | +91% |
| `nist_ai_rmf` | 48 | 51 | +6% |

Text is recovered (94–97% live), so this is placement, not loss.

**What is known.** Element growth is *not* the cause — paragraphs grow 0.7pt
each, figures 0pt. Tables did grow 8–23pt each and that is now fixed (see §4).
Re-wrap is not the cause either: renders carry *fewer* text lines than source
(1048 → 676 on one paper) while using more pages, and the dominant line pitch
matches exactly. Height is going into gaps and element heights, not extra lines.

**What is not known.** Which gaps. Three attribution attempts each produced a
partly-wrong answer, documented in §5.

```bash
python testkit/elemheight.py testkit/real/arxiv_transformer.pdf
```

### D2 — pdfium backend: fine-placement gap · **severity: low (no longer blocks relicensing)**

**This used to be the only thing keeping exactdoc off Apache-2.0. It is not any
more.** The licence is inherited, not chosen: PyMuPDF is AGPL-3.0, so exactdoc
is. A permissive parser (pypdfium2, Apache-2.0) exists in
`exactdoc/parse_pdfium.py`, and it is now measured **not worse than the
incumbent on 14 of 16 corpus documents** — four exactly equal, two better. The
flip is scheduled, not blocked: see [ROADMAP.md](ROADMAP.md) §3.2.

The two documents that remain are attributed to a font-metric convention no
permissive parser can reproduce, and are accepted as a documented divergence
rather than chased — the reasoning is below, under *The two that remain*.

The gap is **2 regressions**, down from 9 → 8 → 6 → 3 → 2. Fourteen of sixteen
documents are now at or better than the incumbent, four of them exactly equal
to it and two above it.

| | within-2pt | median dy |
|---|---|---|
| PyMuPDF (default) | **0.511** | 0.69pt |
| pdfium parser, when this was first measured | 0.291 | 2.02pt |
| **pdfium parser, now** | **0.461** | — |

**Acceptance for the flip, and it is now executable rather than stated:**
`testkit/parity_policy.json` carries the rule the test applies — comparison
margins, the two expected divergences with their rendered evidence, and these two
accepted shortfalls with **numeric floors**, recorded on the canonical
environment:

| Document | PyMuPDF | pdfium floor | fails if |
|---|---|---|---|
| `01_whitepaper_market` | 0.719 | **0.533** | within-2pt drops below the floor, or the divergence disappears |
| `02_research_paper` | 0.761 | **0.569** | same |

Both directions matter. An acceptance with no floor is an acceptance of anything,
and an acceptance that no longer describes reality is a stale record that hides
the next real regression on that document. The current verdict is **0
regressions, 11 same, 1 better, 2 expected divergences, 2 accepted** — and the CI
step is required, not `continue-on-error`.

#### What it is not

Only three quantities reach the writer's vertical model:

```
para_top    = first_baseline − (leading − 0.21 × size)
para_height = n_lines × leading
```

All three were measured across 8 documents and 4,734 matched lines
(`backend_geom.py`): **baselines identical on 4,734 of 4,734**, leadings on
99–100% of pairs, sizes to 0.005pt — an order of magnitude inside the 0.5pt
OOXML quantum. The extraction is exact.

An earlier draft of this file named "baseline or line-box geometry" as the
likely cause. That was a guess, and the measurement above falsifies it. Also
ruled out by measurement: the loose-vs-ink line box, and font naming (raw names
agree on all 494 sampled lines).

#### What it is

The parsers disagree about **grouping**, not geometry: only 35% of lines land
in a block of the same length.

`exp_regroup.py` isolates that by running a third lane — pdfium geometry with
PyMuPDF's block boundaries grafted on. The answer is bimodal. Grouping is the
entire cause on some documents and none of it on others:

| Document | PyMuPDF | pdfium | + PyMuPDF grouping |
|---|---|---|---|
| `c6_long` | 0.68 | 0.23 | **0.73** |
| `c8_toc_links` | 0.99 | 0.63 | **1.00** |
| `02_research_paper` | 0.67 | 0.57 | **0.67** |
| `c7_code` | 0.56 | 0.28 | 0.28 — unmoved |
| `r1_reportlab_report` | 0.32 | 0.21 | 0.21 — unmoved |

So grouping is about half the gap. The other half was a **serif-flag bug**,
since fixed: `_FLAG_SERIF` is read from the FontDescriptor, which the standard
14 fonts may legally omit, and a missing descriptor is indistinguishable from
one with every flag cleared — both arrive as `flags = 0`. Times-Roman,
Times-Bold and Times-Italic were called sans on every core-14 document. Adding
the name fallback that bold/italic/mono already had took style-flag
disagreement from 71 lines to 1 and the gate from 9 regressions to 7, moving
exactly the two documents predicted: `f1_fpdf_brief` 0.00 → 0.60 against
PyMuPDF's 0.62, `r1_reportlab_report` 0.21 → 0.55 against 0.60.

The one remaining flag disagreement is Calibri, where PyMuPDF reports serif for
a humanist sans. Matching it would mean reproducing a bug.

#### What is left

Converge `_build_blocks` on PyMuPDF's grouping. On the evidence above that
should clear roughly three more documents.

**The contract is `backend_parity.py`, not the golden IR.** An earlier version
of this section called `golden_ir.py` "the specification". It is not, and
saying so was steering the port at the wrong target: this backend already
refuses to reproduce three PyMuPDF behaviours because they are bugs, and
PyMuPDF's grouping is not even stable across its own releases (measured: 1.24
and 1.26 put `02_research_paper` p2 in 4 blocks, 1.28 in 7). The golden is a
microscope for locating a disagreement; the rendered-output gate decides
whether it matters.

`c7_code` and `03_tech_report_code` were "explained by neither geometry,
grouping nor fonts". They are now attributed, and it was none of the four
suspected causes: **PDFium does not report leading indentation and PyMuPDF
synthesises it.** For `    def __init__(...)` PDFium's first character is `d`
at x=93.17 with no space before it; PyMuPDF reports the line starting at
x=72.25 with four leading spaces. PDFium synthesises spaces *between*
characters, where there is a gap to measure; at a line start there is nothing
to the left, so the indent vanishes and every glyph on the line is displaced.
Both documents now sit at or above the incumbent.

#### The two that remain, and why

`01_whitepaper_market` (0.53 against 0.72) and `02_research_paper` (0.57
against 0.76) are attributed to a **font-metric convention difference that no
permissive parser can reproduce.**

`infer()` derives the page's vertical origin from line-box *tops*. That is the
one vertical quantity two correct parsers legitimately disagree about, because
each reads it from font-metric tables the other does not have:

| font | PyMuPDF above/below baseline, per size | pdfium |
|---|---|---|
| Helvetica | 1.075 / 0.299 | 0.905 / 0.211 |
| Times-Roman | 1.053 / 0.281 | 0.891 / 0.215 |
| **Symbol** | **1.010 / 0.293** | **1.010 / 0.293** |

Symbol is the control: where both fall back to the *embedded* font's metrics
they agree to three decimals. Everywhere else PyMuPDF is using its own base-14
table. The difference reaches `margin_t` (63.30 against 64.90 on
`02_research_paper`) and displaces every word on the page by a constant 1.5pt —
visible as two identical dy distributions offset by exactly that.

**Parser-side exhaustion is proven, not assumed.** `FPDFFont_GetAscent` and
`FPDFFont_GetDescent` return exactly the ratios the loose box already uses;
pdfium exposes one vertical font metric and the parser is already using it.
Reproducing PyMuPDF's numbers would mean vendoring MuPDF's base-14 table into
the permissive tree, which the licence plan forbids and which is measurably
version-dependent.

A shared-pipeline fix was granted, built and **reverted**: anchoring the origin
on baselines instead reached 0.000pt backend agreement on 14 of 16 documents,
but cost the *incumbent* `c6_long` 0.76 → 0.45, because the `space_before`
chain downstream is itself calibrated against a box-top origin. Making the
vertical model baseline-consistent means moving the origin, `_para_box` and the
spacing chain together — a larger change than this defect justifies on its own.
Evidence: `testkit/margin_probe.py`, and the escalation packet in the project's
planning documents.

```bash
python testkit/backend_parity.py
```

```bash
python testkit/backend_geom.py --all && python testkit/exp_regroup.py
```

### D3 — Nested tables flatten · **severity: medium**

`c3_tables` renders 3 source pages as 4 on *both* backends. Inner-table borders
land in the wrong places and cell content merges. Pre-existing, not a swap
regression.

### D4 — Rounded-corner card rows stack diagonally · **severity: medium**

`border-radius` makes a card's background a curve, and the card-row detector
requires `shape == "rect"`. A three-card stat row renders as a descending
staircase (`c1_whitepaper`).

### D5 — Letter-spaced headings lose their spaces · **severity: medium**

"TECHNICAL SKILLS" → "TECHNICALSKILLS". Tracking-spaced text is drawn as
positioned glyphs; the gap-to-space threshold that is correct for body text is
too large at heading sizes. Visible on the resume sample.

### D6 — Mixed page geometry discarded · **severity: medium**

`DocLayout` takes `page_w`/`page_h` from page 1 and applies it document-wide.
A portrait + landscape + A3 document emits **one** section at one page size.

```bash
python testkit/edge_cases.py
```

### D7 — Google Docs is a harder target than LibreOffice · **severity: medium**

On the *same* DOCX, with the `--target gdocs` static fix applied:

| | LibreOffice | Google Docs |
|---|---|---|
| mean within-2pt | 0.404 | ~0.20 |
| page match | 17/18 | 11/16 |

The LibreOffice column is from the 18-document corpus of the time and the Docs
column from the current 16; the two are not directly comparable and the
comparison has not been rerun on one corpus. The *direction* is the finding —
Docs is the harder target — not the ratio.

Docs has no "exact" line spacing, so its importer mistranslates
`lineRule="exact"` — error scaling with font size (+45pt at 18pt type, +84pt at
22pt). `--target gdocs` emits multiples instead, which recovers most of it
(median drift 23.1pt → 3.4pt), but Docs remains behind.

**Untested and at risk:** the full-bleed cover band depends on a mid-document
section with different L/R margins, and Docs flattens per-section page
geometry. Never measured.

### D8 — Encrypted and truncated PDFs raise raw exceptions · **severity: low**

`ValueError: document closed or encrypted` instead of a clean unsupported-input
error. All other degenerate inputs (empty, image-only, landscape, rotated,
tiny, dense microtype) convert without crashing.

### D9 — `w:shd` emitted 17,112 times across 18 documents · **severity: low**

*(Counted on the 18-document corpus of the time; not recounted on the current
16. The order of magnitude is the point.)*

Shading applied very aggressively per-run/per-cell. File-size and complexity
smell, not a correctness bug.

### D10 — text inside rasterised regions is not live text · **severity: medium**

The defect ID the gate baseline needed. Two documents have never cleared the
0.95 live-text threshold and the reason was recorded only as prose, which meant
`04_exec_brief`'s 0.941 could have fallen to 0.10 without the gate noticing —
the old baseline stored the metric's *name*, not its value.

| Document | live text | doc recall | with figure regions excluded |
|---|---|---|---|
| `c5_graphics` | 0.707 | 0.678 | **0.988** |
| `04_exec_brief` | 0.941 | 0.934 | **0.978** |
| `c3_tables` (D3) | 0.923 | 0.936 | 0.966 |

The third column is `exactdoc/verify.py:audit()`, which excludes figure-region
text from its denominator — the converter's own view, and the one STATUS §4.5
warns not to trust alone. Read only as an attribution it says: **rasterisation
is the dominant cause on all three and the whole cause on none.** `c5_graphics`
loses 28 points of coverage to a gradient band and an SVG chart that must
rasterise (§6.5), and recovers 28 of them when those regions are excluded.
`04_exec_brief` recovers most but not all of its 6 points. The residual is
**unattributed** and deliberately not guessed at.

Not the same defect as D3: `c3_tables` fails structurally (word recall 0.331,
one page over), and its live-text shortfall is a symptom of the nested-table
flattening rather than of a figure.

```bash
python testkit/runall.py --lane product --absolute
```

---

## 3. Pending work, in the order I would do it

**Sequence and distance live in [ROADMAP.md](ROADMAP.md).** This table is the
defect view; the roadmap is the plan view.

**D2 is no longer a blocker.** The permissive parser is at 2 regressions from 9,
both attributed and accepted as a documented divergence, so the relicence can
proceed. That was the only thing gating it.

| # | Item | Blocks | Notes |
|---|---|---|---|
| ~~1~~ | ~~Superscript in the pdfium backend~~ | — | **Closed by measurement, no code written.** `backend_superscript.py`: the writer never sees the parser's flag — `dialect` and `infer` recover superscript from geometry, and all 16 documents agree at the layout level. ROADMAP §3.1 |
| 2 | **The flip and the relicence** | **the whole point of the project** | **Not mechanical.** `fitz` is on the default *runtime* path well past the parser: `docxout.py` imports it at module load and uses MuPDF text metrics for table fitting and MuPDF rasterisation for figure clips, `refine.py` extracts text through it, `verify.py` compares images with it, `ladder.py` measures with it. A wheel installed without PyMuPDF fails while importing the writer, before any backend selection happens. The backend has to be chosen once and carried through parse, write, refine and verify first |
| 3 | **D8 clean unsupported-input error** | the release | Encrypted/truncated PDFs; both files into CI |
| 4 | **PyPI release** | adoption | TestPyPI dry run first; release notes lead with the holdout |
| 5 | **D1 LaTeX pagination** | the holdout, and the core use case | Needs writer-side instrumentation (§5) — per-element emitted-vs-source height accounting inside `docxout` — not another hypothesis. Three attempts have each produced a partly-wrong answer |
| 6 | **The baseline-consistent vertical model** | the last 2 parity regressions, and probably much else | Move `margin_t`, `_para_box` and the `space_before` chain together. A partial version was granted, built and reverted (D2) — the origin alone desynchronises from the spacing calibrated against it |
| 7 | **Google Docs cover-band check** | a real claim in the README | One oracle run; may invalidate the design. The least-measured part of the stated product goal |
| 8 | Un-gate the wrap correction | fidelity | Needs predicted `n_lines` in the page-capacity model *before* the first write, or it costs a page |
| 9 | D3, D4, D5, D6, D9 | — | Bounded, independent |

Not planned: OCR for scanned PDFs; CJK/RTL shaping beyond the reordering
already done; forms.

---

## 4. Approaches used in building this

### 4.1 The core architecture

```
PDF ──parse──▶ IR ──normalise──▶ IR ──infer──▶ Layout ──write──▶ DOCX ──refine──▶ DOCX
     pypdfium2/     dialect.py       heuristics    OOXML subset    render & correct
     PyMuPDF
```

A PDF is a painting: absolutely positioned glyphs and paths with no semantics.
A DOCX is a program: a flow that a renderer lays out again. Conversion is
**decompilation** — recovering the program that would repaint the page.

The output is restricted to a **Google-Docs-safe vocabulary**: styled
paragraphs, fixed-layout tables with per-side borders and shading, section
geometry, true column sections, inline images, headers/footers with fields,
tab stops, hyperlinks. Nothing else. Verified by `testkit/ooxml_audit.py`: no
VML, no text boxes, no floating frames anywhere in the corpus output.

### 4.2 Producer-dialect normalisation

The same visual element is emitted completely differently by different
generators. A list bullet:

| Generator | How it reaches the PDF |
|---|---|
| ReportLab | a text character, same block, gap ≥ 4pt |
| WeasyPrint | a text character, *separate* block, butted flush |
| **Chromium** | **not text at all — a filled bezier circle** |

Inference thresholds were originally calibrated on ReportLab, so they encoded
*"how ReportLab draws things"* rather than *"what a bullet is"*. `dialect.py`
rewrites producer idioms into one canonical form before inference runs, keyed
on **evidence in the page, never on the `/Producer` string** — those are absent
(fpdf2 writes none), rewritten by post-processors, and version-dependent, and a
metadata switch fails hardest on the first unknown producer.

### 4.3 Closed-loop correction

The converter was open-loop: predict how Word will lay out, and hope.
`verify.py` already rendered the result and measured the difference — it just
never fed the answer back. `refine.py` closes it: write → render → measure
overflow and per-page offset → correct → rewrite, keeping the best round.

Justification: fitting a per-page affine trend to word drift removed **77%** of
the vertical error (mean |dy| 4.01pt → 0.93pt). Two pages of one paper were
internally near-perfect (residual 0.03pt) while sitting 12pt too high — one
anchoring bug, not a layout problem.

### 4.4 Root cause before compensator

Repeatedly, the compensator was the wrong tool and the law was findable:

- Google Docs' "+28pt after the first heading" turned out to be its importer
  mistranslating `lineRule="exact"`, error scaling with font size. Replacing
  per-document loop correction with a **static** rule improved Docs within-2pt
  **10×** at zero conversion cost.
- Chromium rasterising whole pages traced to an invisible white page-background
  rect merging every drawing into one cluster, plus bullets-as-beziers.

### 4.5 Verification philosophy

The testkit shares **no code** with the converter. The original `verify.py`
called `infer()` to decide which source text to exclude from its own coverage
denominator — so anything the converter rasterised vanished from its own score.
On the resume it reported `src_chars: 0`. **A converter must not define its own
ground truth.**

Metrics, and why each exists:

| Metric | Catches |
|---|---|
| `page_match` | the loudest failure |
| `live_text_cov` | **raster-blind** — text baked into an image counts as lost |
| `doc_recall` | content survived anywhere |
| `word_recall` | content on the right *page* |
| `within2pt` | fine placement — the dimension a coarse test misses |
| `ink_iou`, `ssim` | whole-page sanity |

**SSIM is never the headline.** It is dominated by whitespace and it *rewards*
a rasterised page: a resume converted to two flat images scored 0.594,
comparable to genuinely good conversions.

Supporting discipline: two gate lanes (refine on/off) so oracle memorisation is
visible; a **holdout** set never used during development; golden IR frozen and
CI-checked; CI on a pinned Linux oracle because local Windows renders with real
Arial/Times and wraps differently.

---

## 5. Measurement mistakes made, and what they cost

These are recorded because each one produced a confident wrong answer, and the
pattern is more useful than the individual fixes.

| Mistake | Symptom | Lesson |
|---|---|---|
| Parity harness omitted `within2pt` | Reported **0 regressions**; the swap actually cost within-2pt 0.510 → 0.291. The default was flipped and the licence changed before the gate caught it | A test is only as good as the dimensions it measures; the forgotten dimension is where the regression hides |
| Harness reused stale renders | A real fix looked like a no-op | Never cache on existence alone — require the render to be newer than the input |
| Bucketed injections by *location* | Reported "65% is space_before" for intervals whose `space_before` was 0–10pt | Naming a location is not naming a cause |
| Element-gap attribution | Impossible values (130pt between adjacent paragraphs at `sb=0`); aggregate flipped sign between documents | Line-text matching cannot attribute vertical space once content reflows |
| `spaninflate` on repeated running heads | 46,000pt of "inflation" on one page | Disclosed in the tool rather than silently trusted |
| Probes matched non-unique strings | Measured body-text "ByteNet", not the table | Match on text that is unique on both sides |
| Wrote a hypothesis into D2 as if it were a finding | "Most likely baseline or line-box geometry" survived a full revision of this file; the first direct measurement showed baselines identical on 4,734 of 4,734 lines | A plausible cause in a defect register is read as a known one. Mark it as a guess or measure it |
| Imported `pypdfium2` without declaring it | `uv sync` evicted it; the parity gate began reporting `ModuleNotFoundError` | A gate that cannot run looks exactly like a gate that passes |
| Gated on *any* failure, with three documents that had never passed | `runall.py` returned non-zero on every run it ever made, so the CI step was marked `continue-on-error` and nothing was gated at all | A check that always fails carries the same information as one that always passes. Gate on the *delta* against a recorded set |
| Tokenised words on whitespace, which CJK does not use | A "word" was a whole rendered line; a one-character re-wrap lost it. `c4_i18n` scored `doc_recall` 0.83 on Linux and passed on Windows **with every character present in both** | The unit a metric counts in must be a unit the content actually has |
| Read golden drift as parser drift | A version-dependent difference (PyMuPDF 1.26 groups `02_research_paper` p2 into 4 blocks, 1.28 into 7) was recorded as cross-platform instability | A frozen artifact without a manifest of what froze it cannot tell you which of the two changed |
| Recorded the *names* of failing metrics, not their values | `04_exec_brief`'s live-text coverage was on record as "known failing" at 0.941. It could have fallen to 0.10 and stayed exactly as green. Same hole in `page_match`, a boolean that cannot tell one page over from forty | A known failure needs a *bound*, not a label. Record the number |
| Treated a missing measurement as a skip | `harness.evaluate()` returns `{"error": ...}` when the render fails and nothing read the key; absent metrics hit `if v is None: continue`. A renderer dying on all 16 documents scored zero failures | Fail closed. A metric that could not be computed is a failure, never a row to pass over |
| Never checked the corpus against a manifest | Measured in a bare container: the generator produced 3 of 16 documents, printed "the corpus is incomplete, numbers are NOT comparable", exited 0 — and the gate scored those 3 against a 16-document baseline and reported a pass | Prose that the next step ignores is not a safeguard. `--strict`, and a manifest the gate compares against in both directions |
| Wrote the oracle paths to a file nobody sourced | `bootstrap.sh` discovers Chromium and writes `scripts/env.sh`, then every subsequent shell — including each CI step — starts without it. CI only ever worked because the GitHub runner image happens to ship `/usr/bin/google-chrome`: provisioning by accident | Discovery has to be readable by the thing that needs it. `_paths.py` now reads the record itself |
| Let the executable rule and the ratified rule disagree | `backend_parity.py` exited on `regressions == 0` while ROADMAP and this file said two documents were formally accepted. The disagreement was resolved by marking the CI step `continue-on-error`, which retired the one gate the entire relicensing effort was aimed at | A gate whose policy lives in prose will be switched off, not corrected. Put the policy in a file the test reads |
| Injected a parser by assigning a module global | The instruments set `exactdoc.convert.parse_pdf`. That worked only because `convert` happened to hold the parser as a global; once the backend was selected through the seam, the assignment became a no-op that set an attribute nobody read — and an experiment that silently measures the default still prints a number | An injection point should be declared (`register_backend`), so removing it breaks loudly instead of quietly |

Two compensators were built, measured, and **left switched off** because they
did not pay: the quality ladder (line-locking) and the half-point wrap
correction. Both fix something real; neither moved page counts, and shipping a
measured regression would have been worse than shipping nothing.

---

## 6. What is not achievable

Stated as limits, not bugs:

1. **Pixel-perfect *and* editable is a contradiction.** Text reflowed by a
   different engine will occasionally break a line differently, and everything
   below a changed break moves. Rare, not eliminable.
2. **OOXML quantises font size to 0.5pt.** A 10.1pt source font cannot be
   emitted at 10.1pt. Compensable via wrap width; not removable.
3. **Google Docs ignores embedded fonts.** Metric-compatible substitution is
   the ceiling.
4. **Docs flattens per-section page geometry**, which puts full-bleed cover
   bands permanently at risk.
5. **Gradients, rounded corners and rotated text** have no paragraph-flow
   equivalent and must rasterise.
6. **Scanned PDFs** need OCR; out of scope.

For text-flow documents — whitepapers, papers, reports, resumes — *visually
indistinguishable at normal zoom and fully editable* is reachable. Everything
in §2 is a bug, not a limit.
