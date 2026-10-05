# Checkpoint — 2026-10-05

This is where the improvement programme of 4–5 October 2026 stopped. It covers
where exactdoc stands, what is left before the first public beta, and how to
pick the work up again.

**State:** version 0.2.0a1 (alpha), nothing published, `main` untouched. Every
change below is on the integration branch `claude/exactdoc-pdf-docx-tool-d4bf20`.
It is pushed and passes the canonical gate in both lanes (16/16 page counts,
within-2pt 0.7209 product / 0.5463 raw).

## The beta scorecard

The owner ratified the beta bar on 2026-10-05 ([beta-bar.md](beta-bar.md)).
The beta (0.3.0b1) is not tagged while any gating criterion fails. The
checkpoint reading is **NOT READY: 6 pass, 4 fail**
([evidence](evidence/beta-readiness-2026-10-05-checkpoint.json)).

| # | Criterion | Checkpoint |
|---|---|---|
| 1 | No crashes; unsupported PDFs refused with typed exit codes | PASS: 0 errors in 365 conversions |
| 2 | Speed (product ≤60 s up to 40 pages, ≤1.5 s/page above; raw ≤1 s/page) | PASS: 0 of 90 over, 29 timed one at a time |
| 3 | Word opens every DOCX with no repair prompt | PASS: 90/90 (compatibility mode 14) |
| 4 | Promised documents of 20 pages or fewer are page-exact in every app | PASS: 41/41 in LibreOffice, Word and Google Docs |
| 5 | Promised documents over 20 pages: pages within max(1, 2%) and word recall ≥ 0.85 on ≥ 80% | **FAIL**: LibreOffice 11/21, Word 15/21 (product DOCX; raw DOCX 11/21), Google Docs 10/21. Each needs 17 |
| 6 | No badly broken promised document (char recall < 0.5 or pages off > 20%) | **FAIL by 1**: y12 (IRS Pub 15) in Google Docs, 72 pages for 59 |
| 8 | No document worse than the accepted sweep | **FAIL by 2**: y26 doc recall 0.992 → 0.971; y61 dy_p50 33 → 39 pt |
| 10 | Fonts: stock Windows + Office, or listed in the README | PASS |
| 11 | The 16 gated documents pass both gate lanes | PASS |
| 12 | README numbers match the release sweep | **FAIL by 2**: two stale citations; refresh at release time |
| 7, 9, 13 | Placement, editability, Docs policy | Reported for beta, gate GA (Word placement 37/41 already meets the GA share) |

## What the programme changed

Raw lane (LibreOffice, no refine loop), the same 90 documents before the
programme and at this checkpoint:

| | Before | Checkpoint |
|---|---|---|
| Page-exact | 39/90 | 59/90 (product lane 69/90) |
| Mean word recall | 0.557 | 0.760 (product 0.842) |
| Mean char recall | 0.703 | 0.856 (product 0.909) |
| Mean within-2pt | 0.134 | 0.274 (product 0.363) |

- **Google Docs (live):** 57 of 90 documents page-exact, mean char recall
  0.855. In the earlier partial sweep it was 29 of 68 and 0.760.
- **Word (first ever measured):** 65 of 90 page-exact with product DOCX, 57
  with raw DOCX.

The work packages are each in CHANGELOG.md with their evidence:

- **WP12** two-column papers
- **WP13** designed panels, cards, sidebars and CV gutters
- **WP14** right-to-left text
- **WP15** slides, pleadings and Office exports
- **WP18** end-of-page spills
- **WP19** Google Docs page-fit planner
- **WP20** release engineering, and the speed work in WP20b and WP20c
- **WP21** Microsoft Word in the loop
- **WP22** regressions and badly broken documents
- **WP23** long-document pagination

## What is left for the beta, in order

1. **Long documents (criterion 5)** need 6 more in LibreOffice, 2 more in Word
   and 7 more in Docs. The remaining causes, by document:
   - y02: the canonical image lacks Carlito, so Calibri titles wrap; the
     glossary overflows.
   - y03, y10: maths fragments and dot-leader tokens.
   - y12: booklet flow.
   - y18: 1pt seam carriers.
   - y21, y22: side-by-side regions are read as one column.
   - y24: tables cut by page breaks.
   - y33: footnotes.
   - y64: a line welded across the gutter.
   - In Docs only, y01 and y28: anchored pictures are standard-profile only;
     a small Docs probe would show whether Docs accepts them.

   The diagnosis files are in the WP19, WP22 and WP23 notes in CHANGELOG.md.
2. **Branch `wp19b`** is finished but **not merged**. It was flown live on all
   62 promised documents
   ([evidence](evidence/gdocs-2026-10-05-wp19b-probe3-live.json)).
   - It gains: Docs placement roughly doubles (short documents 0.232 → 0.313
     within 2pt, long 0.079 → 0.159), y26 passes criterion 5, and y03 reaches
     47 pages for 46 at word recall 0.849.
   - It blocks:
     - y46 spills to a second page, which fails criterion 4;
     - 01, 03 and 04 lose within-2pt to a uniform 2–3 pt offset (their SSIM
       rises);
     - y28 gains a page.
   - Fix those, re-fly, and merge.
3. **Criterion 6:** y12 in Google Docs, 72 pages for 59.
4. **Criterion 8:** recover y26's doc recall and y61's dy_p50.
5. **Criterion 12:** refresh the README numbers from the release sweep.

## Decisions waiting for the owner

- **Gate baseline:** the gated within-2pt rose from 0.6427 / 0.4853 to 0.7209 /
  0.5463 (WP21's table edges). Re-recording would lock that in. It needs the
  owner's approval; the tool is `scripts/dev/rerecord.sh`.
- **Word's "Compatibility Mode" banner:** mode 14 is kept, because mode 15
  re-wraps justified text (Word within-2pt 0.239 → 0.193). Removing the banner
  means making the layout correct under mode 15 first.
- **Publishing:** once the bar passes, the owner's steps are in
  [releasing.md](releasing.md). They cover trusted publishing on PyPI and
  TestPyPI, the GitHub environments, making the repository public, and the
  version bump.

## How to resume

The measurement scripts are in [scripts/dev/](../scripts/dev/README.md).

1. Gate a tree: `bash scripts/dev/gate_full.sh <name> <tree>`.
2. Sweep it: `KEEP_DOCX=1 bash scripts/dev/sweep.sh <name> <tree> --corpus both --profile raw`.
3. Run the live Google Docs sweep: `EXACTDOC_ROOT=<tree> python scripts/dev/gdsweep.py <out> --corpus both`.
4. Run the Word lane: `python testkit/word_oracle.py sweep <out> --docx-dir <runs>/<name>.docx/raw`.
5. Read the scorecard: `python testkit/beta_readiness.py ...`.

LibreOffice is a poor proxy for Google Docs, so gdocs-profile changes are
promoted only on Google's own exports.
