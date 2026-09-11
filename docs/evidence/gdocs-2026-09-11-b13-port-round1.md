# Live Google Docs round, 2026-09-11 — B13 after the first six ported fixes

One consented `explore` upload round (two documents, both Drive objects
deleted, no orphan ledger), run the day the first six catalogue fixes were
ported into the converter. The reference points are the 2026-09-05 hand
campaign on the same source PDF:

| | export pages | verdict |
|---|---:|---|
| converter at `66f5595`, raw output (hand campaign round 1) | 58 | DIVERGENT |
| **converter with the six ports, raw output (this round)** | **39** | DIVERGENT |
| hand-surgery reference `docx_r7` (sha `87eb4771…c75f32`) | 32 | CLEAN 1:1 |

Alignment artefacts: `gdocs-2026-09-11-b13-align.json` (spilled source pages
3, 8, 11, 13, 14, 16, 17 — exactly the table pages the hand campaign's rounds
3–5 fixed by surgery) and `gdocs-2026-09-11-y20-align.json` (Typst specimen:
5→5 pages, page-exact, content divergence only).

What this round authenticates, because only Google's own render can: the
right column now sits at the designer's edge (the converter writes the same
1114tw the hand campaign patched in), Consolas is rendered as Consolas, the
41 line-end hyphens survive as text, quote bars draw as table left borders
rather than 300pt rasterised lines, and the headings appear in Docs' outline
sidebar as Heading 1/Heading 2 — the one property the hand-patched file never
had. What it does not authenticate: the remaining seven spills, which belong
to catalogue #6 (cell partition), #7 (row heights) and #1 (carriers) and are
not yet ported. Numbers above are an explore round, not a qualification run
under the ratified policy, and say nothing about the frozen 16.

---

## Round history, 2026-09-11 (continued the same day)

