# WP15 resume notes (temporary; removed before the final commit)

Branch: worktree-agent-a9cd0f4f2d161e494, started from integration 79d2100.
Scratch: SCR\wp15 (tools: conv.py, drift.py, spread.py, sheet.py, cmp.py,
hfdiff.py, laydiff.py, docxdiff.py, rotcmp.py, head\ = git archive of HEAD).

## Done (in the WIP commit)
- docxout: blank source pages held (`_blank_page_holder`, only behind a page
  whose stack fits); slide writer (framePr paragraphs, tblpPr tables,
  wp:anchor floats via `anchor_floats`); framed header elements excluded
  from `_hf_height`.
- infer: deck detection (`_deck_pages`, landscape + median text >= 14pt),
  `_lock_slide`/`_frame_para`, `_float_graphics`; deck => no furniture,
  margin_b 4pt; `_float_backgrounds` (picture under text / bleeding into
  top-bottom margin) for anchored profiles; `_merge_graphic_rows`;
  pleading: `_line_number_gutters`, `_page_number_gutter`, full-height rules
  consumed, `PAGE_RULE_FRAC` in margins, `_header_gutter` (framed header);
  `_author_break` (double-spaced paragraphs); marker ending a block glued
  (`_has_item_beside`), `SECTION_NUM_RE` markers; joint-square not boxlike;
  long underline under a whole span; `_mirrored_furniture` (+ folio
  numbering offsets, `_front_matter_folios`, their rules);
  `_numeric_column_edge` + figure column not a text column (y35).
- parse_pdfium: glyph `turned` from text matrix; `_line_number_column`
  keeps a 1..9 gutter out of rotated runs; `_line_number_gutter` split +
  `_blocks_apart_from_gutter`.
- options: capability "anchored" (standard only; gdocs unchanged);
  convert passes it to infer.
- tests/test_office_export_classes.py (46 tests, pass locally).

## Measurements (canonical container, raw lane, both corpora)
- base wp15-base-raw (79d2100 tree): page-exact 40, word recall 0.5796.
- s3 (before y35 numeric edge + parser narrowing): page-exact 46, word
  recall 0.639, char recall 0.774, within2pt 0.223; y34 98->40 (0.92
  recall), y32 35->37 (0.99), y63 9->5 (0.995), y31 19->18 (0.975), y30
  33 (0.92), y33 82->69, y36 42->32, y28 37->32, y24 169->184 (recall up).
  Regressions in s3: y03 63->66, y10 38->40 (parser vertical-run change,
  since narrowed to `_line_number_column`), y21 71->75, y22 223->226,
  y40/y41 +1 (same cause, narrowed).
- Gated 16: layout and every DOCX XML part identical to HEAD (laydiff,
  docxdiff, local).
- Local after: y35 14->14 recall 1.00.

## Next
1. Merge integration (now 0b0f787: WP2 headers/footers + full-page picture
   anchor touching y34), resolve keeping both.
2. Re-run raw sweep (both corpora) + product sweep on targets; check y21/y22
   regressions; gate_full (both lanes).
3. CHANGELOG entry, narrative commit(s), delete this file.
