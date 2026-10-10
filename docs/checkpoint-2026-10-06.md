# Checkpoint — 2026-10-06 (round 3)

Round 3 ran from the 2026-10-05 checkpoint ([checkpoint-2026-10-05.md](checkpoint-2026-10-05.md))
to the owner's 02:30 wrap-up on 2026-10-06. The coordinator planned; Opus 5.5
agents implemented in isolated worktrees; an independent Opus review reshaped
the plan first ([the review's findings are summarised below](#what-the-plan-review-changed)).

**State:** version 0.2.0a1, nothing published, `main` untouched. Every merge is
on `claude/exactdoc-pdf-docx-tool-d4bf20`, pushed, and passed the canonical
gate before its push (last full gate: 1670+ tests OK, both lanes PASS,
16/16 page counts, within-2pt 0.7304 product / 0.5466 raw under the new
scorer; the recorded baseline is still 0.6427 / 0.4853 and has not been
re-recorded).

## Bar amendments ratified by the owner (2026-10-06)

1. **Lane flavour:** LibreOffice and Word are both graded on the default
   (product) DOCX flavour. Implemented in `testkit/beta_readiness.py`
   (`BAR["lo_flavour"]`), documented in [beta-bar.md](beta-bar.md).
2. **Scorer:** the harness reads source and render alike: leader runs of three
   or more dots are not words, Symbol/ZapfDingbats/MT Extra private-use
   characters read as what they encode, brackets and operators are their own
   tokens (`testkit/harness.py`, `testkit/rescore.py`). Re-scored checkpoint
   data: [scorer-2026-10-06.json](evidence/scorer-2026-10-06.json).
3. **Carlito in the canonical image:** built as `exactdoc-gate:boot-carlito`
   on branch `wp31` (not merged; see below).

## What merged tonight

| WP | Change | Measured effect |
|---|---|---|
| WP26 | a longtable cut by the page foot is one table (`infer._open_foot`) | y24: 181→180 pages, word recall 0.55→0.99 in LibreOffice, Word and Docs (live) |
| WP28 | WP22's run-in marker rule narrowed; README numbers refreshed | y61 back to its accepted dy_p50; criterion 12 PASS |
| WP29 | the two bar amendments | criterion 5 on checkpoint data: LO product 18/21, Word 16/21; y10 and y26 pass (scoring artefacts gone) |
| WP24 | the Docs placement model finished; `anchor_pictures` granted to gdocs; per-page rule for unmodelled pages | live Docs: y01 81→80 (wr 0.41→0.96), y28 22→21 (0.40→0.99), y12 72→69 (criterion 6 clears); short set mean within-2pt 0.278→0.462, SSIM 0.828→0.887; standard profile byte-identical |
| WP27 | question panels are a one-row table, not a figure; note separator and stacked marks | y33: LO raw 62→60 (wr 0.49→0.99), Word raw 63→60 |
| WP27b | full-bleed page backgrounds anchored behind text under gdocs (`infer._float_backgrounds`) | live Docs: y33 63→60 pages, wr 0.30→0.99, within-2pt 0.02→0.54 |
| WP30 | standard-profile page-fit planner (`exactdoc/pagefit.py`), **switched off** (`PAGEFIT_ENABLED=False`) | on: LO raw 11→13/21 (y18 156→144, wr 0.39→0.99; y33 60), Word product 15→16/21; but y59 regresses (dy_p50 30→46) |

Live Google Docs evidence for each is in `docs/evidence/gdocs-2026-10-06-*.json`.

## Scorecard

Measured on the 2026-10-05 checkpoint renders re-scored under the amended
scorer ([beta-readiness-2026-10-06-rescored-checkpoint.json](evidence/beta-readiness-2026-10-06-rescored-checkpoint.json)):
**NOT READY, 7 pass / 3 fail.** Criterion 5: LO product 18/21 PASS, Word
16/21 (needs 17), Docs 10/21 (needs 17). Criterion 6: y12 in Docs.
Criterion 8: one raw-flavour movement (y61 under the new scorer).

Tonight's merges were each measured live but **no full sweep of the final tree
has been run** (the PC was shut down at the owner's request). Projected from
the live flights: Docs criterion 5 rises to about **14/21** (+y24, +y33, +y01,
+y28), criterion 6 clears (y12 69 pages for 59), LO product stays 18/21, Word
16/21. **First job next session: run the full raw and product sweeps, the live
Docs sweep and the Word lane on the new head, then `beta_readiness`.**

## Branches finished but not merged

- **`wp25` (ab98f63)** — column and gutter rules. y64 passes criterion 5 in
  every lane with both rules on (44→39 pages, wr 0.34→0.95), but the gutter
  rule (`parse_pdfium._gutter_channels`) costs y21's product word recall
  0.71→0.52 and moves y61/y21 dy_p50 beyond tolerance; the cursor rule alone is
  regression-free but does not flip y64. Per-rule numbers are in its evidence.
  Next: diagnose y21 under the gutter rule (same page count, words misplaced).
- **`wp30b` (2de7e08)** — `PAGEFIT_MAX_OVER_LINES` cap for the planner. N=10
  keeps every gain and removes y59's regression (N=3/5/8 do not); the margin
  is thin (y59's page is 11.1 lines over). Needs a full sweep and gate with
  the planner on before enabling.
- **`wp31` (d5db458)** — Carlito/Caladea in the gate image. Not merged
  because its `fonts.conf` change moves the canonical fingerprint; merging
  before the image switch would fail every gate in the current image. Switch
  procedure (7 steps, owner approval for the re-record) is in
  `scripts/dev/README.md` on that branch. Effect measured: y02 120→118 raw,
  placement up on y20/y30/y33, y17 194→195 and y33 62→63 raw (LibreOffice now
  matches Word). Commit af95f6e (`EXACTDOC_GATE_IMAGE`) is safe to merge alone.

## Decisions waiting for the owner

1. **Accepted product sweep for criterion 8** (there is no full product sweep
   at the ratification point): naming `ckpt-prod` makes criterion 8 PASS on
   checkpoint data; against `wp21-base-prod` eight documents are worse.
2. **Re-record the gate baseline** under the new scorer (and again after the
   Carlito switch): lanes now read 0.7304 / 0.5466 against 0.6427 / 0.4853.
3. **Criterion 10's font census flavour** (raw or product DOCX).
4. **Compatibility Mode banner** in Word (mode 14 kept; mode 15 re-wraps).

## What is left for the beta

- Criterion 5 in Docs (~14/21 → 17): y02, y03 (47 for 46 at wr 0.849 — a
  hair), y10 (37 for 36), y12 (booklet), y18, y21, y22, y64 (wp25).
- Criterion 5 in Word (16 → 17): y64 (wp25) or y18 (wp30 planner on).
- Known causes not yet fixed: NIST notice boxes written one bordered paragraph
  per line (Docs adds ~1.5pt per line; y01/y08/y09); y09's justified box lines
  overhang the column; y64's "HOUSEHOLD DATA / Table A-n" titles consumed by
  the varying-furniture pass (needs a "must clear the body" bar); y21's cover
  title wraps (font width); lshort's side-by-side examples; y02 pp2–3 and
  p63/67/71/98; harness within-2pt measured at the word box top (≈1.8pt bias
  against reportlab/fpdf sources; baseline anchoring is the next scorer round).

## What the plan review changed

The reviewer found half the per-document causes wrong (y03 was a page-fit
spill, not maths; y02's "glossary" was appendix references; y33's Docs onset
was full-bleed backgrounds, not footnotes), the real file collision in
`docxout.py` rather than `infer.py`, and criterion 5 at 17/21 unreachable
without a standard-profile page-fit planner — which became WP30. Its scripts
are in the session scratchpad (`bar_review/`, `review/`).