| round | converter change | export pages | spills |
|---|---|---:|---|
| 1 | the six ports (margins, Consolas, hyphens, mono, bars-as-tables, heading styles) | 39 | 3, 8, 11, 13, 14, 16, 17 |
| 2 | **#6 partition**: `_fragments_by_column` — spans assigned to cells by their own centres against the drawn column bands, so parser-joined cells split | 38 | 3, 8, 11, 14, 16, 17 |
| 3 | #7 first attempt: cell paragraph marks sized to content | 38 | unchanged (the mark is inert in Docs — the hand campaign measured the same) |
| 4 | gdocs row pins (`trHeight atLeast` = source height) + content shrink | 38 | unchanged |
| 5 | **quote bars as pBdr paragraphs** (gdocs): the quote TABLE's cell paragraphs rendered +1-2pt/line in Docs and every quote block outgrew its page — measured on the p3 render, ~40 lines to a block. Bars now `sz=12 space=8 #BBBBBB`, the exact form the hand campaign verified | **36** | 8, 11, 14, 16 |
| 6 | r4 levers [B] (tcMar right −1pt: Docs charges the border against the text area) and [C] (bottom-pad cut to `floor(srcH) − 0.75`: Docs rounds every row up to a whole point) | 36 | unchanged |
| 7 | **drawn-edge width guard**: `_fit_col_widths` no longer trusts a "single line" wider than its column on tables whose edges were read from grid lines — a 40pt parser-joined header span over a 28.5pt drawn column had been redistributing width from every neighbour (family table now keeps the author's pitch to 0.1pt) | 36 | unchanged |

Round 7's export (docs/evidence/gdocs-2026-09-11-b13-align-r7.json) still
spills pages 8, 11, 14, 16. The DOCX side is now measured correct — cells
partitioned, gridCols equal to the drawn pitch to 0.1pt, clean rows landing
+0.5pt (source 37.5pt → export 38.0pt rows in tblgeom's reading) — and the
residual growth concentrates in rows whose cells carry 3+ wrapped lines and
in Docs' handling of the extreme 14pt "#" column, where Google's own export
shows the boundary line missing and the cells apparently merged. The next
levers, in the hand campaign's order: the body-paragraph pitch biases
(r4fix [E]: `BIAS_INTRA=0.17`, `BIAS_GAP=0.38` against the source's own
pitch) and the narrow-column minimum.

---

## Rounds 8-12: CLEAN 1:1

| round | change | export pages | verdict |
|---|---|---:|---|
| 8 | gdocs minimum column width 22pt (the importer drops a sub-minimum column's boundary; measured: the 13.6pt "#" column arrived merged into its neighbour). Funded from the widest column | 36 | the boundary survived, but the funding re-flowed the widest column 3→4 lines |
| 9 | funding spread proportionally above the minimum (no column loses >3.1pt, under a word+space) | 36 | columns right; cmptables showed table 2/3 at +3pt, but table 1's cells still MERGED in the DOCX |
| 10 | **single-span cell joins split by advance arithmetic** (`_split_span_at_boundaries`): a span crossing a drawn boundary is cut at the nearest space within 3 chars of the computed boundary — mono exactly (known advance), proportional evenly. "base L0" and "runs verdict bearing" now partition cell-for-cell | 34 | one spill (p16) + one blank (p15, the carrier double-fire) |
| 11 | **single-line pitch bias [E]**: one-line paragraphs' leading is the size*1.16 heuristic, and Docs pitches them ~0.38pt/line looser (the 47-line list block was +18pt on one page); shave 0.38, floor at the dominant size | 33 | zero spills; only the blank page 15 |
| 12 | **pageBreakBefore instead of a carrier paragraph** (gdocs): the carrier spills and double-fires exactly when its page fills exactly; a break-before is a no-op at a page top. The hand campaign called this "unproven in Docs" — it is now proven: no double-fire, no blank | **32** | **CLEAN 1:1** — `gdocs-2026-09-11-b13-align-final.json` |

What the converter now produces straight from the PDF equals what the
seven-round hand surgery produced, and adds what the surgery never had:
named heading styles with a populated Google Docs outline. Gate after the
full sequence: PASS both lanes at the recorded baseline numbers (the
fragment/split changes are all-profile; the row model, min-column, bias and
break-before are gdocs-only). Suite 697 OK locally, container green.

---

## Vision acceptance pass on the CLEAN 1:1 result

A vision-model pass over six zoomed side-by-side page pairs of the final
export (title, two table pages, the callout/quotes page, a quotes page, the
last page). Verdicts: **p01, p11, p20, p32 PASS**; **p15 CONCERNS** — the
page-15 callout box border is still dropped (text intact, position exact;
the hand campaign's round-6 item, not yet ported); **p08 CONCERNS** — the
family table's narrowest cells wrap mid-word in Docs ("INCONCLU / SIVE ×5",
"28/ 60") with rows slightly taller; everything else checked matches:
headings, running heads, footers (identical text), quote bars (same x and
extent), header shading, page breaks, first and last lines on every page.
Document-wide, Docs fits roughly one extra word per line — cosmetic reflow
with line counts and break points preserved. Two model misreads from the
low-resolution passes ("header word difference", "header shading lost")
did not survive the zoomed verification and are withdrawn.

---

## Rounds 13-16: the callout box lands; the grid-autofit fight mapped

**13-14 -- the callout box (hand campaign round 6, ported).** A lone
substantial STROKE rect (481x412pt, 0.75pt #333333, no fill) never reached
`build_box`: singleton drawing clusters skip classification, and the
leftover loop's box branch tested `d.fill` only, so the rect dropped
silently -- text intact, box gone. Recognised in the leftover loop and
given `role="box"`; under the gdocs profile the box is body paragraphs
carrying a four-side `pBdr` (the cell line-inflation that took quotes out
of tables applies to boxes too). Round 13's border did not render, and the
cause is worth the record: **`w:pBdr` children emitted out of schema order
(left before top) are dropped whole by Google Docs.** Round 14, schema
order, renders: rails measured at x=57.2/540.2 against the source's
57.0/538.5. CLEAN 1:1 throughout.

**15-16 -- the p8 narrow-cell wrap, mapped and parked.** The remaining
visible defect is Docs re-laying a table's WHOLE grid when any column's
content overflows its declared width: the verdict column's line sits at
79.4 of 79.5pt, the min-column funding shaved 2.3pt, and Docs' content
autofit rebalanced every column (79.5 -> 48pt remnant) and broke words
mid-word. Widening the text area (+0.75pt right-pad trim) changed nothing;
a need-aware funding (take only from single-line-slack columns) was worse
-- source-wrapped cells report no single-line width, read as pure slack,
and the verdict column was drained for the '#' column's benefit. REVERTED
to the proportional form. The honest next lever is the hand campaign's
`cw2` bracket: per-column empirical wrap boundaries measured from a live
export, not predicted. The aligner stays CLEAN 1:1 across all of it; the
defect is one cell's line break, not a page.

---

## Rounds 15-17: the last visual residual fixed -- the drawn-lines floor

Round 15-16 mapped the p8 defect to its root and two remedies failed
honestly (recorded in situ). Round 17 landed the principle both were
missing: **a column's floor is the widest line its own cells actually
drew** (`src_widths`, wrapping included) -- not a prediction. The floor
bounds what funding may take, and on drawn-edge tables both the floor and
the widening's ask cap at the column itself, because the author's grid by
construction held everything drawn in it: a straddling fragment (54pt of
ink in a 30pt column, a split that refused at a spaceless boundary) is
cross-column ink, not a need, and pads measured within the column must
not double-count.

Measured result, Google's own export: the family table's gridCols now
equal the source pitch to 0.1pt on every column, and "INCONCLUSIVE ×5" --
which the importer was breaking mid-word in a re-laid 48pt remnant --
renders on ONE line. CLEAN 1:1 held. Gate after the all-profiles change:
PASS both lanes at the recorded baseline.

Also in this arc: Ubuntu maps to itself (Docs ships it; a font mapping to
its own name needs no metric claim). Vollkorn stays deliberately
unmeasured -- two document-derived "measurements" disagreed by 12-35%
depending on sampling (justified spans carry the justification stretch;
the unstretched remainder is letterspaced display text), and neither was
trustworthy. The honest route is a probe_font_metrics ride-along, noted
in the code where the next reader will look.

---

## The inflation class, mapped (lshort, canonical container, product lane)

The first precise map of the new producers' page inflation (lshort:
153 -> 173, +20): **8 blank export pages** (13, 58, 110, 114, 123, and the
run 160-162) against only **3 spilled source pages** (9, 81, 118) and 3
orphan tails. The inflation is not uniform drift -- it is mostly the
carrier double-fire (defect catalogue #1) on the STANDARD profile, whose
page seams still use carrier paragraphs (the gdocs profile's
pageBreakBefore port proved the no-op-at-page-top model live, in Docs;
LibreOffice needs its own gate cycle before the same port lands there),
plus one clustered blank run (160-162) worth its own look -- three
consecutive blanks usually mean an element cycling just over a page
boundary, not three coincidences.

## The carrier paragraph retired from every profile

The lshort map's lever, taken: `pageBreakBefore` is now the page seam in
the STANDARD profile too (carriers remain only before non-paragraph
followers, which cannot carry the property). The gated corpus adjudicated:
**gate PASS both lanes with BETTER numbers** -- product within-2pt
0.5274 -> 0.5361, raw 0.3615 -> 0.3703, dy50 unchanged -- because the 1pt
carrier paragraph no longer sits at every page seam. lshort in the
canonical container: 173 -> 170 pages, dy_p50 41.0 -> 20.8, place 0.258 ->
0.471, mean_ssim 0.659 -> 0.678. Suite 701 OK. The remaining lshort
blanks (the 160-162 run among them) are not carriers and keep their place
on the runway.

## Final vision acceptance, with each claim verified

A pixel-geometry + zoomed-vision pass over the round-17 export confirmed
the two fixes: **p15 PASS** (the callout box renders as a complete
four-sided rectangle, every edge pixel-verified at 2px stroke) and **p01
PASS** (title, metadata, 41 matching lines, footer). p08's column
boundaries measure within 0.2% of source across all eight columns and the
verdict column is clean ("INCONCLUSIVE ×5" on one line).

The pass also made three p08 claims that direct verification then
DISPROVED, and the disproofs matter as much as the passes: "Control case
Fable 3 vs Fable 5" (the phrase exists in neither source nor export -- a
small-zoom transcription artifact), and "two values stacked in the 5th
cell of rows 2/4 with the 4th empty" (the DOCX rows partition exactly:
system_promp | 9/40 | 20/40 (+27.5%...) | 20/40 | 20/40 | 20/40 | 19/40 |
HOLDS x5 -- the "stack" is a vision read of a legitimately wrapped cell).
The one remaining plausible claim, mid-token breaks in the narrowest
numeric columns at ~0.5pt of fit margin, stays on the runway where the
wrap bracket lives. Lesson recorded: pixel geometry from these passes is
trustworthy; digit transcriptions at zoom are not, and every textual
claim needs a text-level check before it becomes a defect.

## The self-referential median (lshort's index tail, and WorldBank's too)

The lshort blank run 160-162 was one paragraph: the index's last three
entries, from three different columns, 352pt apart -- and the paragraph
splitter's threshold is "gap > 1.55x the median gap", where the median of
three huge gaps IS a huge gap. The split could never fire; the paragraph's
352pt exact leading rendered one line per page. The threshold's idea of a
pitch now caps at 2.2x the dominant font size (double spacing is 2.0), so
a group whose every gap is enormous splits like any other.

Canonical container, after: **lshort 170 -> 168** (mean_ssim 0.678 ->
0.686) and **WorldBank 48/69 -> 48/66** (mean_ssim 0.408 -> 0.435) -- the
same artifact class was eating three pages there. Gate PASS both lanes,
numbers unchanged; suite 701 OK. EUR-Lex unmoved at 147 (its +3 is a
different, smaller class).

## Vollkorn: the live probe, done as an experiment instead of a probe

The parked Vollkorn question answered itself the cheap way: map it to
itself (it is a Google Font; Docs plausibly ships it), upload, and let the
word wraps arbitrate. They did -- the export's line breaks came back at
the SOURCE's own -- and the family's line box then measured straight from
that export: emitted 1.2458x at 11pt predicted 15.68pt, Docs rendered
19.10pt (median of 30 consecutive body-line gaps), a natural factor of
**1.392** against the 1.144 default that had made the document's lines
22% tall and its pages 5 -> 7. With the factor in: **5 pages, body pitch
15.70pt = the source's 15.70pt exactly**, page-3 verbatim line matches
2/37 -> 14/37 (the rest is a tab-row extraction artifact and justified
space counts). Same provenance class as Libre Baskerville's entry: the
number is Docs' own rendering, measured, not assumed.

## The remaining inflation, mapped to its classes

**WorldBank (48 -> 66)**: the spills concentrate in one contiguous run --
source pages 32-42, the overview booklet's infographic section (InDesign
full-bleed designed layouts with charts as background art). That is the
policy's `designed_stress` class living inside a document tiered
`ordinary_digital`; the tier call was wrong about that section, not the
converter. The honest fixes there are the known-hard ones (rasterised
regions, full-bleed design), not pagination rules.

**EUR-Lex (144 -> 147)**: +2% on a 144-page document -- the minor-drift
class, lowest value of the runway. lshort (153 -> 168) and SCOTUS (exact)
bound the LaTeX and Word-dialect ends of the same measurement.

## The 3-column booklet diagnosis, to the exact seam

y06 (126 -> 294 canonical): the failure is NOT detection and NOT the
columns' rendering. The chain, measured at each link:

1. the varying "Page N of 126 Fileid" footer IS consumed (digit-
   normalised signatures already handled it);
2. margins are right (42/42 -- most pages' body genuinely starts at 42);
3. the 3-column pages ARE detected: the DOCX carries 28 three-column
   sections and 24 two-column ones (143 sections total);
4. the sections DO render as columns -- the export page carrying source
   p39's text shows 37 column-width text rects against 1 full-width;
5. and still 126 -> 294 (298 in a fresh local open-loop render).

The inflation is in the PAGINATION of the column sections themselves:
per-page element accounting says the document emits 158.5k pt of content
against a 150.4k pt true capacity (730pt x n_cols per page) -- a 5%
overage that should cost ~8 pages, not +168. The suspects, in order:
LibreOffice's default BALANCING of continuous multi-column sections;
pageBreakBefore inside a column section breaking to the next COLUMN
rather than the page; and the per-page lead/grid/tail section ladder
(1-col -> 3-col -> 1-col via continuous breaks) interacting with both.
The next session's lever is a probe document -- known content in one
3-col section, rendered, with one variable changed at a time -- the
method the cover-band and font probes already established. The parser,
the inference and the writer's declarations are all measured correct;
what is unmodelled is the renderer's column-section pagination.

## The 3-column fragmentation map (surgical experiments on the real artifact)

Following the seam diagnosis, four one-variable experiments on the
converter's actual y06 output, each rendered and counted:

| lever | pages (baseline 298) |
|---|---:|
| strip all 66 explicit column breaks | 291 |
| strip all 1,148 indents inside 3-col sections | 299 (no effect) |
| strip the 46 pageBreakBefore page seams | 278 |
| all of the above | 278 |

Wrapping, pitch and volume are all CORRECT (export/source chars 1.03,
line pitch equal to the source, per-page rows equal) -- and the page
histogram says where the 2.3x really lives: **123 of 298 export pages are
sparse (<40 rows), 58 of them nearly empty**. Content totalling 17.6k
rows against the source's 13.5k (1.3x from narrower equal-width columns)
is scattered across half-filled pages by the per-source-page
lead(1-col)/grid(3-col)/tail(1-col) section ladder: every source page
costs 2-3 section boxes, and LibreOffice does not refill the leftover
space.

The structural fix is now scoped, not guessed: **merge the grids of
consecutive 3-column source pages into ONE continuous multi-column
section** (lead/tail content joining the flow), letting content fill
pages naturally. Predicted landing from the row ratio: ~160 pages (1.3x)
for y06 -- and the 1.3x residue is then the equal-width column narrowness
(165.5pt emitted vs ~172pt drawn), which the writer can close by emitting
the measured band widths. Both are inference/writer changes of ordinary
size; the experiments that ruled out every cheaper lever are the value
recorded here.

## The grid merge, built and measured: a wash, reverted

The scoped fix was implemented exactly as prescribed -- consecutive pages
each carrying one multi-column grid of the same width merged into one
synthetic page, tails and leads joining the grid flow in reading order --
and measured in the canonical container:

| document | before | merged |
|---|---:|---:|
| y06 (126pp source) | 294 | 270 |
| y13 (31pp source) | 66 | **70 (worse)** |

Gate PASS unchanged (the gated corpus forms no runs); suite 703 OK. But
the prediction failed: y06 was expected near 160 and landed at 270,
because the booklet's page structures ALTERNATE -- `(2,1) → (2,1) → (1,)
→ (1,)` -- so two thirds of grid pages never form runs longer than two
(chunk-pattern census: of pages 1-40, 14 are pure 1-col, 13 are
`(2,1)`, only 9 have any lead). And y13 regressed by 4 pages, with a
plausible mechanism: `_column_one_overflows` decides per CHUNK whether to
drop column breaks, and a merged chunk is the size of the whole run -- one
overflow prediction then linearises ten pages of column content.

Reverted. What the negative result adds to the map: the fragmentation is
not the SEAMS between same-shaped pages -- it is the section-per-page
model itself on a document whose shape changes page to page. The fix that
the evidence now points to is a document-flow emission for booklet-class
documents (one body flow, column sections changed only where the source's
grid genuinely changes, breaks re-derived per page of flow), which is a
redesign of the writer's page model rather than a patch on the ladder.

## The booklet class, actually fixed: three coordinated changes

The document-flow redesign the fragmentation map pointed at turned out to
need one prerequisite nobody had measured: most of y06's three-column
grids were never DETECTED. The chain:

1. **The gutter scan now reads only narrow lines** (<= 0.62 of the content
   width -- the same bar every other column test uses). A spanning line
   cannot be column content by construction, yet the old all-lines
   occupancy counted it against every gutter it crossed; the IRS pages
   carry spanning cautions at 4-7% of lines, above the 3% tolerance, and
   EVERY such page fell through to the two-column path. The tolerance
   could not simply rise (y03's byte table reads as a grid from 4% up), so
   the separator is a **band-width floor**: a document's text column is
   never narrower than 80pt (a 3-col letter page runs ~165pt; the byte
   table's bands are 49-70pt, measured, held out). Result: y06 detects
   61 grid pages where it detected 9; y13's grids arrive; y03 is
   byte-identical in structure.

2. **"Wide tail" means crossing the column split, not a fixed fraction of
   the page.** The 0.62 bar classified every full line of the dialect's
   column two (65% of content width) as page-spanning and pulled whole
   columns out of the flow with page-absolute indents -- 182pt indents
   inside 165pt sections, every word wrapping.

3. **Grid runs merge, and merged flows drop per-page column breaks.**
   The previously-reverted wash had a prerequisite: runs need detected
   grids. With (1), y06's 42+17 same-shape pages form real runs; the
   merge concatenates them into one continuous section (tails and leads
   joining the flow), and the per-source-page ColBreaks -- which fire at
   flow positions inside a merged run and compound drift, the measured
   y13 regression of the first attempt -- are dropped for natural fill.

Canonical container, product lane (refine3), against the committed
baseline:

| document | before | after | |
|---|---:|---:|---|
| y06 (126pp) | 294 | **226** | 2.33x -> 1.79x |
| y13 (31pp) | 66 | **59** | 2.13x -> 1.90x |
| y12 (59pp) | 85 | **84** | 1.44x -> 1.42x |

The local refine0 renders had shown y12/y13 moving the wrong way; the
refinement loop -- three rounds against the actual renderer -- corrects
the merged flows and lands all three better. Gate: PASS both lanes,
numbers unchanged. Suite 705 OK. The residual ~1.8x on y06 is the
equal-width column narrowness plus the un-merged minority of pages --
the measured band widths and the remaining ladder pages are the next
levers, now standing on a detection layer that actually fires.

---

## The residual, decomposed -- and the "measured band widths" lever disproved

The lever named above ("emit the measured ~172pt band widths instead of
165.5pt equal-width") did not survive its own measurement. Probing the
detector on y06 directly: the snapped bands measure **165.5-166.0pt** on
the 50-page dominant shape (y13: 167.5-169), and today's equal-width
emission writes **165.50** -- a delta of 0.0-0.5pt. The "172pt drawn"
number in the fragmentation map was a prediction, not a measurement; the
snap (`max(ink, a+col_w)`) had already absorbed the drawn widths. There
was no narrowness to recover.

What the decomposition found instead, on the 226-page y06 export:

- the export carries the SAME TEXT IN FEWER LINES: 36,090 lines against
  the source's 40,752 (de-hyphenation packs ~11% tighter);
- the line pitch is exact: 11.5pt = 11.5pt in every measured column;
- the source's own intra-page whitespace is 10,814pt (16 pages' worth)
  and its page-top offsets >48pt total just 724pt;
- the render carries 28-29k pt of internal gaps -- **~18,300pt of dead
  space the source does not have**.

So the +100 pages were pure fragmentation, and they lived on the NON-grid
pages: y06's 63 grid pages had merged into runs, but its ~12 two-col
worksheet pages and ~23 sparse one-col pages still carried one section +
page seam per source page. The rejection census: of 126 pages, 63 detect
grids, ~12 find ONE gutter (2-col pages), 23 fail the narrow-line scan
(few narrow lines -- full-width worksheet pages), 12 hit the band floor
(table pages, correctly held out).

## The booklet document-flow merge, and the page-relative gap cap

`_merge_grid_page_runs` now merges runs of consecutive same-shape pages
inside BOOKLET-CLASS documents -- detected as >= 10 pages carrying a
>=3-col grid and >= 35% of the document (y06: 63/126; y13: 20/31; y12's
1/59 excludes it; the gated 16 carry no >=3-col page at all, so the
extension cannot fire there). All-1-col runs flow into one synthetic
page; 2-col runs merge exactly as grid runs do. Full-width content stays
in 1-col sections -- the merge only drops page seams, it never feeds
full-width text into columns.

The first measurement was a near-wash (226 -> 209) and the reason became
its own finding: the merged render's fabricated dead space decomposed
into PAGE-RELATIVE offsets -- the distance from a page's last content to
its bottom-pinned tail ("Need more information..."), and page-top offsets
on joined leads. In the source those distances were absorbed by the page
break; in a flow they render as gaps. Everything a JOINED page
contributes to a run is now capped at 48pt per element gap
(`_JOIN_GAP_CAP_PT`) -- above any real paragraph or heading gap in the
corpus, below every page-relative offset measured (100-692pt). The run's
own first page keeps its geometry.

| document | before | after | |
|---|---:|---:|---|
| y06 (126pp) | 226 | **203** | 1.79x -> 1.61x |
| y12 (59pp) | 84 | **83** | 1.42x -> 1.41x (the cap alone; not booklet-class) |
| y13 (31pp) | 59 | **58** | 1.90x -> 1.87x |

y06's ladder collapses 126 pages -> 36 synthetic pages (its 15- and
14-page worksheet runs flow as one page each). The remaining fat is
structural: ~36 runs each end in a section break whose leftover the
renderer cannot refill -- roughly half a page per run boundary. Going
below ~190 needs the writer-level document flow (one body flow, column
sections changed by CONTINUOUS breaks), not more merging.

Gate, with a control: the parity advisory read "9 regressions" in the
post-restart container -- the A/B control at HEAD code reads the SAME 9
(environment fingerprint drift after the host power cut, not a code
effect; both runs' lanes PASS). With the change: **product lane PASS
16/16, within-2pt 0.5361 -> 0.5445 BETTER** (the gap cap tightens a
gated document's own merged 2-col run), raw lane PASS unchanged
(0.3703 / 15/16). Suite 716 OK (11 new tests: booklet detection
thresholds, 1-col/2-col run merging, non-booklet safety, seam order,
and the cap's first-page-keeps-geometry contract).

## The writer's document flow: one flow, CONTINUOUS shape changes

The merge left ~36 run boundaries, each a NEW_PAGE section whose leftover
the renderer cannot refill -- measured as roughly half a page per boundary,
the predicted floor of ~190 on y06. The writer now treats a booklet as
ONE flow: same-shape synthetic pages continue with no break at all, and a
column-shape change is a CONTINUOUS section break (columns begin below
the preceding content, the way a Word author builds mixed-column text)
emitted by the chunk loop that already existed for in-page transitions.
The first chunk's page-top `pre_gap` is capped under `_JOIN_GAP_CAP_PT`,
the same page-relative rule as every joined-page gap. Non-booklet
documents -- every gated document -- keep their page seams unchanged:
those seams ARE the page-exact reconstruction the gate certifies.

Two defects surfaced by rendering the flow, both fixed:

- **tables inside a column flow were sized against the page width.** A
  table in a multi-column chunk now sizes against its COLUMN (booklet
  scope). A table cannot wrap, so the min-column widening against the
  528pt page was building 300pt tables inside 165pt columns.
- **pages carrying a rigid element wider than a booklet column are
  structure, not repetition.** y06's source p99 is a hybrid -- a 405pt
  "Student Loan Interest Deduction Worksheet" spanning the page over
  genuine 3-col instructions -- and run membership pulled that table into
  the column flow, colliding with the neighbouring columns' text on six
  rendered pages (the "tail renders in column width" trade assumed tails
  wrap; a table does not). Such pages are excluded from run membership
  and keep their own ladder. Spanning TEXT keeps the trade: paragraphs
  wrap.

| document | 9ee75f8 | now | |
|---|---:|---:|---|
| y06 (126pp) | 226 | **198** | 2.33x -> 1.57x from the campaign's start |
| y13 (31pp) | 59 | **53** | 2.13x -> 1.71x |
| y12 (59pp) | 84 | **83** | (not booklet-class; the cap alone) |

Gate: product PASS 16/16 at the recorded baseline (0.5361 / 0.9588 /
1.045pt), raw PASS (0.3703 / 15/16); the parity advisory reads the same
nine regressions it reads at HEAD code in this restarted container
(environment drift, A/B-controlled earlier). Suite 719 OK. Residual,
named: five pages carry 4-12pt intersections at section-transition bands
(smaller than, and pre-existing, the equivalent at 9ee75f8), and one page
renders two paragraphs zipped glyph-on-glyph -- both await the
element-level section interruption of the true document flow, where a
wide element gets its own CONTINUOUS 1-col section mid-flow instead of a
page of its own.

## Symbol fonts: the TeX PUA class, closed with a verified table

The last named runway item for lshort was "dingbat pages -> PUA garbage
glyphs". The census first: across the WHOLE corpus the class is two
documents and 83 characters -- y22_lshort (46 chars, 5 pages: 71, 72, 82,
83, 111) and y25_texbytopic (33; refused over-cap anyway) -- all from
Computer Modern fonts. No dingbats anywhere: the garbage is CMEX10
delimiter PIECES and CMMI10 oldstyle digits, for which the PDFs carry no
/ToUnicode, and both parsers synthesise Adobe's PUA assignments.

The table was not copied from memory: every PUA value was joined to its
glyph NAME through the embedded CFF charsets of the corpus's own files
(PyMuPDF texttrace GIDs against each font's charset). Verified, the class
is exactly: paren/bracket/brace tp-ex-bt pieces, the brace/arrow
extenders, dotless j, and oldstyle digits 1-9. Each piece now translates
to its base character ("(", "[", "{", "|", "1".."9", U+0237) -- scoped to
CM-family fonts by name, so a PUA value in any other face keeps its
producer's meaning. `_tex_pua_to_text` runs first in `normalize`, counts
into `_dialect` stats, and lshort's DOCX now carries zero Private Use
characters (was 46; the formulas read "(((" where a tall parenthesis was
drawn in pieces -- each piece sits on its own line in the real document).
Gate PASS both lanes at the recorded baseline; suite 724 OK.

## Varying running headers: scoped, design written, next lever

Why they fall through, precisely: `detect_hf` consumes a top/bottom-zone
line only when its full signature -- (zone, y/3, text[:40]) -- repeats on
>= 60% of pages. A per-chapter header repeats only across its chapter,
so every variant falls below the bar and lands in the body flow (one
stray line per source page; lshort's would be ~150, the pandoc manual's
section headings at a consistent top y are the same class).

The discriminator that separates them from REAL content is already in
the file: the digit-role machinery. A running header carries a digit
that equals the page number; a chapter title at the same geometry does
not. The next lever: group top-zone lines by GEOMETRY alone (zone, y/3,
font size), and where >= 60% of pages carry exactly one line at that
geometry and enough of them carry the page-number digit role, consume
them as furniture (emission: per-section dominant text, or consume-only
for flow documents). The blast radius is every document's HF detection,
so it needs its own full gate cycle -- handed to the next session's
budget rather than rushed at the end of this one.

## Varying running furniture: consumed by geometry, landed

The scoped design needed one correction from its own measurement: the
page-number digit role cannot be the discriminator, because the pandoc
manual's varying header -- the CHAPTER NAME ("Pandoc's Markdown" x25,
"Options" x11, "Templates" x10) -- carries no digits at all. What holds
for both real cases, and cannot hold for real content (which starts
below the furniture zone), is the GEOMETRY: exactly one line at the same
position and size on >= 60% of non-first pages. The fixed-text pass runs
first and keeps every document it already owned (its digit-normalised
signatures handle "Page 3"/"Page 4" style furniture); the geometry pass
consumes only single-line-per-page leftovers.

Consumed WITHOUT emission: the representative-page machinery cannot
state varying text, and a source page number is wrong in the DOCX once
pagination differs -- furniture that cannot be stated correctly is
dropped rather than stated wrongly. Measured: the bash manual's 212
page-number/chapter lines and the pandoc manual's 138 chapter-name lines
all consumed; y26 stays exactly 214 pages and y24 stays 168 (the lines
were riding inside existing page slack -- the gain is a clean flow, not
pages). Gate PASS both lanes at the recorded baseline; suite 728 OK.

## The wrap bracket's live measurement: B13 re-flown at the current HEAD

One consented exploration round (single document, deleted after, empty
orphan ledger): B13 converted with the day's HEAD (booklet flow, join-
gap caps, varying-furniture consumption, TeX PUA -- none of it B13
specific) at the gdocs profile, uploaded, Google's export returned.

- **32 pages in, 32 pages out -- CLEAN 1:1 holds** across every change
  landed since the campaign closed.
- The p8 verdict column's "INCONCLUSIVE x5" renders on ONE line: the
  drawn-lines floor (round 17) owns that break, confirmed live.
- The named residual is now measured to the cell: "28/60" and "30/40"
  render as "28/" over "60" and "30/" over "40" -- two cells of one
  table, mid-token, exactly the cw2 class.

The bracket measurement, from Google's own export: our DOCX declares
the cell at 30.0pt (pads 0.25pt) and the token's predicted advance is
21.6pt at Consolas 8 -- 7pt of slack, it FITS its declared column. Docs
breaks it anyway because the table's grid is re-laid: the rendered
"28/" fragment runs x416-429, i.e. the column Docs actually gave it is
~17pt wide, not 30. The round-15/16 finding ("Docs re-lays the whole
grid when any column's content overflows its declared width") is the
trigger, and some column's overflow -- not this one -- fires it. The
cw2 lever therefore needs Docs' REBALANCE MODEL (which column overflowed,
where the squeeze lands), not a per-token width bump: a local floor on
the narrow columns cannot see the squeeze coming. The measurement above
is the empirical basis; implementation handed to a fresh session's
budget. Artifacts stay out of the repository (personal document);
the journal records the numbers.

## cw2, closed: the wrap bracket was a double-encoded position

The rebalance theory recorded above was wrong, and the live export's own
XML said so. The broken cells were not squeezed by a re-laid grid -- the
DOCX itself carried `w:ind w:left="254"` (12.7pt) TOGETHER with
`w:jc val="right"` on the same cell paragraph: the source x of an
aligned cell line was being emitted as an indent AND as an alignment.
Google honours both -- the indent consumes the wrap width, leaving
17pt of line under a 22.4pt token -- so Docs broke "28/60" after the
slash. LibreOffice renders the same XML unbroken, which is why the
gated lanes never saw the class.

Two rules, both gdocs-only, close it:

1. a right- or centre-aligned cell paragraph drops the positional
   indent -- jc already places the text;
2. a left-aligned cell paragraph's indent is bracketed by the SOURCE's
   own drawing of the line (`source_line_width` -- the same glyphs Docs
   renders, measured in the PDF, no font model) plus the live-measured
   ~10% advance gap and the 1pt border charge. Position may never push
   the wrap boundary under the text's own width. Monotone-safe: a
   smaller indent can only remove a wrap.

Three live rounds in one arc (all single-document, deleted after, empty
orphan ledger): the first measured the residual and disproved the
rebalance theory; the second proved rule 1 (the right-aligned cells
'28/60', '30/40', '21/60' came back whole); the third, with both rules,
came back with every token whole -- '28/60', '30/40', '35/60', '15/40',
'21/60' -- zero fragment lines, and the document still CLEAN 1:1 at
32/32 pages. Gate PASS both lanes at the recorded baseline (the change
is gdocs-profile only; the standard lanes cannot move). Suite 733 OK.
