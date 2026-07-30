# exactdoc — roadmap: what is done, what is left, how far

**Updated 2026-07-30.** STATUS.md is the authority on measured numbers; this
file is the authority on *sequence and distance*. If they disagree, STATUS wins
on numbers and this file gets corrected.

---

## The short answer

**Every code path can now run without PyMuPDF — the shipped default still uses it,
and the parity gate is red.** The AGPL was the one thing standing between this
project and being usable by anyone who cannot accept it. As of 2026-07-30 the
parity gate **fails on 2 unwaived regressions**, alongside 4 documents
**provisionally waived** against a single cause proven unreachable from a
permissive parser and bounded by numeric floors.

Both numbers went the wrong way for the right reason. The comparison used to stop
at the first dimension outside its margin — so an improvement suppressed every
regression after it — and it never compared vertical drift at all. Fixing that
turned "2 regressions, 13 same, 1 better" into a picture with more in it. Nothing
got worse; the gate got honest. "Provisional" is likewise deliberate: expanding a
waiver from two documents to four is a product decision awaiting ratification, not
a measurement.

`import exactdoc` and a full conversion — including the refinement loop — now work
with PyMuPDF **physically absent**, which was not true a session ago and was the
real content of the word "mechanical" in §3.2. `pymupdf` remains the default
backend and a hard runtime dependency until §3.2b. See §3.2a.

**CI status: these are local commits. GitHub Actions has not run them.** Every
number below was measured on a canonical `ubuntu:24.04` environment that
reproduces the recorded baseline, which is evidence and is not the same thing as
a green check on the branch.

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
| Parity gate (pdfium vs PyMuPDF) | **FAILS: 2 unwaived regressions** — 5 same, 3 better, 2 expected divergences, 4 provisional accepted shortfalls under D2 |
| Started at | 9 regressions, then 8 when first measured on the canonical environment |
| Why it went up, not down | the comparison stopped at the first dimension outside its margin and never looked at vertical drift. `05_memo` and `f1_fpdf_brief` were drifting >1pt while it reported "same" |
| Waived set | grew 2 → 4 when the loop stopped borrowing the incumbent's parser to measure with (§3.2a). **Awaiting ratification**, and the 2 new regressions are deliberately *not* added to it |
| Shipped default backend | still `pymupdf`, still a hard runtime dependency — §3.2b |
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

### 3.2a — The permissive runtime boundary · **DONE, at zero measured cost**

This step was not in the roadmap, and it should have been: it is what "mechanical"
was hiding. `fitz` was on the default runtime path in five stages *past* the
parser, so a wheel installed without PyMuPDF failed while importing the writer,
before any backend selection could happen. Full account and the site-by-site table
in [STATUS.md §7](STATUS.md#7-the-permissive-runtime-boundary).

| | |
|---|---|
| Writer's cost | **zero.** Both lanes re-measured; not one of 224 values moved (2 lanes × 16 documents × 7 metrics, compared exactly, not within tolerance) |
| Refiner's cost | **not zero, and the gate caught it.** Reading both sides through the selected backend cost within-2pt 0.46 → 0.31 and 0.60 → 0.32 on two documents. Fixed by anchoring the loop on *baselines* instead of line-box tops — the one vertical quantity the two parsers agree on exactly. The fix came out of D2's existing measurements, not a new hypothesis |
| Proof | `tests/test_no_pymupdf.py` makes `fitz` *unimportable*, then converts a fixture per capability and runs refinement through the permissive path |
| Lost | `--ladder` needs the `[mupdf]` extra: predicting a re-wrap means shaping text with no source line to measure, and MuPDF's base-14 tables are not vendored here. Off by default, so nothing shipped changes |
| Found on the way | PDFium native handles were never closed (16 documents, 18 pages, 9 text pages left open per parity run); every LibreOffice invocation shared one profile machine-wide |

The refiner line is the part worth remembering. It is the second time a change to
*which parser produces a number* moved fidelity while looking like a refactor. The
first time — within-2pt 0.510 → 0.291 — went unnoticed for a release because the
harness did not measure the dimension it moved. This time the gate written the same
week failed the run and named both documents.

### 3.2b — The default flip and the relicence (`M2.f`) · *one session, now really mechanical*

This is the milestone the whole project has been driving at, and 3.2a is why it is
now a small change.

1. `pypdfium2` becomes the main dependency; `pymupdf` moves to a `[mupdf]`
   extra. **`parse.py` is not deleted** — it becomes the extra's backend.
2. Re-freeze the goldens *from the pdfium backend*, with manifest; archive the
   MuPDF goldens for diffing. Its own commit, per law 14.
3. **Re-record every gate number.** The default parser changes, so the baseline
   describes a different product. This is not a formality: pdfium's mean
   within-2pt is 0.461 against the incumbent's 0.511, and the record has to say
   so rather than inherit numbers from a parser that is no longer the default.
4. `LICENSE` → Apache-2.0, add `NOTICE`, classifier swap, README licence
   section rewritten — including the plain statement that installing the
   `[mupdf]` extra makes the *combination* AGPL-governed for distribution.
   **This one needs a licensing review, not an edit.** Everything above is a
   measurement; this is not, and nothing in the gate can tell you it is right.
5. Version → `0.2.0a1`.

**Done when:** the parity table from the canonical environment is in the PR
description, `git grep -il affero` returns only historical narrative and the
extra's documentation, and the gate is green.

**Acceptance, and it is met — but the number moved, and why it moved matters
more than the number.** 0 regressions, with **four** documents accepted under
STATUS D2 rather than two, all bounded by numeric floors in
`testkit/parity_policy.json` rather than by prose.

The two additions are not new breakage. They are what the old comparison was
hiding: until 3.2a, the candidate lane read the refinement measurement through
*PyMuPDF*, because `refine.py` imported `fitz` directly regardless of which
backend had parsed. So "2 regressions" described a configuration nobody could
install — pdfium parsing, MuPDF measuring. With the loop reading through the
backend that parsed, `03_tech_report_code` and `r1_reportlab_report` join the
accepted set, and the cause is the same proven-unreachable one: all four are
core-14 documents, where PDFium substitutes a generic ascent for the real font's,
and every document that embeds its fonts is untouched.

**The honest reading is that the parity gate got harder, not that the backend got
worse.** A gate that lets the candidate borrow the incumbent's parser halfway
through the pipeline is measuring the wrong thing, and this is the second time that
shape of error has been found here — the first was a harness that omitted the
dimension a swap moved.

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
