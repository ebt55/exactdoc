# WP12 RESUME (paused again: usage limit, 2026-10-04)

**Latest:** integration head 50f7436 (gdocs Calibri factors e6086c7, docs moved to docs/deep-dive/) is
ALREADY MERGED cleanly as 86c40e4 -- no conflicts, no code changes needed. THEORY/STATUS now live in
docs/deep-dive/ (cite those paths in the CHANGELOG/commit text). Nothing measured since the merge.
**Exact next step:** step 1 below (recreate wp12-dev), but export the BASE from 50f7436, not 0b0f787:
`git archive --format=tar -o SCR/wp12/int50f.tar 50f7436` -> extract to SCR/wp12/int50f, sweep that as
`wp12-int50f-raw`. Then y40 p2/p3 (top priority per coordinator), unit suite, both sweeps, gate, CHANGELOG.

Branch `worktree-agent-aad6d0fa9d5e74b5e`. Integration branch 0b0f787 was merged earlier (commit 3ff9067).
Scratch: `SCR\wp12\` (scripts: micro.py microscope, laydump.py, laydiff.sh, qs.sh/qtab.py targeted sweeps,
dx.sh runs a scratch script in container `wp12-dev`; sync.sh copies the worktree in; set FULL=. for a full copy).

## Done (committed)
- 67e9815: two-column pages read from the GUTTER (`infer._two_column_gutter`, `_gutter_chunks`: per-line
  placement, page cut into bands at spanning items in source order), `_split_at_gutter` (lines joined across
  the gutter), `_split_crossed` (equation numbers at the margin are not a column); parser `_visual_pieces` /
  `_one_piece_per_column` in `_group_table_rows` (a 2-col body with inline maths is not a table); display
  maths as one paragraph per baseline row (`_display_rows`/`_display_paras`, `_ACCENTS` rows ride along);
  fonts: Linux Libertine/Biolinum, MathTime, txfonts.
- 1a86170 + merge 3ff9067: `_absorb_fragments` (stacked "~" over "=", same-baseline maths continuation);
  `_split_crossed` only for margin-narrow right side (lshort y22 regression fixed). My header/footer patches
  were DROPPED in the merge in favour of WP2's equivalents (`_fill_first_page_parts`, margin_t raised to the
  header reach, `_fit_footers_below_body`).
- WIP commit (this one): `tests/test_two_column_papers.py` (22 tests, pass on Windows python), and a
  tightening of `_absorb_fragments` continuation joins (must be maths and <= FRAG_MAX_SHARE of the host:
  a neighbouring column's line on the same baseline was being joined).

## Measurements so far (canonical container, raw lane)
Pre-merge checkpoint 67e9815 vs my start tree (79d2100), full sweep `SCR\runs\wp12-c1-raw.sweep.json`
vs `wp12-base-raw.sweep.json`: y41 20->10, y39 28->13, y43 31->22, y37 39->35, y42 7->7, y40 15->16,
y38 55->55; y12 83->72, y17 210->204 (recall .341->.887), y21 71->52, y03 63->56, y28 37->33;
regressions: y22 223->228 (fixed since, 221 in targeted run), y26 recall .962->.914 (216 vs 215 pages; its
index pages 206-214 now cut at the D.x headings -- look at this), y60 recall .215->.194.
c2_paper2col and 02_research_paper layouts byte-identical (laydiff) at every step, incl. the merged tree.
After merge, y40: 15 pages (integration also 15).

## Next steps (exact)
1. `docker rm -f` was run; recreate: `MSYS_NO_PATHCONV=1 docker run -d --name wp12-dev -w /work
   exactdoc-gate:boot sleep infinity`, then `FULL=. bash SCR/wp12/sync.sh`; put integration code in /base
   (tar of `SCR/wp12/int0b0f/exactdoc` -> /base) for laydiff/ROOT=/base comparisons.
2. Re-run the BASE sweep of the integration head (was in flight, killed):
   `bash SCR/sweep.sh wp12-int0b0f-raw SCR/wp12/int0b0f --corpus both --jobs 6 --profile raw`
   (SCR/wp12/int0b0f is a `git archive 0b0f787` export). Then sweep this branch (`wp12-m1-raw`) and diff
   with `python SCR/wp12/qtab.py new.json base.json`.
3. Full unit suite in the container (last full run before the merge: 3 failures, all fixed since;
   the post-merge run was killed).
4. Investigate remaining targets: y40 p2/p3 (left column text lands +270pt x -> right column / next page:
   look at `laydump y40 2,3`), y37/y38 (PLOS/eLife: one wide column + sidebar margin; inflation from display
   maths rows and figures), y26 index pages, y60 recall drop.
5. Product-lane sweep for the targets; gate_full.sh (`wp12-gate-1`) on the merged tree; CHANGELOG bullet;
   before/after side-by-side PNGs for 2 pages of y41 and y39 (`SCR/wp12/strip.py`); final report.
gdocs profile: no gdocs-specific branch was added; the infer changes apply to every profile (flag this).
