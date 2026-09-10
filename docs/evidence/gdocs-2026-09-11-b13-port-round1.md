# Live Google Docs round, 2026-09-11 — B13 after the first six ported fixes

One consented `explore` upload round (two documents, both Drive objects
deleted, no orphan ledger), run the day the first six catalogue fixes were
ported into the converter. The reference points are the 2026-09-05 hand
campaign on the same source PDF:

| | export pages | verdict |
|---|---:|---|
| converter at `66f5595`, raw output (hand campaign round 1) | 58 | DIVERGENT |
| **converter with the six ports, raw output (this round)** | **39** | DIVERGENT |
| hand-surgery reference `docx_r7` (sha `87eb4771…c75f32`) | 32 | CLEAN 1:1 |

Alignment artefacts: `gdocs-2026-09-11-b13-align.json` (spilled source pages
3, 8, 11, 13, 14, 16, 17 — exactly the table pages the hand campaign's rounds
3–5 fixed by surgery) and `gdocs-2026-09-11-y20-align.json` (Typst specimen:
5→5 pages, page-exact, content divergence only).

What this round authenticates, because only Google's own render can: the
right column now sits at the designer's edge (the converter writes the same
1114tw the hand campaign patched in), Consolas is rendered as Consolas, the
41 line-end hyphens survive as text, quote bars draw as table left borders
rather than 300pt rasterised lines, and the headings appear in Docs' outline
sidebar as Heading 1/Heading 2 — the one property the hand-patched file never
had. What it does not authenticate: the remaining seven spills, which belong
to catalogue #6 (cell partition), #7 (row heights) and #1 (carriers) and are
not yet ported. Numbers above are an explore round, not a qualification run
under the ratified policy, and say nothing about the frozen 16.
