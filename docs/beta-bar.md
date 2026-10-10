# The beta bar

**Ratified by the owner on 2026-10-05** ("option A": the independent bar
review's proposal, adopted exactly). **Amended by the owner on 2026-10-06**:
the lanes are graded on the product DOCX, and the harness reads leaders,
symbol fonts and maths the same way on both sides (see
[the amendments](#amendments-2026-10-06-ratified-by-the-owner)). **Amendment
4, 2026-10-10** (owner-delegated): a capped dy_p50 rise that comes with more
words within 2pt is not a criterion-8 regression
([amendment 4](#amendment-4-2026-10-10-criterion-8s-dy_p50-owner-delegated-decision)).

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
- **(e)** **Before 0.3.0b2** (promoted on 2026-10-11 by the second y37
  decision, below): a paired, common-word reading of criterion 8's dy_p50,
  designed with the owner, so that a change in which words a render matches
  is not read as words moving. After the beta: the wrap fidelity of y43 and
  y55.

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

## Exceptions for 0.3.0b1

**y37 `dy_p50`: an owner decision of 2026-10-11, by delegation to an
independent decider (Fable 5.1); option A: land WP38b and re-instate a
bounded waiver.** This is the **second time** y37's dy_p50 has needed
excusing. The first (2026-10-10, WP33's column split: 27.38 → 30.96 in the
wp29 reading) was decided and then reverted unused, when WP33n removed the
flag. Now WP38b's render-judged probe re-flags it in the wp42 reading:
27.64 → 32.00, past a tolerance of 2.76.

- **Scope.** `y37_plos_one_dvipdfmx.pdf` (unpromised: an academic journal
  paper), metric `dy_p50` only, release 0.3.0b1 only, harness reading `wp42`.
  Every other y37 metric stays gated at full tolerance; no other document is
  covered.
- **Ceiling.** 33.0pt (measured 32.00). Above it: blocking, and a new decision.
- **Accepted sweep.** The wp42 re-score of wp31-prod,
  `accepted-wp31-prod.rescored5.sweep.json`, SHA-256
  `fcb8ca9782cc62623e7c399a72a8877e667afb0c3e42d77187ea385de62b668c`
  (`reading.scorer` = `wp42`). If the final accepted sweep is another file,
  the entry names that one, by SHA-256.
- **Conditions a–f of the first decision apply, mutatis mutandis** (like for
  like in one reading; this scope; the ceiling; recorded here with the entry;
  dies with the accepted sweep it names, not carried to 0.3.0b2 or GA), with
  **d′** on the FINAL renders, by `python testkit/churn.py ... --check-y37
  --current-sweep FINAL.sweep.json` against the accepted render
  `wp31-prod.docx/product/y37_plos_one_dvipdfmx/y37_plos_one_dvipdfmx.pdf`,
  render SHA-256s recorded: word recall ≥ 0.37 (accepted 0.3268); common-word
  dy_p50 ≤ 1.1 × the accepted common; within-2pt not down by more than 0.05;
  LibreOffice out_pages < 27.
- **Void if** the ceiling or any d′ bound is missed; y37 becomes promised; the
  accepted sweep, the reading or the release differ (the scorecard reads it
  stale); a second document needs a dy_p50 waiver before the tag; or the
  owner revokes it before the tag.
- **Before 0.3.0b2:** amendment 4(e) is promoted -- a paired, common-word
  reading of criterion 8's dy_p50, designed with the owner.

**The figures, measured on WP38b's sweep (wp38b-L1-prod) in the wp42 reading;
re-measured on the final renders before the tag** ([evidence](evidence/churn-y37-2026-10-11.json)).
Accepted render SHA-256
`17e58b3eaca879e7880fe70f369a70b4ef2829b2e8aede65d10558a7f869993b`, current
`1a33619027e46e8198e5cb135f8b6a90e372c56daf8c22abf51d3914980e3445`, source
`31b2894a30f71cbb3046f401c05a14a75603410d6bd808d4f308b37a0b35c77d`.

| Matched source words (of 10,699) | Words | dy_p50 (pt) | Within 2pt | \|dy\| ≤ 5pt |
|---|---:|---:|---:|---:|
| Accepted render, all | 3,496 | 27.64 | 0.0020 | 0.171 |
| Current render, all | 4,173 | 32.00 | 0.0019 | 0.149 |
| Common, read in the accepted render | 3,109 | 25.20 | 0.0023 | 0.182 |
| Common, read in the current render | 3,109 | 24.97 | 0.0019 | 0.172 |
| Lost (accepted render only) | 387 | 64.10 | 0.0000 | 0.085 |
| Gained (current render only) | 1,064 | 74.32 | 0.0019 | 0.080 |

Word recall 0.3268 → 0.3900; LibreOffice pages 27 → 24 (source 22). d′ holds
on these renders: recall 0.39 ≥ 0.37, common dy_p50 24.97 / 25.20 = 0.99 ≤
1.1, within-2pt 0.0020 → 0.0019, 24 pages < 27. Recorded honestly: 387 words
lost and 1,064 gained; 38% of the common words moved by more than 2pt; the
common set's |dy| ≤ 5pt share fell 0.182 → 0.172; dy_p90 rose 244 → 303pt;
doc recall fell 0.913 → 0.905. **No evidence of a real loss in the median;
the tail widened.**
