# WP14 (RTL and complex scripts) — resume notes

Paused for the usage limit. Branch `worktree-agent-aab8f20d3e5002018`.
Delete this file before the final commit.

## State

- `c4661c6` WP14 implementation (parser bidi inverse, RTL spaces, inference
  mirroring, OOXML bidi/rtl/cs/szCs/lang, `bidi` profile capability, gdocs probe
  set `testkit/gdocs_probe_rtl.py`, `tests/test_rtl_bidi.py`, 41 tests).
- `740c714` merge of integration a4fca48 (options.py conflict resolved: gdocs
  keeps `numbering`, standard gains `bidi`).
- `f7eabca` bracket balancer re-reads stray brackets by shape; RTL list items
  stay typed in a profile without `bidi`.
- `fa04968` merge of integration 0b0f787 (clean). Working tree clean.

## Measurements so far (canonical container)

- Gate `wp14-gate-1` at 740c714: FAILED_STEPS=0, both lanes PASS, 1224 tests OK,
  golden 6/6. c4_i18n within2pt 0.621 -> 0.872 (both lanes), dy_p50 0.15,
  live 0.909 -> 0.901 (inside the 0.010 tol; fitz reads c4's Arabic words in
  visual order, so logical text loses cross-word 3-grams).
- Full raw sweep `wp14-final2-raw` (fa04968) vs `wp14-head-raw` (a4fca48):
  ONLY the 7 target docs moved; the other 83 identical. y47 100->89 pages,
  y48 11->10, y49 56->54, y50 25->19, y54 5->4 (word recall 0.06->0.66),
  y55 3->3 (word recall 0.06->0.84), c4 within2pt +0.252. Aggregates: page_exact
  39->40, mean|ratio-1| 0.2867->0.2749, word recall 0.5903->0.6067.
- Product (targets, it7 = pre-merge c4661c6) vs base-prod (79d2100): y49 56->33,
  y47 71->63, y50 15->15 (word recall 0.68), y48 9->9.
- Before/after images: scratchpad `wp14/y49_p2_before_after.png`,
  `wp14/y47_p2_before_after.png`.

## Next steps (exact)

1. Rerun the gate on fa04968 (`gate_full.sh wp14-gate-2 <worktree>`; the run in
   flight was killed by this pause).
2. Product sweep of the targets on fa04968 and on 0b0f787 (extract with
   `git archive 0b0f787`) for the product delta table.
3. CHANGELOG.md bullet under "## Unreleased" (WP14, measured numbers above);
   README Tier 3 RTL bullet: now converted in logical order as w:bidi paragraphs
   (standard profile); gdocs writes visual LTR equivalent until
   `testkit/gdocs_probe_rtl.py` is flown live; canonical-container Arabic fonts
   (FreeSerif/DejaVu) set Arabic 27-45% wider than Arial/Noto Naskh, which is
   the remaining raw inflation for y47/y48.
4. Remove this RESUME.md, commit, final report via SubagentHandback.

## Known remaining / follow-ups

- Raw y49 still 54 pages: every page re-wraps 2.6% wider (David -> FreeSerif)
  and spills a few lines past its hard page break; product refine fixes it (33).
  Needs complex-script text metrics in metrics.py so the spill predictor sees it.
- Footnote custom marks render doubled in LibreOffice ("77") -- generic notes.py
  behaviour, not RTL-specific.
- RTL tables (w:bidiVisual) not emitted; tables keep visual column order.
