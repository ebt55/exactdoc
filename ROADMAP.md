# exactdoc — roadmap: what is done, what is left, how far

**Updated 2026-07-30.** STATUS.md is the authority on measured numbers; this
file is the authority on *sequence and distance*. If they disagree, STATUS wins
on numbers and this file gets corrected.

---

## The short answer

**The licence swap is no longer blocked.** It was the one thing standing between
this project and being usable by anyone who cannot accept AGPL, and as of
2026-07-30 the permissive parser is measured **not worse than the incumbent on
14 of 16 corpus documents**, with the remaining two attributed to a cause that
is proven unreachable from a permissive parser and formally accepted as a
documented divergence.

| question | answer |
|---|---|
| How far to `pip install exactdoc` under Apache-2.0? | **three working sessions** — see §3 |
| How far to "fully working on any PDF you throw at it"? | **much further, and it is a different project** — see §5 |
| Is anything still blocking the swap? | **No.** The one item that was queued ahead of it (superscript) turned out to need no code at all — §3.1 |

**Before the flip, the gate had to become worth trusting.** The licence swap is a
change to which parser produces every number, and it was about to be judged by a
gate that could pass while the renderer failed on every document, while a
required metric was missing, while 8 of the 16 corpus documents did not exist,
and while a known shortfall slid arbitrarily far. That work is done and is
described in [STATUS.md §1](STATUS.md#1-where-the-converter-stands): a numeric
per-document baseline, an exact corpus manifest, both lanes gating the exit code,
the parity policy as executable data rather than prose, one evidence artifact,
and a mutation test for every false-green path the old gate had.

The distinction in the last two rows is the important one. Shipping a permissive,
honest, well-measured alpha is close. Making the converter *good on documents it
has never seen* is the open-ended part, and it is deliberately not on the
critical path to a release.

---

## 1. Where the converter stands

| | value |
|---|---|
| Parity gate (pdfium vs PyMuPDF) | **2 regressions, 13 same, 1 better** |
| Started at | 9 regressions, then 8 when first measured on the canonical environment |
| Mean within-2pt, pdfium | **0.461** against the incumbent's 0.511 |
| Documents at or above the incumbent | **14 of 16** — four exactly equal, two better |
| Gate lanes (default backend) | 13/16 page match raw, 15/16 product; both lanes gate the exit code |
| Golden IR | 7/7 |
| CI | green, and fail-closed — see the three questions in [STATUS §1](STATUS.md#1-where-the-converter-stands) |
| Release-qualification gate (`--absolute`) | **fails, on the record.** D3 and D10 are below threshold and say so |
| Holdout (4 wild PDFs) | **0/4** — unchanged, and the honest generalisation number |

---

## 2. Done, with the evidence

| | what it means now |
|---|---|
| **M0 — identity reset** | Version `0.1.0a1`, Alpha classifier, every published claim reconciled to measurement. Tagged. |
| **M1 — reproducible measurement** | One command provisions a bare Linux box; the corpus generates or says exactly what it skipped; goldens carry an environment manifest; the gate is a *regression* gate with a recorded baseline, and CI runs it for real. Verified in a clean `ubuntu:24.04` container and on GitHub Actions. |
| **M2.a — instruments** | `backend_spans`, `backend_paths`, `block_gaps`, `residual`, `margin_probe`, `--only`. Six measuring tools that did not exist, each built because a question could not otherwise be answered. |
| **M2.b — page-space geometry** | Path points transformed by the object matrix; bboxes are the geometric path, not the ink envelope. 578 of 612 corpus paths carry a non-identity matrix. |
| **M2.c — block grouping** | Body-pitch reference per type size instead of a page-wide median. Block boundaries now match the incumbent exactly on the documents that were failing. |
| **M2.d — the metric box** | The single largest find: x was read from the ink box while y came from the metric box. Fixing it took three documents out of the regression set at once. |
| **M2.e — span and space fidelity** | Spans end where styles end; generated spaces have real widths; invented end-of-line spaces dropped; justified text no longer doubles its spaces. Superscript, the last item, needed no code: measured, the writer never sees the parser's flag (§3.1). |
| **The line-box escalation** | Granted, built, measured, **reverted** — and the cause closed out as unreachable. §4. |
| **M2.g — the gate made worth trusting** | One product profile shared by API, CLI, CI and docs, replacing three that disagreed. An exact corpus manifest. A numeric per-document baseline for every gated metric, replacing a list of metric *names*. Both lanes gating. The parity policy as data with numeric floors and stale detection, so `continue-on-error` could come off the step. One `evidence.json`. A mutation test for every false-green path the old gate had. |

---

## 3. Left to do, in order

### 3.1 — Superscript (`M2.e` remainder) · **CLOSED by measurement, no code**

`parse_pdfium.py` hardcodes `superscript=False`, and the plan was to implement
it. It does not need implementing, and the way to find that out was to measure
the level that matters rather than the level that looked wrong.

`testkit/backend_superscript.py` compares both levels across the corpus:

| level | what it compares | result |
|---|---|---|
| parse | spans the *parser* flags | `c2_paper2col` 3 (PyMuPDF) vs 0 (PDFium); every other document 0 vs 0 |
| **layout** | runs the *writer* receives, after `normalize()` + `infer()` | **3 vs 3 on `c2_paper2col`, identical text; 16 of 16 documents agree** |

`dialect._merge_row_lines` and `infer` both promote a small fragment sitting
above its host line's baseline, measured from geometry inside the em box, and
neither looks at the backend. So the parser flag is not load-bearing: it never
reaches a DOCX. One corpus document in sixteen even has a superscript, and its
flags survive the swap.

**Done. Verdict recorded, no backend change made:**

```bash
python testkit/backend_superscript.py
```

This is the cheaper half of a habit worth keeping — before implementing a
missing feature in a component, measure whether anything downstream consumes it.

### 3.2 — The flip and the relicence (`M2.f`) · *one session, mechanical*

This is the milestone the whole project has been driving at.

1. `pypdfium2` becomes the main dependency; `pymupdf` moves to a `[mupdf]`
   extra. **`parse.py` is not deleted** — it becomes the extra's backend.
2. Re-freeze the goldens *from the pdfium backend*, with manifest; archive the
   MuPDF goldens for diffing. Its own commit, per law 14.
3. `LICENSE` → Apache-2.0, add `NOTICE`, classifier swap, README licence
   section rewritten — including the plain statement that installing the
   `[mupdf]` extra makes the *combination* AGPL-governed for distribution.
4. Version → `0.2.0a1`.
5. Re-verify: clean venv *without pymupdf installed* converts a PDF;
   `import exactdoc.convert` pulls in no `fitz`.

**Done when:** the parity table from the canonical environment is in the PR
description, `git grep -il affero` returns only historical narrative and the
extra's documentation, and the gate is green.

**Acceptance (amended, and this is why it is now reachable):** 0 regressions,
except `01_whitepaper_market` and `02_research_paper`, attributed in STATUS D2
to a font-metric convention no permissive parser can reproduce.

### 3.3 — Ship the alpha (`M3`) · *one session*

1. **D8**: encrypted and truncated PDFs raise a clean `UnsupportedInputError`
   with a non-zero exit, not a backend traceback. Both degenerate files go into
   CI.
2. Package: name check, wheel + sdist, TestPyPI dry run, then PyPI.
3. Release notes that lead with what it is *measured not to do* as well as what
   it does — corpus numbers and the 0/4 holdout in the same breath — plus one
   side-by-side screenshot.
4. Invite the contribution the project actually needs: *a PDF that breaks it*.

**Done when:** `pip install exactdoc` on a machine with no dev setup converts a
browser-printed PDF, and the PyPI page reads Apache-2.0, `3 - Alpha`, 0.2.0a1.

---

## 4. Closed, and why they will not be reopened

Recording these so nobody spends another session rediscovering them.

- **The last two parity regressions.** `infer()` derives the page's vertical
  origin from line-box tops — the one vertical quantity two correct parsers
  legitimately disagree about, because each reads it from font-metric tables
  the other does not have. Proven unreachable: pdfium exposes exactly one
  vertical font metric and the parser already uses it; matching PyMuPDF means
  vendoring MuPDF's base-14 table, which the licence plan forbids and which is
  measurably version-dependent. A baseline-anchored origin was granted, built
  and reverted — it reached 0.000pt backend agreement on 14 of 16 documents and
  still cost the *incumbent* `c6_long` 0.76 → 0.45, because the spacing chain
  downstream is itself calibrated on box tops. Fixing it properly means moving
  the origin, `_para_box` and the `space_before` chain together: a real project,
  not a patch. Instrument kept: `testkit/margin_probe.py`.
- **Structural convergence of the IR.** Finished, and *demonstrated* finished:
  three separate structurally-confirmed changes scored exactly flat, and the
  third explained the other two — justified text lets the renderer redistribute
  inter-word space, so text- and span-level differences cannot reach
  `within2pt` at all.
- **Matching PyMuPDF bit-for-bit** as a target. It refuses to reproduce three
  PyMuPDF behaviours because they are bugs, and PyMuPDF's grouping is not stable
  across its own point releases. The parity gate is the contract; the golden IR
  is a microscope.

---

## 5. After the release — the part that is genuinely open

None of this blocks shipping. All of it is what stands between "a good alpha"
and "trust it with any PDF".

| | state |
|---|---|
| **D1 — LaTeX/pdfTeX pagination** | The largest open defect and the reason the holdout is 0/4. Page counts inflate 25–90%; text survives 94–97%. Three attribution attempts each produced a partly-wrong answer. Needs writer-side instrumentation — per-element emitted-vs-source height accounting inside `docxout` — not another hypothesis. |
| **The holdout** | 0/4, and it is the honest generalisation number. It moves when D1 moves. |
| **D3 nested tables** | Inner borders misplaced, cell content merges. |
| **D4 rounded-corner cards** | `border-radius` makes the card a curve; the detector requires a rect. |
| **D5 letter-spaced headings** | Tracking-spaced text loses its spaces. |
| **D6 mixed page geometry** | Page size and orientation taken from page 1 for the whole document. |
| **D7 Google Docs** | The actual target renderer, and the least measured. The full-bleed cover band has *never* been checked in Docs — the single most likely silent failure of the stated product goal. |
| **D9 `w:shd` spam** | File-size smell, not a correctness bug. |
| **The vertical model** | §4's baseline-consistent rewrite. Would close the last two parity regressions and probably help everywhere. |

**Honest distance to "fully working":** unknown, and anyone who gives you a
number for it is guessing. D1 alone has resisted three attributed attempts. What
*is* known is that it does not block a release, because the release does not
claim to have solved it — the README leads with the 0/4.

---

## 6. How to tell if this is on track

The project's own discipline, in four checks anyone can run:

```bash
bash scripts/bootstrap.sh --strict && python testkit/gen_corpus.py testkit/adv --strict && python corpus/make_corpus.py
```

```bash
python testkit/corpus_manifest.py verify
```

```bash
python testkit/runall.py
```

```bash
python testkit/backend_parity.py
```

The first must produce all 16 documents — `--strict` makes a skip a failure,
because the un-strict version printed "the corpus is incomplete", exited 0, and
the gate then scored 8 documents against a 16-document baseline. The second
proves the corpus is the one the baseline describes. The third must print
`gate PASS` for **both** lanes. The fourth is the swap's verdict, and it is now a
required check rather than a report.

Every number in STATUS.md traces to `testkit/batch/evidence.json`, which those
commands write and CI attaches to the run: commit, dependency versions, oracle
versions, the profile measured, the corpus manifest, both lanes and the parity
verdict, in one file. Prose in three documents drifted apart once — one said
`12 same / 2 better` where another said `13 same / 1 better` — and prose cannot
be diffed.
