# RESUME: README rework (paused for shutdown, 2026-10-04)

Branch `worktree-agent-a5a2f7242442cf719`. Not pushed. Delete this file before the
final commit.

## Done (committed)

- 7be3b1b: pure renames into `docs/deep-dive/`: THEORY.md -> theory.md,
  STATUS.md -> status.md, ROADMAP.md -> roadmap.md,
  ESCALATION_RULING_LINEBOX.md -> escalation-ruling-linebox.md,
  docs/diagrams/support-by-engine.svg -> docs/deep-dive/support-by-engine.svg.
  No half-finished moves.
- 6f76e41: every path reference updated (links inside the moved files, code
  comments, the gate message in testkit/gate.py, corpus-expansion.md,
  license-audit.md, CHANGELOG, .gitignore comment, quality_sweep docstring,
  expansion_download_plan.json note). docs/evidence/ deliberately untouched.
- 9860f08: new README (~200 lines); old long sections moved unrewritten to
  docs/usage.md and docs/deep-dive/{limitations,measured-state,how-it-works,
  licensing}.md; docs/README.md index; 9 images in docs/images/ (25-151 KB);
  scripts/readme_images.py; docs/evidence/readme-examples-2026-10-04.json
  (the canonical product sweep at a4fca48 the images come from).
- 1bfdec2: merged claude/exactdoc-pdf-docx-tool-d4bf20 at 647fbea (CHANGELOG
  conflict resolved, both sides kept).
- c08795a: README cites the committed live sweep (gdocs-live-sweep-2026-10-04.json).
- 5976b9b (WIP): README footnote bullet notes that the gdocs output keeps
  footnotes as text.

## Next

1. Fix two README gallery captions (inaccurate, verified from the DOCX):
   - works-tables.png: the "nested detail" table is ONE table with merged
     cells, not a real nested table. Caption and alt text (README lines ~90
     and ~94) must say "a table-within-a-table is rebuilt as one table with
     merged cells", not "a table inside a table".
   - works-footnotes.png (x05): there is NO header part; "Consultation
     Response" is an ordinary paragraph. Caption (line ~103) should be
     "Quotes, links and footnotes", and the alt text (line ~99) must not
     claim a running header. Running headers/footers are shown by
     editable-structure.png (01_whitepaper_market p2: header1.xml, footer
     with a PAGE field).
2. Re-run the link check (scratchpad readme_work/linkcheck.py).
3. `git merge claude/exactdoc-pdf-docx-tool-d4bf20` again if it moved.
4. Re-run the full gate: `bash <SCR>/gate_full.sh readme-gate2 <worktree>`
   in the background; it must PASS. The first run (readme-gate) was
   interrupted by the shutdown and has no result.
5. Delete RESUME.md, final commit, hand back the report.
