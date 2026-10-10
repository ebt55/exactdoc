# The beta bar

**Ratified by the owner on 2026-10-05** ("option A": the independent bar
review's proposal, adopted exactly). **Amended by the owner on 2026-10-06**:
the lanes are graded on the product DOCX, and the harness reads leaders,
symbol fonts and maths the same way on both sides (see
[the amendments](#amendments-2026-10-06-ratified-by-the-owner)). **Amended
again on 2026-10-10**: placement is measured at the text baseline, and live
text is read the way the words are (see
[amendment 3](#amendment-3-2026-10-10-ratified-by-the-owner)); **amendment
4, 2026-10-10** (owner-delegated): a capped dy_p50 rise that comes with more
words within 2pt is not a criterion-8 regression
([amendment 4](#amendment-4-2026-10-10-criterion-8s-dy_p50-owner-delegated-decision));
and a letter-spaced source word reads as the word it spells
([amendment 5](#amendment-5-2026-10-10-ratified-by-the-owner)).

**0.3.0b1 is not tagged while any gating criterion fails.** Criteria 1–6, 8 and
10–12 gate the beta. Criteria 7, 9 and 13 are reported for the beta and gate
the 1.0 release (GA). An unmeasured gating criterion is not a pass either.

`python testkit/beta_readiness.py --runs <folder>` reads the latest
measurements against this bar and prints one line per criterion: PASS,
FAIL by N, REPORTED or UNMEASURED, with the documents that miss. The
thresholds live in `BAR` at the top of that file; changing one changes a
ratified bar, so it needs the owner and an edit to this page in the same
commit.

## Which documents

Most criteria grade the **promised** documents: the kinds the README says
work. An expansion document is promised unless the README disclaims its kind
(academic papers, slides, heavily designed layouts, the scripts it marks
"Partly", scans, refused documents); the rule and the list are in
[corpus-expansion.md §14](corpus-expansion.md) and in each document's
`promised` field in `testkit/corpus_expansion.json`. Of the 16 gated
documents, the 13 the ratified Google Docs policy tiers `ordinary_digital` are
promised. Today that is 62 documents: 41 of 20 pages or fewer, 21 longer.

**Lanes** are where the DOCX is opened: LibreOffice (the product sweep,
rendered in the pinned container), Word (the Word lane, rendered by Word
itself), and Google Docs (live: uploaded, converted by Google and exported).
LibreOffice and Word both open the default (product) DOCX; see the
amendments below.

## The criteria

| # | Criterion | Threshold | Data | Why |
|---:|---|---|---|---|
| 1 | Crash-free | 0 conversion errors on any document in any input; every `unsupported` document refused with a typed exit code (17 scan, 19 form, 20 page cap) | every sweep and lane read | A crash is the one failure a tester cannot work around |
| 2 | Time | Product profile ≤ 60 s for documents of ≤ 40 pages, ≤ 1.5 s per page above; raw ≤ 1 s per page | one-at-a-time timings (`testkit/serial_timing.py`), preferred document by document; otherwise `convert_s` in the product and raw sweeps, which run documents side by side and read 1.4–2.3× slower | The product profile is what `exactdoc file.pdf` runs when LibreOffice is installed; minutes per document reads as a hang |
| 3 | Word opens cleanly | 100% open with no repair prompt; compatibility mode recorded | Word lane rows (open, repair, compat) | A repair prompt tells a tester the file is broken, whatever it looks like |
| 4 | Short documents exact | Promised documents of ≤ 20 pages: 100% page-exact in each lane | LibreOffice, Word, Docs live | A memo or letter that gains a page is visibly wrong at a glance |
| 5 | Long documents close | Promised documents over 20 pages: on ≥ 80% of them, \|Δpages\| ≤ max(1, 2% of the pages) and word recall ≥ 0.85, in each lane | LibreOffice, Word, Docs live | Long reports are what people convert; page drift there breaks every cross-reference |
| 6 | No catastrophe | 0 promised documents with char recall < 0.5 or \|Δpages\| > 20%, in any lane | LibreOffice, Word, Docs live | One unusable result on a promised kind costs more trust than many small faults |
| 7 | Placement *(reported; GA gate)* | Promised ≤ 20 pages: word recall ≥ 0.9 and median vertical drift (dy_p50) ≤ 10 pt on ≥ 90% | the three lanes | Looks-like-the-original, beyond the page count |
| 8 | No regression | No document worse than in the last accepted sweep beyond `testkit/gate.py`'s tolerances, over all documents | the current sweep of the accepted sweep's profile (product since 2026-10-06) vs the accepted sweep | The beta must not lose what earlier work won |
| 9 | Editability *(reported; GA gate)* | Promised documents: text-box share ≤ 0.05, one-cell tables ≤ 1 per page, real list numbering on ≥ 90% of list paragraphs where lists exist | `editability` in the product sweep | "Editable" is the product's promise, and placement metrics cannot see it |
| 10 | Fonts | Every family the DOCX declares is in the stock Windows + Microsoft 365 set, or listed in the README | static census of the kept DOCX files | A family a tester's Word lacks is substituted, and the layout moves |
| 11 | Gated 16 | Both gate lanes PASS | the canonical gate's lane verdicts | The frozen corpus is the contract every change is held to |
| 12 | README is current | Every number the README cites matches the release sweep; no cited evidence file older than the newest measurement by more than 7 days | README.md against the inputs | Testers read the README first; a stale claim there is a false one |
| 13 | Google Docs policy *(reported; GA gate)* | The ratified per-document thresholds in `testkit/gdocs_quality_policy.json` (page match, live text, recall, SSIM, drift) on ≥ 90% of promised documents, in each lane | LibreOffice, Word, Docs live | The qualification bar the gated 16 already meet in Docs, applied to every promised document wherever it is opened |

"FAIL by N" is the number of offending documents for an all-must-pass
criterion, and for a share criterion the number of further documents that
would have to pass, summed over lanes.

Until amendment 1 below, the Data column read "LibreOffice raw" for criteria
4–6 and 13, "raw sweep vs the accepted sweep" for 8 and "`editability` in the
raw sweep" for 9.

## Amendments, 2026-10-06, ratified by the owner

No threshold changed. Both amendments change what the numbers are read from or
how they are read.

**1. Every lane is graded on the default DOCX flavour.** The scorecard graded
LibreOffice on the raw-profile DOCX (no refine loop) and Word on the product
DOCX, so the two lanes graded different files. `exactdoc file.pdf` writes the
product DOCX whenever LibreOffice is installed, and that is the file a tester
opens. So:

- Criteria 4–7, 9 and 13 read the LibreOffice lane from the **product** sweep.
  Word already rendered the product DOCX. Docs live is unchanged: it uploads the
  gdocs-profile DOCX, which is the one made for Docs.
- Criterion 2 still holds the raw profile to its own limit (≤ 1 s per page),
  read from the raw sweep. The raw sweep is also still read for crashes
  (criterion 1).
- Criterion 8 compares the current sweep **of the accepted sweep's own
  profile** with it: product against an accepted product sweep. An accepted
  sweep that does not cover the corpus (at least 90% of the documents a sweep
  runs) is UNMEASURED, because it cannot say "no document worse". The product
  sweep at the ratification point, `wp18-m2-prod.sweep.json`, ran 13 documents,
  so the first full accepted product sweep has to be named; until it is, a raw
  accepted sweep still gives the pre-amendment reading, labelled "raw flavour".

**2. The harness reads source and render the same way.** Three things in a
PDF's text layer were scored as lost words although nothing was lost:

- **Leaders.** A tab leader is however many dots fill the gap, and that
  depends on the renderer's fonts. A run of three or more leader characters
  on one line (`.`, `·`, `…`, as separate tokens, one token, or glued to the
  end or start of a word) is not counted; one or two dots are. At the
  checkpoint, 2,243 of y26's 3,027 unmatched source tokens were leader dots.
- **Symbol-font code points.** A symbol font without a Unicode map reaches
  every extractor as private-use U+F020–U+F0FF. For faces with a published
  encoding (Symbol, ZapfDingbats, and two codes of MathType's MT Extra), the
  code is read as the character it encodes, keyed by the span's font.
- **Brackets and maths operators** are their own tokens, so maths set with
  different gaps (`( i − 1 )` against `(i−1)`) matches. The hyphen, comma,
  slash and asterisk are not split.

Each rule is applied by one function to both the source and the render, so it
can only stop counting a difference that is not one: text that is really lost
still counts as lost, and the unit tests pin both sides
(`tests/test_harness_reading.py`). The same renders read differently from this
date on, so numbers before and after it are compared only through
`testkit/rescore.py`, which re-reads saved renders without converting anything
and keeps the old reading beside the new
([evidence](evidence/scorer-2026-10-06.json)). The gate's recorded baseline was
measured with the old reading; re-recording it is a separate owner decision.

## Amendment 3, 2026-10-10, ratified by the owner

No threshold changed. Two readings change, each applied to the source and the
render alike by the same function (`testkit/harness.py`, pinned by
`tests/test_harness_baseline.py`).

**Placement is measured at the text baseline.** Within-2pt, `dy_p50` and
`dy_p90` (criteria 7, 8 and 13, and the gate) compared the tops of two words'
boxes. A box top is not where the text is: PyMuPDF derives it as the glyph
origin minus the font's ascent, and the ascent is whatever the PDF's copy of
the font declares. Measured on the corpus, the box top sits above the
baseline by 1.075 em for an unembedded Helvetica and 1.053 em for Times-Roman
(r1_reportlab_report), 1.040 em for the Times New Roman and Arial that Word
embeds (y01, y29) and 0.776 em for JasperReports' Arial (y65), against
0.905 / 0.891 em for Liberation Sans / Serif in a LibreOffice render and
Arial / Times New Roman in a Word or Google Docs export. So the box-top
reading charged ~1.7pt at 10pt to every word of a base-14 source although
nothing had moved, and credited the same amount to a render whose text really
sat 1.7pt off. The baseline is the glyph origin, a number in the content
stream that every reader lines text up on. Checked against the ink (the
glyphs' outlines, letters without descenders) on 12 documents in the
LibreOffice product lane: the median vertical drift of the ink and of the
baseline agree within 0.11pt, where the box top was off by 0.14-1.74pt. A
word's baseline is that of its largest characters, so a glued superscript
does not move it; text on a line that is not horizontal keeps its box top.
Words are still paired by text, so word recall cannot move. This supersedes
the decision recorded in [dy-ascent-artifact.md](dy-ascent-artifact.md) to
keep glyph tops and exempt the artefact instead.

**Live text is read the way the words are.** `live_text_cov` (criterion 13,
the gate) reads the source through amendment 2's symbol-font table and leader
rule, and the DOCX's live text the same way (private-use characters through
the run's font, leader runs dropped). y10's equations are Symbol PUA in the
source and "=", "+" in the DOCX: 0.787 -> 0.932 in LibreOffice and Word;
x02's contents dots are tab leaders in the DOCX: 0.741 -> 0.972. The gated 16
do not move.

**What moved**, re-read by `testkit/rescore.py` from saved renders (nothing
converted; every row's previous reading recomputed beside the new one and
equal to what was recorded or re-scored before, on all 1,144 rows;
[evidence](evidence/scorer-baseline-2026-10-10.json)). The round-4 renders
(tree 71558af):

| | before | after |
|---|---|---|
| Gate renders, product: mean within-2pt / median dy_p50 | 0.7304 / 0.525pt | 0.8156 / 0.35pt |
| Gate renders, raw | 0.5466 / 1.245pt | 0.6168 / 0.65pt |
| LibreOffice product, 90 documents, mean within-2pt | 0.381 | 0.396 |
| Word product | 0.369 | 0.389 |
| Google Docs live | 0.242 | 0.295 |

The artefact goes: f1_fpdf_brief 0.629 -> 1.000, 02_research_paper
0.605 -> 0.922 in LibreOffice product; in Docs 04_exec_brief 0.05 -> 0.56 and
r1_reportlab_report 0.47 -> 0.94; documents with embedded fonts are unchanged
(c1_whitepaper 0.873, c6_long 0.977). Real drift stays and some surfaces:
in the product DOCX opened in LibreOffice and Word, Word-produced sources
whose fonts declare 1.040 em now read 1.7pt high, where their box tops agreed
-- y01 dy_p50 0.23 -> 1.74pt (within-2pt 0.800 -> 0.671), y30 0.32 -> 2.17pt
(0.724 -> 0.282), y09 and y29 alike, the ink agreeing each time. The raw DOCX
places the same lines right (y01 1.73 -> 0.34pt).

Criteria on the round-4 data: **7** no document changes in any lane; **8**
against the accepted wp31-prod sweep, both read the same way: FAIL by 1 ->
PASS (y61's dy_p50 35.91 -> 39.56pt was beyond its 3.59pt tolerance at the
box top; 37.00 -> 40.53pt is within 3.70pt at the baseline); **13**
LibreOffice and Word 40 -> 45 of 62 (live text: x02, y01, y10, y30, y36), Docs
36 of 62 either way.

The gate's recorded baseline was measured at box tops. Until it is re-recorded
(a separate owner decision), the gate reads one finding against it: raw
05_memo within-2pt 0.1205 -> 0.0602, ten of 83 matched words within 2pt at the
box top and five at the baseline. The five that leave (a dash, "August"
twice, two bullets) sit 2.05-3.55pt above their source baseline and were
inside 2pt only by Helvetica's box-top bias.

## Amendment 4, 2026-10-10: criterion 8's dy_p50 (owner-delegated decision)

The owner delegated this question to an independent decider (Fable 5.1), whose
decision stands as the owner's for it: "A+cap". The rule, verbatim:

> A document's dy_p50 that is worse than the accepted sweep beyond gate.py's
> tolerance does not count as a regression when, on the same document against
> the same accepted row and in the same harness reading, (i) within2pt rose by
> more than its tolerance (0.05), (ii) within5pt did not fall by more than
> 0.05, and (iii) the dy_p50 rise is at most max(3pt, 30% of the accepted
> value). Every other metric, including within2pt, word_recall, doc_recall and
> page_err, is judged exactly as before. A row without within5pt gets no
> exemption. The scorecard names each exempted document with its dy_p50,
> within2pt and within5pt deltas and the cap applied.

Enforced with it:

- **(a) Same reading on both sides.** The final product sweep is compared with
  an accepted sweep read the same way, named by file and SHA-256. When the two
  sweeps record different readings (`rescored.scorer`, written by
  `testkit/rescore.py`), criterion 8 is UNMEASURED: a mixed-reading scorecard
  is invalid. From WP41c every sweep records its reading itself: `reading` =
  {`scorer`: `harness.HARNESS_READING`, `source`: a hash of the harness's
  reading code}, written by `quality_sweep.py` and by `rescore.py` (which also
  writes `rescored.scorer`). The name is bumped by each amendment that changes
  the reading, in the same commit. A side that records no reading is compared
  with a non-blocking warning, "reading unrecorded"; the same name over a
  different code hash draws a "check the bump" warning. **Transition:** every
  sweep scored before WP41c and never re-scored (r4-*, wp33-*, wp39-*, …)
  records nothing and reads with the warning. Re-scoring it with
  `testkit/rescore.py sweep` records the reading, and any sweep run from this
  commit on records it, so the final product sweep and its accepted sweep
  carry no warning.
- **(b)** y43 is re-checked on the final sweep (its within2pt rise clears the
  0.05 by 0.0023). A document that no longer meets (i)–(iii) is a plain FAIL,
  with no waiver to fall back on; the question then goes back to the owner.
- **(c)** The text above, the rule in `testkit/beta_readiness.py`
  (`dy_exemption`; constants `c8_dy_*` in `BAR`) and its tests land in one
  commit, before the final sweep.
- **(d)** A document is judged by this rule or by a waiver, never both. A
  document that has a dy_p50 waiver entry is left to the waiver, whatever the
  waiver's verdict; the rule does not look at it (as decided for y37: on its
  waiver, not re-based).
- **(e)** After the beta: the wrap fidelity of y43 and y55, and how criterion 8
  reads dy_p50 for GA, are revisited.

**Evidence.** The reviewer's rule scripts over 272 same-reading pairs of full
product sweeps: y18, y33, y43 and y55 exempted (y54's dy_p50 too, but it still
fails on recall); y26, y59, y61, y21, y37 and the reverse of y18's pair (within5pt
−0.125) still fail. Re-run with the implemented rule on the sweeps kept in the
run folder: y18 on wp34-g10 → wp33-a (dy_p50 3.20 → 4.51 under a 3pt cap,
within2pt +0.122, within5pt −0.021); y33 on wp21-base → wp34-g10 (0.35 → 1.89,
within2pt +0.268, within5pt +0.464: 30% alone would have flagged this real
gain, hence the 3pt floor); y43 on wp39-A → wp39-C (8.79 → 10.64, within2pt
+0.0523, within5pt −0.0014); y55 on the same pair (15.56 → 17.26 under a
4.67pt cap, within2pt +0.0645, within5pt +0.0047). On wp39-A → wp39-C those two
are the only flags, and both are exempted; on
`accepted-wp31-prod.rescored` → `wp33-d1-prod` nothing is exempted: y21 and
y61 still fail, and y37 (within2pt +0.0008) would not meet (i) even if the
rule looked at it.

*y37:* a dy_p50 exception for 0.3.0b1 was decided (owner-delegated, 2026-10-10)
but not needed: WP33n (d8e27d6) removed the flag, so no waiver is recorded.

## Exceptions to criterion 8

An owner decision can excuse **one metric on one unpromised document** from
criterion 8, in the form the Google Docs quality policy already uses for its
waivers. The entry lives in `testkit/beta_waivers.json` and names the
document, the metric, a bound (a ceiling for a metric where lower is better,
a floor where higher is), the release it is granted for, the accepted sweep
it was measured against by file name **and** SHA-256, the harness reading,
who decided and when, the evidence, and the conditions. Each exception is
recorded on this page in the same commit as its entry. No threshold changes.

`testkit/beta_readiness.py` reads it with criterion 8:

- the document is flagged on that metric, the accepted sweep is the one named
  and the current value is inside the bound → the flag is lifted and the
  criterion prints the waiver beside its PASS ("PASS (1 waived)");
- the current value is past the bound → **blocking**, "waiver out of bounds"
  (a new decision is needed);
- the accepted sweep (name or SHA-256), the release or the harness reading is
  not the one the waiver names → **blocking**, "stale waiver": the waiver dies
  with the sweep it was measured against and is not carried to another
  release;
- a waiver for a promised document, or one without a finite bound, is
  **refused** (blocking): a promised document's bar is the README's promise,
  and an unbounded waiver is a waiver of anything;
- the document is no longer flagged → a non-blocking note, "waiver unused,
  delete it".

Every other metric on a waived document stays gated at full tolerance, and the
JSON output carries each waiver's verdict.

## Amendment 5, 2026-10-10, ratified by the owner

No threshold changed. **A letter-spaced (tracked) run of glyphs reads as the
word it spells**, on the source and the render alike (`testkit/harness.py`,
harness reading `"wp42"`; `tests/test_harness_tracking.py`). A run set with
tracking has the same extra advance after every glyph, and the text extractor
synthesises a space wherever a gap looks wide enough: x17_resume_twocol's
headings (Liberation Sans Bold 9.5pt, 0.146-0.202 em after every glyph) read
"S UM M ARY", "E X P E RI E NCE" in the source while the DOCX, Word and Docs say
"SUMMARY". A run joins when every glyph gap in it, inside its tokens and
between them, is tracking-sized (0.08-0.25 em) and alike (within 0.08 em), and
no gap holds a space the producer drew. Ordinary words never qualify (their
glyph boxes touch: 0.036 em at the 99th percentile over the 95 sources), nor
justified or ordinary word spacing, nor maths.

On saved renders (`testkit/rescore.py`, nothing converted; the previous reading
recomputed beside the new one equals the recorded rows): x17 word recall
0.953 -> 0.985 in LibreOffice and Word and 0.889 -> 0.979 in Docs, x18 alike;
y28 0.993 -> 0.991 in every lane, because its DOCX writes the tracked "Page"
footer as "P a g e" with real spaces -- a converter defect this reading now
sees. No other document moves by more than 0.002, and no gated number moves.
