# WP15 resume notes (temporary; removed before the final commit)

Branch: worktree-agent-a9cd0f4f2d161e494.
- 2d48c4f: WIP of WP15 on 79d2100 (see that commit's RESUME.md for the full
  list of rules added and the pre-merge measurements).
- Next commit (this one): WIP merge of the integration branch 0b0f787 (WP2
  running furniture, full-page picture anchor, gdocs numbering) with conflicts
  resolved, keeping both behaviours.
Scratch: SCR\wp15 (conv.py, conv_abl.py [WP15_ABL=func,... no-ops infer
functions], drift.py, spread.py, sheet.py, cmp.py, hfdiff.py, laydiff.py,
docxdiff.py, rotcmp.py, mirwho.py; head\ = git archive of 79d2100 -- refresh
it from the integration head before re-using laydiff/docxdiff).

## Merge resolutions (done)
- options: standard = numbering+footnotes+anchored; gdocs = numbering (WP2).
- infer imports both FloatEl and HFSection/furniture.
- `_no_furniture()` now carries WP2's keys (page_numbers, num_sections,
  parity, var_lines) plus "gutter"; detect_hf uses it.
- margins: drawings excluded if page-covering (WP2) OR full-height rule (mine).
- docxout seam: my slide-lock block + WP2's `_absorb_page_spill(...,
  ctx.output_profile)`.
- WP2 now covers what `_mirrored_furniture` did (measured with mirwho.py: it
  added nothing on y36/y24/y31). Replaced by `_furniture_leftovers`:
  `_front_matter_folios` (y30 "ii"/"iii": recall 0.38 -> 0.98 with it) and
  hlines outside the legacy zones touching consumed running lines (y36's
  foot rule) -> consumed_draw + rep_draws (drawn as the foot's border).
- `_hf_extent` (infer) skips framed elements; `_header_gutter` now runs after
  hf_sections are built and adds the gutter to header_default/even/first and
  every section's header parts.

## Exact next step
0. Integration moved again to 50f7436 (e6086c7 gdocs Calibri line factors;
   README/docs moved to docs/deep-dive/, THEORY.md and STATUS.md live there
   now -- fix any path references). Merge it before the final gate. Check
   that d630b33's full-page picture anchor (`docxout._picture_paragraph`,
   every profile) and my `anchored` floats never handle the same picture:
   my floats take ImageEls out of the flow before write_image sees them, so
   decide whether a >=97%-of-page picture should be left to d630b33's path
   (exclude it in `infer._float_backgrounds` / `_float_graphics`).
1. tests/test_office_export_classes.py: `RunningRules.
   test_a_running_foots_rule_goes_with_it` fails because the synthetic
   document has 8 pages and WP2's parity pass needs
   `infer.PARITY_MIN_PAGES = 10` (debugged 2026-10-05: detect_hf consumed 0
   lines, page_numbers {}). Fix: build >= 12 synthetic pages in
   `RunningRules._pages` (keep the feet at y 772 of 842 carrying the page
   number, the rule 1.4pt above). Keep the test's intent (the rule leaves
   the flow and goes to rep_draws "bot"). Then run the whole tests/ suite.
2. Local check on the merged tree: y36 (was 38 pages after merge before the
   rule fix), y30, y63, y34, y32, y35, y31, y33, y28 with
   `SCR\wp15\conv.py SCR\wp15\m2 <pdfs>`.
3. Canonical raw sweep both corpora (compare runs/wp15-base-raw.sweep.json
   AND a fresh sweep of the integration head 0b0f787, since the base moved);
   product sweep on the targets; `gate_full` (inline docker commands; the
   bash scripts are refused by the sandbox -- run docker run/tar/exec as
   separate plain commands, no $VARS).
4. CHANGELOG entry under Unreleased, narrative commit(s), delete RESUME.md,
   final report.

## Measurements so far (pre-merge, raw lane, canonical)
base (79d2100) page-exact 40, word recall 0.580 -> WP15 s3 46, 0.639; y34
98->40, y32 35->37 (recall 0.26->0.99), y63 9->5 (0.29->0.995), y31 19->18
(0.30->0.975), y30 33 (0.72->0.92), y33 82->69, y36 42->32, y28 37->32,
y24 recall 0.39->0.50. Gated 16: every DOCX XML part identical to 79d2100.
Narrowed after s3 (not yet re-swept): parser vertical-run rule (y03/y10/
y21/y22/y40/y41 regressions), y35 numeric column edge (local 15->14, recall
0.36->1.00).
