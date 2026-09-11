# Changelog

Notable changes to exactdoc. Every quality number in this file is measured in
the canonical environment (`docker/gate.Dockerfile`, pinned by digest) and
traceable to a committed artifact under `docs/evidence/`.

## Unreleased — porting the live-verified defect catalogue into the converter

Between 2026-09-05 and 2026-09-07 a 32-page real report was converted and taken
to CLEAN 1:1 in Google Docs through seven rounds of hand surgery on the output
DOCX, with the converter deliberately frozen. That campaign's defect catalogue
(recorded in the handoff; summarised below) is being ported into the converter
one verified fix at a time, each gated against the frozen 16.

Ported so far, all first verified live on Google's own render:

- **#6 the cells the parser joins.** Adjacent table cells whose gap is under
  the parser's join threshold arrive as one Line; spans keep their own
  boxes, so `build_grid_table` now fragments each line at the drawn column
  bands and assigns spans by their own centres. On the same principle a
  "single line" wider than its column is a straddler, not a need, when the
  column edges were read from the author's grid lines — a 40pt joined
  header span over a 28.5pt column had been driving `_fit_col_widths` to
  shave every neighbour (the family table now holds the drawn pitch to
  0.1pt).
- **#5 (writer half) quote bars are paragraph borders under the gdocs
  profile.** Inside a table cell every quote line rendered 1-2pt taller
  than source in Docs — ~40 lines to a block, the block outgrew its page
  and the spill cascaded. As body paragraphs the same lines carry the
  profile's calibrated line encoding, and the bar is one continuous
  `pBdr` left border (`sz=12 space=8 #BBBBBB`, the live-verified form).
- **#7 (writer half) gdocs table-row levers from the hand campaign's
  round 4**: rows pinned to `trHeight atLeast` = source height; bottom pad
  cut so content lands on `floor(srcH) − 0.75` (Docs rounds every row box
  up to a whole point — that rounding alone measured +1.27pt/row); tcMar
  right trimmed a point (Docs charges the cell border against the text
  area); cell paragraph marks sized to content (inert in Docs, correct for
  Word). Clean rows now land +0.5pt on Google's export.

- **#3 the text column is where the document's own full-width rules end, when
  the text cannot say it in sufficient mass.** A ragged-right document keeps
  its flush edge below the wide-line estimator's 8% membership floor, so the
  rightmost qualifying cluster is an interior band of line ends; on the report
  that cost ~19.5pt of column width and nearly doubled the page count. The
  rule-evidence widener (`_rule_right_edge`) reads the document's rules
  instead — unanimous, 32 rules at one edge — and widens only, never narrows,
  only past the p90 of wide-line ends (a decorative rule overshooting a
  correctly-measured column is rejected: 01_whitepaper's 6pt overshoot moved a
  gated margin before that guard existed, and the Docker gate caught it).
- **#4 Consolas maps to itself.** It was mapped to Courier New, 9% wider, so
  every inline-code run wrapped early. Measured from the font file: 0.550em
  advance (a true monospace), natural factor 1.171 (hhea 1521/−527/350 over
  2048). Google Docs honours a declared Consolas — verified in export spans.
- **#10 a hyphen is only a word break where hyphenation happens.** The join
  dehyphenated every line-end hyphen before a lowercase continuation; on a
  ragged-right report all 41 of them were real text (37 deleted, 4 spaced).
  Dehyphenation now requires a justified paragraph at its wrap edge — a
  ragged-right line keeps its hyphen and joins without a space.
- **#2 a verbatim block keeps its line breaks.** A block whose every glyph is
  monospace is code, not prose; its lines are now separated by breaks the
  writer renders as `w:br`, and break-carrying paragraphs do not merge.
- **#5 quote bars are bars, not pictures.** A 1.5pt-wide vertical rule 100pt+
  tall marking text to its right is a quote bar; the old 1.8pt width floor
  rejected every one (6 then rasterised as ~300pt-tall lines, 56 dropped).
  Vertically-contiguous segments at the same x merge before the quote test.
