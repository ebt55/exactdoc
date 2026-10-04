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

- **fonts: a family table replaces the descriptor-flag heuristic (audit B12–B15,
  B30, defect catalogue #3/#19).** pdfTeX's Type 1 fonts carry no Serif or
  FixedPitch bit, so `NimbusRomNo9L` (Times' metric clone) became Arial,
  `CMTT10`/`NimbusMonL` code became proportional, `CMBX12` headings lost their
  bold, EUR-Lex's `EUAlbertina` became Arial and `HelveticaNeueLTStd-Roman`
  became Times New Roman ("roman" counted as serif evidence). `fonts.py` now
  names the URW 35, CM/CMU/LM/EC, Helvetica Neue, the Office set and CJK faces
  with class, weight/slant codes (Bd, Blk, Demi, Medi, Ital, CMBX, CMSL…) and a
  target per profile; the parser takes class from it before the flags. The
  standard profile writes Calibri/Cambria by name (gdocs keeps Carlito/Georgia
  until a live pass grades them). Calibri is shaped from Carlito's own widths
  (OFL; was Helvetica's, 8.6% wide), CJK runs name their face in `w:eastAsia`,
  and a run whose emitted width cannot match the source — a half-point size
  (c1's 9.33pt written 9.5) or Courier New for a 0.525em typewriter — carries a
  `w:w` scale from the PDF's own glyph advances, which the ladder shapes with.
  Measured in the canonical container against HEAD. Product lane: y03 62→57
  pages, y18 147→145 (word recall 0.435→0.756), y22 167→166 (recall
  0.261→0.423); c1 within-2pt 0.334→0.678 and c4 0.440→0.621 in both gated
  lanes (gate PASS; product mean within-2pt 0.5274→0.5689); x17/x18 up. Raw
  lane: y03 71→65, y25 361→338, y18 279→265; over all 52 swept documents mean
  within-2pt 0.2107→0.2216, mean |page ratio−1| 0.1517→0.1483, mean word
  recall 0.7445→0.7401 (y24, y22). TeX code blocks now keep their
  line breaks (catalogue #2), which costs raw-lane pages where an unrelated
  overflow had been absorbed by code collapsed into prose — y22 222→229, y24
  168→169 (recall 0.645→0.388 in both lanes, a page-alignment shift), the
  attribution checked by disabling only the name-based monospace class; y06
  202→204 because its cover title is now bold, as drawn. Proportional width
  matching was measured and NOT taken: per-run ratios carry clone-rounding
  noise that moved 02, x05, x06 and x15.

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

Corpus tranche 4 (see `docs/corpus-expansion.md` §13): "what people actually
convert" — 38 licence-verified documents sealed as y28–y65 (16 gated + 79
expansion = 95, 21.9 MB added).

- **Producer chains new to the corpus:** Word, PowerPoint and Excel for
  Microsoft 365 direct exports, Google Docs, Apple Pages, real-world
  LibreOffice, Power PDF, Print To PDF, WeasyPrint, JUST PDF, XPP,
  JasperReports, GPO, three journal pipelines and three arXiv classes.
- **Coverage:** CVs, eight non-Latin scripts and two OCR'd scans.
- **First sweep** (product profile at ec22cbf,
  `docs/evidence/quality-sweep-tranche4-2026-10-04.json`): 38/38 convert, but
  only 10/38 are page-exact. Median ratio 1.38×.
- **Two-column papers** inflate 2.4–2.6× (y41, y39, y42).
- **Panel-backed InDesign text is rasterised wholesale:** y58 keeps 12% live
  text.
- **Scans** go 2.8–2.9× in pages and 53–58× in DOCX size.
- **The word-recall metric cannot grade Thai or Devanagari** (y55 keeps every
  Thai character and scores 0.061).

Non-gating; the expansion parity policy re-pins its corpus hash only.

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
- **drawings count as structure only when a reader can see them.** Three
  false-structure defects from weak drawing evidence, fixed in `dialect`
  (visibility) and at two `infer` decision sites:
  Word's per-line `#ffffff` paragraph shading no longer becomes one box
  table per line — a page-coloured, unstroked area fill is dropped unless it
  is visible by contrast with something it touches (a knockout, a zebra row,
  a panel under artwork, part of an image); y01 p21's 7-line paragraph is one
  paragraph again and y01's 111 white boxes are gone. Word's table-border
  joint squares (0.48/1.5pt, flush with the rules they join) are no longer
  promoted to "•": a drawn marker must be ≥ max(2pt, 0.25em) of its line and
  must not touch a rule end — y02 1,286 → 24 bullets (its 24 real ones),
  y11 3,612 → 36, x11's dotted TOC leaders no longer bullet the page numbers;
  Chromium discs (3pt, 0.27–0.29em) are untouched. Paths with zero alpha or
  no paint are dropped before inference reads them. And a vertical rule is a
  quote bar only within 2em of its text, without overhanging it by more than
  1.5em, and not as one side of a drawn frame: y09's page-height margin rule
  had wrapped 56 of 59 pages in a quote table. Raw lane, canonical sweep:
  y09 72 → 67 pages, y01 107 → 103 (word recall 0.184 → 0.199), y02 142 →
  140 (doc recall 0.903 → 0.922), y03 71 → 70, x11 4 → 3; y10 within-2pt
  0.273 → 0.272, everything else identical. Product lane: y09 72 → 65,
  y03 62 → 60, y02 128 → 126, y01 96 → 95. One honest loss: y08's product
  within-2pt 0.336 → 0.321, all of it on p6 (269 words within 2pt → 0).
  The phantom "•" had been that page's first paragraph and so carried its
  `pageBreakBefore`; without it the page opens with the heading box's
  rule after a `w:br` carrier, LibreOffice drops the space before it
  (audit B23) and the page sits 17.5pt high. Disabling only the marker
  rule restores 0.336 exactly. Gated 16: raw DOCX byte-identical to
  before, gate PASS both lanes at the recorded numbers. 30 new tests.
- **résumés: the structure the release bar names.** Five defects on the
  owner's résumé and x17/x18 (defect catalogue #7, #8, #22; design audit
  B16), each a general rule. *Typed list markers* ("• text" in one span,
  "1." "(a)") now open a list item when the flow shows list evidence — a
  second marker at the same x, a hanging indent, or a numbering sequence
  ("5. Section heading" alone stays a heading) — and the item keeps its
  measured hang; x17's fused bullets and RFC 9110's four glued items split.
  *A rule between two lines of one block* cuts the block, so the rule under
  "SUMMARY" is drawn under SUMMARY, not under the summary text. *A lone
  role/date row* takes its tab stop from the document's column of rows
  (same edge, same styles, a label/field style contrast), not the page's.
  *The content edge* may reach the document's rules when two label/field
  rows end there (x17: 486pt column → 509pt). *Body-size section headings*
  — bold caps, one line, at the column edge, tracked or ruled — carry
  Heading styles, so Docs' outline of a résumé exists. x17's 8.92pt dy_p90
  was one paragraph re-wrapping (Chrome's advances run ~4% wide); with the
  column right and a typed item's hang counted as first-line room, the
  ladder locks it. Measured in the canonical container: gate PASS both
  lanes at the recorded numbers, no gated layout changes; x17/x18 product
  dy_p90 8.92 → **2.41/2.42pt**, within2pt 0.102/0.140 → 0.160/0.167;
  expansion+gated product sweep mean within2pt 0.2892 → 0.2935, SSIM
  0.7488 → 0.7503, y17 228 → 224 pages, no product document worse than
  −0.001 within2pt. Worse, honestly: the open-loop raw lane's x17/x18
  within2pt 0.08 → 0.05 (dy_p90 8.92 → 5.9, under that lane's constant
  ~4pt offset), y18 raw 279 → 280 pages, and two lexical hyphens now
  dehyphenated in justified list items (y24, y26) beside nine
  discretionary ones correctly removed.
- **the refine loop: aligned, levered, cheaper, and it cannot lose the
  DOCX.** *Mapping:* source pages map to rendered pages by a monotone
  alignment of lines unique in both documents (LIS), with a diff inside
  each anchored window placing pages that have no unique line; the old
  five-line vote sent RFC 9110's TOC pages 20-170 pages ahead (spill=206 for
  34 surplus pages; round 1 went 228 → 340). *Levers:* each spilled page's
  overflow is read off the render and spent after the unchanged gap step on
  ≤3% line pitch, then ≤50% of table cell top/bottom pads; push-down offsets
  are capped at the room the render shows; the published round's spend is
  reported. *Cost:* the source is read once, figure clips rasterised once,
  one private LibreOffice profile per loop (fresh profiles cost 7-11s a
  render on Windows against 3.5-4s kept; a persistent soffice measured no
  better and is not used), and two quadratic scans in PDFium line grouping
  are gone (page_lines + IR fingerprint-identical on all 94 fixtures;
  page_lines 776 → 455s for the corpus). *Robustness:* a LibreOffice that
  crashes, hangs or writes nothing no longer fails the conversion — the
  best measured round (or the open-loop DOCX) is published and
  `OracleDegradedWarning` raised before publication (escalate it for the old
  all-or-nothing contract; the gate and sweep do); the CLI exits 0 with a
  stderr warning, `convert_result()` returns the `ConversionResult`.
  Absent LibreOffice is still exit 11. The profile lives under a short
  root: ≥ ~160-char profile paths crash soffice on Windows, which failed
  every product conversion under agent TEMP paths. *B23:* inside the loop a
  non-paragraph page opener carries its own `pageBreakBefore`, so
  LibreOffice keeps its page-top gap (probe 84.6 → 184.6pt); open-loop
  writes keep the carrier (kept there, the gap measured as lost slack:
  y17 +3 pages, y27 +2, y03 +3), so the raw lane is byte-identical.
  Measured on the merged tree in the canonical container: gate PASS both
  lanes, product within-2pt 0.5689 → 0.5739 (c6_long 0.90 → 0.98: the old
  mapper had reported a phantom spill on a 7/7 render), raw unchanged
  0.4031; 880 tests. Product sweep (90 documents) against the same tree
  without WP6, run concurrently: conversion time 12,983 → 8,391s (1.55×;
  y06 2,187 → 1,127s, y12 715 → 307s, y01 270 → 137s); 23 documents
  shorter and none longer (y17 223 → 206 pages, y06 199 → 174, y34 86 →
  73, y01 95 → 90, y12 83 → 78, y13 53 → 49, y02 126 → 122), page-exact
  47 = 47; mean within-2pt 0.199 → 0.205, word recall 0.621 → 0.632, char
  recall 0.772 → 0.783, SSIM 0.644 → 0.652; y08 within-2pt 0.321 → 0.349
  (the B23 page WP1 recorded as its loss). Worse, and not yet attributed:
  y22 word recall 0.423 → 0.341 and within-2pt 0.034 → 0.022 although it
  is three pages shorter (the harness matches pages by index, so one spill
  moved earlier shifts every page after it -- the shape y02 had before the
  window fill), y59 recall 0.111 → 0.082, small recall dips on y03, y37,
  y52.

- **the parser reads the page a reader sees (design audit WP4: B6–B11,
  B28; defect catalogue #5, #9).** Every coordinate is in the visible
  frame — CropBox origin removed, /Rotate applied, and a page turned to the
  orientation its text reads when /Rotate would leave every line vertical
  (synthetic probes: CropBox baseline −8 → 42, MediaBox origin 92 → 142,
  /Rotate 90 no longer loses its text). Objects inside Form XObjects are
  placed through the form's matrix (a rect at form (0, 752) is at page
  (150, 352)): y47's charts, y13's TIP/CAUTION icons and y03's figures now
  sit where they are drawn instead of piled in a page corner. Text a reader
  does not see is not text: off-page printer's slugs (y06/y12/y13, 38k
  chars that had become the running header), render-mode-3 text (y19's
  invisible line-start spaces), clipped glyphs, 0.01pt duplicates, white on
  the bare page (y21, GPO's white "VerDate … Frm … Sfmt" slug on y61/y62),
  and an icon's own lettering. Except an OCR layer over a scan, which
  becomes the page's editable text with the duplicated scan left out
  (`--ocr-layer image` keeps the picture). Images with an SMask/stencil are
  embedded as PDFium paints them (y20's logo and y01's TOC numbers were
  black boxes); opaque JPEGs pass through as their own stream; parser drops,
  failed figure renders and bad link annotations are counted, not silent;
  a write opens the PDF once for all figure clips; pages of another size
  get their own section (pgSz, w:orient, pgMar). Gated corpus byte-identical
  (raw DOCX, all 16); canonical gate PASS both lanes (product 16/16, <2pt
  0.5689; raw 15/16, 0.4031).
  Raw sweep over all 95, against the integration head it merged: 35 moved,
  mean abs page-ratio error 0.379 → 0.333, char recall 0.708 → 0.720, live
  text 0.935 → 0.939, SSIM 0.596 → 0.604, page-exact 37 → 38. The OCR'd
  scans y56/y57: 32 → 16 and 44 → 29 pages (10 and 16 in the source), char
  recall 0.01/0.13 → 0.53/0.32, DOCX 31.4/73.1 MB → 1.2/3.8 MB; y42 12 → 7
  pages (live text 0.62 → 0.92); y65 page-exact; y06 204 → 198; y03
  within2pt 0.009 → 0.096. Product lane: y06 198 → 189, y13 and y12 page-
  neutral. Worse, honestly: y13 raw 59 → 61 and its word recall 0.24 → 0.21
  (the correctly placed icons in a three-column booklet flow; the icon-
  lettering rule took it back from 64); y39 27 → 28 and y62 26 → 27 —
  correcting a CropBox origin and dropping an invisible slug both remove
  slack an inflating page had been borrowing; y61/y62 doc recall
  0.963/0.913 → 0.956/0.836 because the harness's reference still counts
  the invisible slug's words; y47 doc recall 0.752 → 0.733 as its chart
  labels move into the now correctly placed chart figures. The visibility
  pass costs 15–20% of character extraction; DOCX size rises where black boxes became
  real RGBA images (y01 0.79 → 0.98 MB) and falls where JPEGs pass through
  (y28 1.96 → 1.53 MB, y50 1.55 → 0.84 MB).
- **ordinary browser- and word-processor-printed documents (WP9).** The
  expansion's Chromium, LibreOffice and ReportLab fixtures kept their page
  counts and still landed 15–74pt off. Each root cause was found with the
  line-drift microscope and fixed as a general rule:
  *Chromium sets text 6.2–6.6% wider than its fonts' advances* (hinted
  integer-ppem glyphs; IQR < 0.6%, against 0.999 for LibreOffice), so every
  4-line paragraph re-wrapped into 3: `tracking.py` measures the scale on
  regular metric-clone faces and restores the bias as character spacing
  (standard profile only — Docs discards run tracking; WP3's w:w keeps the
  half-point quantisation), and the ladder predicts with that part
  (`Run.advance_track`) and never with its own lock compression.
  *A contents page is not two columns*: x11's drawn dot leaders became
  bullets, then a right-hand column, and the page split at a 238pt
  "gutter" (→ 3 pages for 2). Drawn leaders become text dots; dense dot
  leaders become title-TAB-number on a right tab stop with a dot leader
  (`w:leader="dot"`); off-page drawings are dropped; a gutter over 30% of
  the content (every genuine one ≤ 0.234) with the page's prose crossing
  between the columns is not a gutter. *The column is at least as wide as
  the lines that wrapped in it* (98th percentile, verbatim and multi-column
  pages excluded; x05's edge sat 18pt inside a wrapped line); right-aligned
  fields reaching a rule edge on two pages vouch for it. *A rule-less
  table's rows are tabbed paragraphs* (right stops for figures), not one
  welded line or a vertical stack of cells. Markers: outlined `circle`
  bullets (one per line, in a column), a lone mark corroborated only by a
  list column elsewhere, never a tombstone flush with a column end; raised
  footnote numbers join their note, each note its own paragraph. Quote
  tables start at their first line.
  Canonical, on the merged tree: gate PASS both lanes at the recorded
  numbers (product 0.5739, raw 0.4031; gated DOCX unchanged), 989 tests.
  Product lane against the integration head (5ef641a), within-2pt: x02
  0.17 → 1.00, x05 0.37 → 0.99, x07 0.02 → 0.48, x08 0.01 → 0.68, x09 0.21
  → 0.94, x10 0.12 → 0.54, x11 0.04 → 0.76 (dy_p90 30.8 → 1.3pt), x14 0.15
  → 0.54, x17/x18 0.19 → 0.41, x04 0.55 → 0.64; no target page moved.
  Raw sweep, all 90 measured: within-2pt 0.141 → 0.191, word recall 0.562
  → 0.569, char recall 0.720 → 0.729, page-ratio error 0.333 → 0.322,
  page-exact 38 → 39, SSIM 0.604 → 0.615; y09 67 → 63 pages, y33 88 → 82,
  y06 198 → 191, y01 103 → 100, x11 3 → 2. Worse, honestly: live-text
  coverage 0.939 → 0.930, doc recall 0.911 → 0.910 — the metric reads a dot
  leader drawn by a tab as lost text (x02 0.98 → 0.74) and "◦"+tab as a
  token (x09); y35 15 → 16 pages, because its rate tables were fitting only
  as welded prose beside a cell wrapping one syllable per line; y50 dy_p50
  52 → 71 though 26 → 24 pages (15 in the source); y30, y60 recall −0.007,
  −0.011 (TOC and table rows now tabbed); y46, y64 dy_p90 +15, +13 (y64
  within-2pt 0.02 → 0.11). Not fixed here: x07's Chrome `position: fixed`
  running header and footer, painted over the body inside the page, need
  detect_hf (WP2).

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
