# WP13 resume notes (paused for shutdown, 2026-10-04)

Branch: worktree-agent-ad472d44b82c61bec, fast-forwarded to integration 79d2100, then WIP commit.
Scratch: `SCR\wp13\` (laysig.py/sigdiff.py layout signatures, sbs.py LO side-by-sides,
ablate.py constant/function ablation + LO page count, cmp.py sweep compare, cuts.py, base_src = 79d2100 export).
Baseline sweep (raw, both corpora, KEEP_DOCX): `SCR\runs\wp13-base-raw.sweep.json`.

## Done (in the WIP commit; unit tests tests/test_designed_regions.py, 24 pass locally)
- model.rounded_rect_bbox + DrawCmd.rounded; parse_pdfium/parse report rounded rectangles as shape "rect".
- infer: _merge_box_rows (side-by-side one-cell boxes -> role "cards"); build_box reads its lines
  through _to_flow with forced breaks (_forced_break: room for next word, or wholly-bold over non-bold);
  box paragraph indents now cell-edge relative (docxout._write_box_paragraphs adjusted to match).
- _split_lines_at_box_edges (pre-pass, candidate rects, only where a box takes a piece) +
  _restore_uncut after element building (JUST ADDED, NOT YET MEASURED).
- Side-by-side regions: _side_splits/_split_side/_side_evidence (figure|panel|rule|sidebar)/_sbs_regions/
  _side_by_side_chunks: equal widths -> Chunk(n_cols=2) (`_sbs`), else TableEl role "layout"
  (_layout_table; Cell.blocks holds the column flow; nested boxes). Called in _assemble_chunks only when
  the twocol path did not fire.
- docxout: Cell.blocks writer (_write_cell_blocks), negative tblInd, layout rows pinned atLeast,
  no row shrink for layout; _merge_grid_page_runs refuses pages with `_sbs` chunks.
- layout.page_sequences used by headings/caps headings/list hangs/lists._collect/structures numbering check;
  iter_paras and gdocs_metrics walk layout blocks.
- Gutter columns (y44): _gutter_column in _measure_margins (margin -> gutter left, lay._gutter_main for
  side-margin furniture), _gutter_para (label TAB text hanging at main column).
- build_figure absorbs numeric axis ticks within 24pt (c5).
- full-bleed boxes wider than the column keep a negative indent in _to_flow.
- REMOVED (measured harmful): right-aligned line slack in _keep_room (y40 15->18).

## Measurements so far (raw, canonical container; tree before the last 5 edits)
wp13-raw-1 vs base: page-exact 40->43, mean char_recall .7375->.7601, word .5796->.6088,
within2pt .2130->.2195, live .9311->.9431. y58 4->3 (live .119->.888), y44 4->3 (char .59->1.0),
y46 2->1, y09 word .316->.901, c1 within2pt .869->.873 (gate floor .869), c5 within2pt .800->.333 (raw; now
addressed by tick absorption, unmeasured). Regressions then: y40 15->18 (fixed: slack removed, local 15),
y41 20->27 (fixed: _sbs pages not merged + figure-evidence overlap; local 20), y60 38->40 (cuts; local 39,
restore step just added), y59 20->23 (local 24 now), y61 7->8 (local 7).
Local LO after move-cut-into-build_box: y58 regressed to 4 because 'Earnings Earnings Taxed' fragment
was no longer absorbed by the p2 table figure -> reverted to pre-pass + restore (unmeasured).

## Next
1. Re-run local ablate on y58/y60/y59/y40/y41/c5 (`SCR\wp13\ablate.py`), then targeted container sweep.
2. Unit test for _restore_uncut; rerun full local suite (one earlier failure fixed by narrowing).
3. Full raw sweep + product sweep on targets; merge integration branch; gate_full.sh.
4. CHANGELOG entry; side-by-sides for y58 p1, y44 p1, sidebar (before images in SCR\wp13\sbs\before).
5. Known open: y58 masthead wraps (Arial Bold 7% wider than InDesign's kerned title; ladder MAX_TRACK
   refuses), y59 leader-line figure spanning callouts, gdocs box paragraph form drops panel shading
   (needs a live probe set, not changed).
