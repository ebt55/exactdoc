# WP13 resume notes (paused again: usage limit; state = a517dc5 + this note)

Branch: worktree-agent-ad472d44b82c61bec. Integration 0b0f787 is MERGED (commit 06cd7d4), then a WIP commit.
Scratch: `SCR\wp13\` -- laysig.py/sigdiff.py (layout signatures), sbs.py (LO side-by-sides), ablate.py
(constant/function ablation; values ID/FALSE/OFF), pages.py <tree> <outdir> docs... (local LO page counts),
cmp.py (sweep compare), cuts.py, base_src = 79d2100 export, base2_src = 0b0f787 export (the merged base).

## State of the code (all in the WIP commit)
See the earlier list in git history (d0c62cd RESUME.md). Since then:
- merged 0b0f787 (one import conflict in infer.py, resolved keeping both).
- _split_lines_at_box_edges now returns cuts; _restore_uncut joins back cuts no region claimed
  (unit tests added: test_a_cut_no_region_claimed_is_joined_back / ..._a_box_claimed_stays_cut).
- _keep_room: RIGHT_LINE_SLACK (0.10) restored but ONLY for short (<= 1/3 room) flush-right
  single lines (y40 regression came from giving it to every right-aligned line).
- _column_flow: right-aligned single lines in a side column get the same slack (y46 1 page locally).
- _gutter_column marks main-column lines `_main_col`; para_from_lines never right-aligns them
  (y44's 'Created on-device...' bullet was set flush right).
- _side_splits: a band is rejected when an item outside it crosses the split within the band's
  height (y59's leader-line figure spans the callouts).  Local LO: y59 still 21 (base2 18) -- NOT FIXED.
- tests/test_designed_regions.py: 26 tests pass locally.

## Measurements (canonical container, raw, current tree except the last _side_splits edit)
wp13-t3 (targets): c5 1 page, within2pt 0.975, word 0.878 (gate risk RESOLVED by axis-tick absorption);
c1 2 pages within2pt 0.873; 01 .339; 04 dy_p50 4.05 (= floor); y58 3 pages (base 4) live .892;
y46 1 page (base 2); y44 4 pages (earlier pre-merge run gave 3; base 4) -- contact row staircase
(5 one-baseline blocks -> 5 paragraphs) + check whether WP2 footer/margins changed; y59 21 (base 20,
base2 unknown); y60 39 (base 38); y40 15 (=base); y41 20 (=base); y61 7 (=base); y03 66? (was 63 in
old base -- compare against base2 when its sweep exists); y38 56 (old base 55); y39 29 (old 28).
Container `exs-wp13-base2-raw` (full raw sweep of 0b0f787) was running at pause; it is removed
-- RE-RUN it: `bash SCR/sweep.sh wp13-base2-raw SCR/wp13/base2_src --corpus both --jobs 6 --profile raw`.

## Next (exact)
0. FIRST: `git merge claude/exactdoc-pdf-docx-tool-d4bf20` (now 50f7436: README rework, THEORY/STATUS moved
   to docs/deep-dive/ -- put any CHANGELOG/doc references there). Nothing was started after a517dc5.
   The base2 raw sweep of 0b0f787 DID finish: `SCR\runs\wp13-base2-raw.sweep.json` -- but re-run the base on
   50f7436 if converter code changed (e6086c7 touches gdocs line heights only; check `git diff 0b0f787 50f7436 -- exactdoc`).
1. Re-run base2 raw sweep (above) and a full raw sweep of this tree (`wp13-raw-2`), compare with
   `SCR\wp13\cmp.py`. Chase any doc worse than base2 (y59, y60, y03, y38, y39 suspects).
2. y59: if still worse than base2, require 'panel' evidence bands to have no FigureEl wider than
   either side overlapping the band (or drop y59's band) -- check with pages.py.
3. Product sweep on targets + gated; full local unit suite; `bash SCR/gate_full.sh wp13-gate-1 <wt>`.
4. CHANGELOG entry under Unreleased; side-by-sides y58 p1 / y44 p1 / sidebar (before: SCR\wp13\sbs\before).
5. Report: gdocs box paragraph form drops panel shading (needs live probe); y58 masthead wraps.
