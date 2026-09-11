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