- **named Heading styles, so Google Docs' outline exists.** Converted
  documents carried only `w:outlineLvl`, which Word's navigation pane reads
  and Google Docs' outline sidebar ignores: every paragraph read "Normal
  text". Headings now carry `Heading 1..6`, with the stock style definitions
  rewritten to explicit zeros (an absent pPr is not a zero pPr — LibreOffice
  supplies its own spacing for a silent "heading 1", which moved a gated
  document's raw lane before the zeros were written).

Measured after the ports, in the canonical container: **gate PASS both lanes
at the recorded baseline numbers** (product 16/16 pages, 0.5274 within-2pt,
0.9588 live text, 1.045pt dy50). The live B13 report went from **58 export
pages before to CLEAN 1:1 at 32** across twelve live rounds — every source
page mapping to exactly one export page, no blanks, no spills, no orphans
(`docs/evidence/gdocs-2026-09-11-b13-align-final.json`) — and the conversion
carries the heading outline the hand-patched file never had. The closing
ports: single-span cell joins split at drawn boundaries by advance
arithmetic (space-guarded), a gdocs column minimum of 22pt funded
proportionally, the single-line pitch bias (−0.38pt), and pageBreakBefore in
place of carrier paragraphs under the gdocs profile — the double-fire class
the hand campaign left "unproven in Docs", now proven absent live. 34 new
unit tests cover the fixes.

Corpus tranche 3 (see `docs/corpus-expansion.md` §12): acquisition reopened for
the two named shortfalls; ten documents fetched, licence-verified and sealed
(16 gated + 41 expansion = 57), adding six producer chains the corpus had
never held — Typst, XeLaTeX, LuaTeX+ConTeXt, pandoc, Arbortext+PDFlib,
Word→PostScript→Distiller — and closing LaTeX-light 1→6, other real-world
1→6. Non-gating, as §7 requires.

- **the booklet class, fixed at the root (detection, then flow).** Three
  coordinated changes: the gutter scan reads only narrow lines (≤0.62 of the
  content width) so a spanning caution line can no longer veto a genuine
  three-column page, with an 80pt band-width floor holding narrow byte
  tables out; "wide tail" means crossing the drawn gutter pair, not 62% of
  the page; and runs of same-shape grid pages merge into one continuous
  section whose per-page column breaks drop for natural fill. Measured in
  the canonical container, product lane: y06 294→226 pages (2.33×→1.79×),
  y13 66→59, y12 85→84; gate PASS both lanes unchanged; suite 705 OK.
- **the writer's document flow: a booklet is one flow.** After the run
  merges, ~36 run boundaries each cost a NEW_PAGE section whose leftover
  the renderer cannot refill (~half a page each). Inside the booklet
  signature, same-shape synthetic pages now continue with no break and
  column-shape changes are CONTINUOUS section breaks; the gated corpus
  keeps its page seams unchanged. Two defects the flow's render exposed,
  both fixed: tables inside a column flow size against their column, not
  the page (a table cannot wrap); and pages carrying a table or figure
  wider than a booklet column are excluded from run membership -- y06's
  405pt source worksheets over 3-col instructions were colliding with the
  neighbouring columns' text on six rendered pages. Measured: y06 226 ->
  **198** (2.33x -> 1.57x from the campaign's start), y13 59 -> **53**
  (2.13x -> 1.71x), y12 84 -> 83. Gate PASS both lanes at the recorded
  baseline; suite 719 OK.
- **the booklet document-flow merge, and the page-relative gap cap.** The
  "measured band widths" lever named for y06's residual was disproved by
  its own probe (the snapped bands measure 165.5-166pt; the emission
  writes 165.50), and the decomposition found the +100 pages were pure
  fragmentation on the NON-grid pages: the export carries the same text
  in fewer lines (36,090 vs 40,752) at the exact source pitch. Inside
  booklet-class documents (>= 10 pages with a >=3-col grid and >= 35% of
  the document — the gated 16 carry no >=3-col page, so this cannot fire
  there), `_merge_grid_page_runs` now also merges runs of consecutive
  all-1-col pages (and 2-col runs merge like grid runs), dropping their
  per-page seams while full-width content stays in 1-col sections. Joined
  pages carry gaps capped at 48pt: the fabricated dead space was
  page-relative offsets (a bottom-pinned tail's distance from its page's
  content), 18,300pt of it on the first attempt's render. Measured in the
  canonical container: y06 294->226->**203** (2.33x -> 1.61x total),
  y12 84->**83**, y13 66->59->**58**. Gate: product lane PASS with
  within-2pt **0.5361 -> 0.5445 better** (the cap tightens a gated
  document's own merged 2-col run), raw lane PASS unchanged; the parity
  advisory's "9 regressions" read identically at HEAD code in the same
  restarted container (environment drift, not a code effect). 11 new
  tests.
- **the support matrix is now by producing engine.** One diagram
  (`docs/diagrams/support-by-engine.svg`, replacing the two per-renderer
  matrices) answers the question a user actually asks — *my PDF came from
  LaTeX / Word / the browser: how will it convert?* Rows are producer
  engines, columns the two output profiles, and the Google Docs column
  carries only live-verified claims (marked `live`) with `†` on engines not
  yet live-tested. The engine rows stand on a fresh canonical sweep of all
  18 real-producer expansion fixtures at e72a900
  (`docs/evidence/engine-sweep-2026-09-11.json`): Word→PDF dialects
  1.03–1.22×, the Distiller dialect and the 214-page GNU Bash manual
  page-exact, LaTeX 0.93–1.35×, RFC/cairo 1.05–1.18×, EUR-Lex +2%, Typst
  page-exact, and the IRS XSL-FO booklets 1.42–1.90× (the designed-stress
  class). The sweep reproduces the committed booklet numbers exactly
  (y06 226, y12 84, y13 59) — an independent confirmation of e72a900.
  Re-swept at the close of the same day, after the document flow, the
  symbol-font fix, the varying-furniture consumption and the wrap
  bracket (`engine-sweep-2026-09-11b.json`, at 621aae6): y06 198, y13
  53, y12 83, y02 128, y21 60, everything else unchanged — the matrix
  and README carry these numbers, and the booklet class stands at
  1.41–1.71×.

## 1.0.1 — 2026-08-07

A résumé went through the converter and came out wrong in ways the 16-document
corpus could not see, because it contained no résumé. Adding one
(`x17_resume_twocol`, with `x18_resume_twocol_tnr` as the control that removes
the monospaced run) exposed six defects at once. This release is those fixes and
the fixture that found them.

### Fixed

- **a hyperlink is a property of characters, not of spans.** The writer asked
  whether a span was *mostly* inside an anchor and tagged the whole span on a
  50% majority, so a link covering less than half its span was dropped
  entirely — which is what a contact header does when one word of a longer run
  carries the mailto. Spans now split at anchor boundaries and each character
  carries its own link.
- **a role and a date on one baseline are one row.** Two runs sharing a baseline
  were emitted as two paragraphs, stacking a right-hand date under the role it
  belongs beside. They are now one paragraph with a right-aligned tab stop.
- **the fontTable declares every font emitted, plus an explicit Normal
  typeface.** An undeclared family is not an error in OOXML; it is an
  invitation, and Google Docs accepted it by substituting its theme face —
  Georgia arrived as something else.
- **tracking is not word spacing.** PDFium fabricates space characters inside
  letter-spaced runs, and those were kept as text, so a tracked heading arrived
  with gaps in it. `_drop_tracking_spaces` removes the fabricated ones and
  leaves real spaces alone.
- **a tracking change ends a paragraph.** A letter-spaced line among
  un-letter-spaced ones is a heading; without that boundary it welded to the
  body text beneath it.
- **hashed JSON is byte-pinned to LF in `.gitattributes`.** A checkout that
  normalised line endings produced a different digest from the one recorded,
  and it failed in both directions — a clean tree reading as modified, and a
  modified tree reading as clean.
- **CI discovers tests instead of naming five files.** The suite had grown to
  663 while CI still ran five script-style suites by name.

### Measured

Confirmation sweep over 31 expansion documents: 25 unchanged, the résumé pair
improved, and the four other movers shown to be render noise by an IR-identical
control on `x11` that establishes a 2.3% noise floor. `y13`'s tab-stop rows fire
but are invisible at its scale.

`x17`/`x18`, before → after: `dy_p50` 3.13 → **0.38pt**, `dy_p90` 25.43 →
**8.92pt**, `within2pt` 0.0590 → **0.1022**, `mean_ssim` 0.8422 → **0.8733**.
Reviewed live in Google Docs and approved. Both runs are committed:
[docs/evidence/sweep-1.0.1-expansion-2026-08-06.md](docs/evidence/sweep-1.0.1-expansion-2026-08-06.md)
indexes the two result sets and their logs, and records what they do and do not
authenticate.

`word_recall` reads 0.9443 → 0.8719 across the same change, and that is a
**reference artifact rather than a text regression**: the harness reference was
extracted with the same PDFium fragmentation this release fixes, so it holds no
whole heading tokens to match against. The converted document gained the
headings; the yardstick never had them.

### Known limitations, carried

- **#48 — ink-vs-advance space synthesis.** Space insertion measures ink extent
  rather than advance width, so a narrow glyph pair can lose its space
  (`A smaller` → `Asmaller`).
- **#47 — cross-platform byte deltas.** Same input on the same platform gives
  identical bytes; across platforms, 6 of 16 gated fixtures match exactly.
  Documents carrying a rasterised region differ by hundreds of bytes, because
  image encoders are not required to be reproducible across platforms, and four
  image-free documents differ by 2–11 bytes for a reason not yet chased.
- **font-style substitution.** Google Docs renders substitute faces for styles
  it does not have. Parked by owner decision: the fontTable now declares what
  the document uses, and what Docs does with that declaration is Docs'.

## 1.0.0 — 2026-08-06

**High-fidelity PDF → DOCX, tuned for documents that have to survive Google
Docs' importer. Apache-2.0. PDFium (pypdfium2) is the core parser; nothing in a
default install carries a copyleft term.**

The version is 1.0.0 because the release bar is met *and live-validated*: the
converter qualifies against the ratified quality policy in Google Docs itself,
not against a local renderer standing in for it.

### The release gate

Live pass 7, consented, against Google Docs —
[qualification](docs/evidence/gdocs-2026-08-06-pass7-qualification.json) ·
[assessment](docs/evidence/gdocs-2026-08-06-pass7-assessment.json):

- `overall_pass: true`, **zero blocking findings** across the 13 blocking
  documents of the ratified policy
- 16/16 documents uploaded, converted, exported and deleted; zero orphaned
  Drive objects
- the uploaded DOCX were verified byte-identical to what a PyMuPDF-free install
  produces, so the run qualified the product a user gets

Regression gate at the bound baseline, both lanes PASS
([re-record](docs/evidence/cover-band-seed-rerecord-2026-08-06.json)):

| lane | page match | mean within-2pt | mean live text | median dy50 |
|---|---:|---:|---:|---:|
| product | 16/16 | 0.5274 | 0.9588 | 1.045pt |
| raw | 15/16 | 0.3615 | 0.9588 | 1.6pt |

### Licence

Relicensed from AGPL-3.0-or-later to **Apache-2.0**. The migration was gated on
four proofs, all recorded: parser parity ratified, two clean consented Google
Docs passes, the [base-wheel proof](docs/evidence/base-wheel-proof-2026-08-06.json),
and the [licence audit](docs/license-audit.md).

PyMuPDF moved out of the core dependency set into an optional `mupdf` extra.
**Installing that extra does not change output** — both installs produce
identical DOCX content on all 16 gated fixtures, proven by content hash. It
exists only for the legacy parser path and for the parity reference arm, and it
is AGPL-3.0-or-later: adding it changes your obligations for anything you
distribute.

### What changed to get here

- **PDFium replaces PyMuPDF as the shipping parser.** The line and block
  clustering PDFium does not provide is written here (`exactdoc/parse_pdfium.py`).
  Four parity findings at the shipping profile were measured and ratified before
  the swap, not after.
- **Permissive text metrics.** The quality ladder shapes text from the published
  Adobe AFM widths (`exactdoc/_base14_widths.py`, generated by
  `testkit/gen_base14_widths.py`), so it works with no optional extra. It is
  deliberately *not* bug-compatible with MuPDF, whose base-14 lookup is Latin-1
  only and charges the space width for em dashes, curly quotes and 25 other
  WinAnsi codepoints.
- **Cover bands inset from the paper edge are recognised.** A band starting
  7.16pt down was treated as ordinary body content, losing both the full-bleed
  side treatment and the Docs vertical compensation; in Google's own export it
  landed 54.5pt right of source and overflowed the page. See
  [the attribution](docs/evidence/c1-live-attribution-2026-08-06.json).
- **Refusals are typed and have stable exit codes**: interactive forms (19),
  page cap (20), OCR-required (17), and the rest of `exactdoc/errors.py`.
- `--verify` compares one page pair at a time; peak RSS on a 259-page comparison
  fell from 5,340 MB to 237 MB.

### Known limitations

Stated in the README's "Limitations" section, generated from the ratified policy
rather than from recollection. The short version: dense multi-column booklets
inflate their page count, interactive forms and image-only scans are refused
rather than mangled, and roughly 14.6pt of white above a page-one cover band is
Google's own and cannot be removed.

## 0.1.0a1

Pre-release development. See the git history and `docs/evidence/` — the
measurement trail starts well before this changelog does.
