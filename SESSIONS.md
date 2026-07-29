# Sessions

One entry per working session, written **before** the work starts (protocol §12.1
of the execution plan): goal, gate-before numbers, hypothesis → experiment →
expected movement, and the files the session intends to touch. Results are
appended to the same entry afterwards, including the ones that failed.

The point is not bookkeeping. This project has twice produced a confident wrong
answer that survived because nobody had written down what they expected to see
before they saw it.

---

## 2026-07-29 · M0 — identity and truth reset

**Goal.** Make the repository's claims match its own measurements, and reset the
version to something that does not promise more than the evidence supports.

**Gate before.** Not applicable — this session changes no code that any gate
measures. Recorded instead: the environment this session established, so later
sessions can tell whether a number moved because of a change or because of the
machine.

| | |
|---|---|
| Platform | Windows 11, Python 3.13.12, uv 0.6.0 |
| Backend deps | pymupdf 1.28.0, pypdfium2 5.12.1 |
| Oracles | LibreOffice (`C:\Program Files\LibreOffice`), Chrome (system) |
| Corpus generated | 15/16 — `l1_word_native` failed (see below) |

**Hypothesis → experiment → expected movement.** None. This is a documentation
and metadata session; the expected movement of every measured number is *zero*.
If any gate number moves, something was edited that should not have been.

**Files intended.** `pyproject.toml`, `README.md`, `STATUS.md`, `FINDINGS.md`
(banner only), `SESSIONS.md` (new).

**Outside the M0 allowlist, with justification (protocol §12.7):** `.gitignore` —
the execution plan and advisory notes sit untracked in the repo root and are
private working documents; one ignore line prevents a `git add -A` from
publishing them, which is the same class of accident the credentials patterns
already guard against.

**Result.**

- `pyproject.toml`: `0.2.0` → `0.1.0a1`, `Development Status :: 4 - Beta` →
  `3 - Alpha`. Licence fields unchanged (AGPL is still true today).
- `README.md`: rewritten against STATUS.md. Every number in the claims ledger
  (plan §16) resolved — see the table in this entry.
- `FINDINGS.md`: one banner line clarifying that "v1.1" is a pre-release
  internal label, no other change (the file is frozen).
- `STATUS.md`: two inline notes where a figure predates the 16-document corpus
  and was being read as current (D7's LibreOffice column, D9's denominator).

Claims resolved:

| Claim (before) | After | Source of truth |
|---|---|---|
| gate 15/18 | 13/16 refine lane, 12/16 no-refine | STATUS §1 |
| page count 17/18 | 15/16 refine, 13/16 no-refine | STATUS §1 |
| within2pt 40.4% | 51.0% refine, 36.1% no-refine | STATUS §1 |
| median drift 1.02pt | 0.69pt refine, 2.79pt no-refine | STATUS §1 |
| live text 96.9% | 96.5% | STATUS §1 |
| SSIM 0.809 mean | removed — an 18-document figure, and never the headline | STATUS §4.5 |
| 18 documents / five dialects | 16 documents / four dialects in the corpus | corpus contents, verified |
| pdfium "9 regressions" | 7 | STATUS D2 |
| `runall.py testkit/adv my_samples` | `runall.py testkit/adv corpus/pdfs` | `my_samples` is not in the repo |
| holdout | stated in the same table as the corpus numbers | STATUS §1 |

**Acceptance (plan §7), each box with the evidence beside it.**

- [x] `pyproject.toml` shows only the new values — `version = "0.1.0a1"`,
      `Development Status :: 3 - Alpha`; no `0.2.0`, no `Beta`.
      `uv run python -c "importlib.metadata.version('exactdoc')"` → `0.1.0a1`.
- [x] No numeric claim in README contradicts STATUS §1–§2 — the ten ledger rows
      above are each resolved; a grep for the retired figures
      (`15/18|17/18|18 documents|9 regressions|0.809|40.4|1.02pt|my_samples`)
      returns nothing.
- [x] README shows corpus AND holdout numbers in the same top table.
- [x] Tag `v0.1.0a1` exists on a docs/metadata-only commit (`95fcb9d`).
- [x] Every command quoted in the README runs. Verified:
      `uv run exactdoc <pdf>` → wrote a 37KB DOCX; corpus generators and
      `golden_ir.py verify` → 7/7 both run here; the two harness commands carry
      their prerequisites (`[test]` extra, LibreOffice, Chrome) in the sentence
      that introduces them.

**Defect found while setting up (deferred to M1, not fixed here).**
`gen_corpus.py`'s LibreOffice document (`l1_word_native`) is generated with
`-env:UserInstallation=file:///` + a **relative** path, which LibreOffice
resolves against the filesystem root. It exits 1 and writes nothing, and the
function returns `None` without printing anything — so the corpus silently
comes back 15 documents instead of 16 and every downstream number is computed
over a different corpus than the one recorded. `harness.py` does not have this
bug (it builds the profile path from `tempfile.gettempdir()`, absolute).
This is exactly the M1 failure mode: a gate that quietly measures something
else. Fixed in the M1 entry.

---

## 2026-07-29 · M1 — make the measurement machinery survive a fresh clone

**Goal.** A fresh clone on a clean machine can run the gate, and a missing
oracle degrades into a printed skip list instead of a traceback or a silently
smaller corpus.

**Gate before** (this machine, Windows, PyMuPDF default — the environment the
goldens were frozen on):

| Measurement | Result |
|---|---|
| `golden_ir.py verify` | **7/7** |
| Corpus generated | **15/16** — `l1_word_native` missing, silently |
| `runall.py` lanes | not yet run here |
| `backend_parity.py --refine 3` | not yet run here |

**Hypotheses → experiments → expected movement.**

1. *The l1 gap is the relative `-env:UserInstallation` URL, not a broken
   LibreOffice.* Experiment: run the same soffice command with an absolute
   profile URL. Expected: `_l1.pdf` appears. **Already confirmed** during M0
   setup — the plain invocation wrote a 66KB PDF; the relative one exits 1.
   Expected movement after the fix: corpus 15 → 16 documents. No fidelity
   number should move for the other 15.
2. *The goldens are environment-pinned in practice but not in name.* Experiment:
   freeze on this Windows machine (already done historically → 7/7 here) and
   verify inside an `ubuntu:24.04` container provisioned exactly like
   `gate.yml`. Expected: fewer than 7/7 on Linux, on documents whose *producer*
   is deterministic — i.e. drift attributable to the environment, not the
   parser. If Linux reproduces 7/7, the plan's §3 finding does not hold here and
   the manifest is a precaution rather than a fix; either way the manifest gets
   written, and which it is gets recorded.
3. *`corpus/make_corpus.py` still carries the `â€¢` mojibake (FINDINGS §2.7).*
   Experiment: read the bytes. **Falsified** — the bullets are `E2 80 A2`,
   correct UTF-8. No change needed, and no golden churn incurred for one.

**Verification environment.** Docker is available on this machine, so the
"clean container" acceptance criterion is executed literally, in
`ubuntu:24.04` — the same image family `gate.yml` runs on — rather than
deferred to a CI run nobody can see yet. That container is also the canonical
environment for anything the plan says must be frozen or baselined on Linux.

**Files intended.** `testkit/gen_corpus.py`, `testkit/golden_ir.py`,
`testkit/README.md`, `testkit/golden/*` (only in a separate, justified commit),
`scripts/bootstrap.sh` (new), `.github/workflows/gate.yml`, `README.md`,
`STATUS.md`. **Forbidden this milestone:** anything under `exactdoc/`.

### Mid-milestone addition: `harness.py` (a metric, not a threshold)

Running the two lanes on Linux produced **12/16** where Windows records 13/16.
The extra failure is `c4_i18n`, on `doc_recall` 0.8298 / `word_recall` 0.8298.
Chasing it produced one falsified hypothesis and one measured cause.

*Hypothesis A (falsified).* The container lacks CJK fonts, so the corpus
document or the oracle's render loses glyphs. Experiment: count characters per
script in the source and in the render-back; then install `fonts-noto-cjk` and
re-run. Result: **the source PDFs are character-identical between Windows and
Linux** (82 ideographs / 37 Hangul / 33 Kana / 88 Arabic / 71 Hebrew on both),
**the render-back carries every one of them**, and installing the fonts moved
`doc_recall` by exactly 0.0000. Not fonts.

*Hypothesis B (measured, confirmed).* The metric cannot see the text it is
counting. `page_words` tokenises with PyMuPDF's `get_text("words")`, which
splits on whitespace — and Chinese, Japanese and Korean do not use any. A
"word" is therefore an entire rendered line, up to 32 characters; LibreOffice
re-wraps that line one character differently and the token no longer matches,
though every character is present. Evidence: of 94 source tokens, 16 go
unmatched, and **all 16 are Hangul (11), CJK (4) or Kana (1)** — zero Latin,
zero Arabic, zero Hebrew. Mean unmatched token length 9.3 characters against
4.4 for matched ones.

So the gate fails a correct conversion, for a reason that depends on which
font the renderer wrapped with — which is why Windows passes and Linux does
not. That is not a threshold to tune; it is a measurement that is wrong.

*Change.* Tokenise scriptio-continua runs (CJK ideographs, Kana, Hangul) per
character in `harness.page_words`, with the bbox divided across them. Scripts
that do use spaces are untouched.

*Expected movement, written before running.* `c4_i18n` `doc_recall` and
`word_recall` 0.83 → ≈1.00, and the document passes the gate: refine lane
12/16 → 13/16 on Linux, matching Windows. `within2pt` for `c4_i18n` will also
move, because the matched population changes. **No other corpus document may
move at all** — none of the other 15 contains a CJK, Kana or Hangul character.
A change anywhere else means this fix is wrong, not that it is generous.

*Result.* Held exactly. Re-scoring the existing renders — same DOCX, same
render-back on disk, so only the metric changed — moved `c4_i18n` `doc_recall`
0.8298 → 1.0000 and `within2pt` 0.3333 → 0.4160, and left all 15 other
documents identical to four decimal places on every metric. `1 document(s)
moved`. The refine lane went 12/16 → 13/16.

### Second mid-milestone finding: the gate could never pass

Dropping `continue-on-error` was blocked by something other than calibration.
`runall.py` exits 1 if *any* document misses a threshold, and three never have
(`c3_tables` D3, `c5_graphics`, `04_exec_brief` live-text 0.941 vs 0.95). So the
gate had returned non-zero on every run ever made, on both platforms — the CI
flag was not hiding an uncalibrated threshold, it was hiding a check that could
not pass. Fixed by gating on the delta against a recorded per-lane baseline
(`testkit/gate_baseline.json`), including treating a *stale* record — a document
that passes while the record says it fails — as a failure, since a record that
over-permits silently re-admits the regression it exists to catch.

**Acceptance (plan §8), each box with the evidence beside it.**

- [x] Clean container: provision → generate → exit 0. Executed literally, in
      `ubuntu:24.04` populated from `git archive HEAD` (a fresh clone with no
      Python at all): `bash scripts/bootstrap.sh` → 6/6 capabilities OK;
      `gen_corpus.py` → **11 PDFs**, `make_corpus.py` → 5, i.e. the full
      16-document corpus, page counts identical to Windows.
- [x] Without the oracles it yields the subset plus a printed skip list and
      never a traceback — `tests/test_corpus_degradation.py`, both directions
      (bare machine exits 0 having still produced the two pure-Python
      documents; a `CHROME` pointing at nothing exits 1).
- [x] `golden_ir.py verify` → **7/7** on the CI environment, against re-frozen
      manifest-carrying goldens. Also 7/7 on Windows, with the platform
      difference named rather than presented as parser drift.
- [x] CI runs golden verify + two-lane runall + parity, thresholds pinned, no
      `continue-on-error` on the lanes. **Confirmed on a real runner** —
      [run 30455217670](https://github.com/ebt55/exactdoc/actions/runs/30455217670),
      green in 3m21s, every step passing:

          Golden IR                7/7 documents match
          lane norefine            12/16 pass · 12 known, 0 new, 0 stale
          lane refine              13/16 pass ·  9 known, 0 new, 0 stale
          lane comparison          norefine 13/16 0.366 0.9652 2.20
                                   refine   15/16 0.529 0.9652 0.68
          backend parity           8 regressions, 7 same, 1 better

      The baseline recorded in a local container transferred to GitHub's runner
      with **0 new and 0 stale in both lanes**, and parity reproduced its count
      exactly. That is the regression gate proving portable across two
      independent Linux environments, which is the property it needed to have.
- [x] Numbers recorded in STATUS.md §1 as the Linux/CI baseline, beside the
      Windows column.
- [x] A deliberately broken environment still produces a passing
      corpus-generation run with an explicit skip report.
- [x] `pypdfium2` declared in `testkit/README.md`'s quick start; `SOFFICE` /
      `CHROME` documented in a table.
- [x] Mojibake (plan §8.6): **not present** — bullets are `E2 80 A2`. No golden
      churn spent on a defect that had already been fixed.

**Closed later the same day.** This box was first recorded as unverified,
because "CI is green" is a claim only a CI run can make and `gh` was
unauthenticated at the time. The owner authenticated it; the branch was pushed,
PR #1 opened, and the run came back green. The box above carries its output.

---

## 2026-07-29 · M2 — finish the licence swap

**Goal.** `backend_parity.py --refine 3` reports **0 regressions**, so the
default parser can become pypdfium2 and the licence can become Apache-2.0.

**Gate before.** Measured on the canonical Linux container, this session:

| Measurement | Result |
|---|---|
| `backend_parity.py --refine 3` | *(running — recorded below)* |
| `golden_ir.py verify` | 7/7 |
| Gate lanes | 12/16 no-refine, 13/16 refine; 0 new, 0 stale |

**The reframe this milestone starts from.** The parity gate is the contract;
the golden IR is a microscope. The two definitions of "correct" have already
diverged — the backend deliberately refuses to reproduce three PyMuPDF
behaviours because they are bugs (RTL visual order, dropped gradients, Calibri's
serif flag), and M1 measured a fourth reason: **MuPDF's grouping changes between
its own point releases** (1.26 puts `02_research_paper` p2 in 4 blocks, 1.28 in
7). Converging bit-for-bit on a target that moves with the dependency version is
not a finish line. Not worse on the rendered output is.

**Working loops.** Inner: golden digest diff + `backend_geom.py`, seconds, no
oracle. Middle: `backend_parity.py --only <doc>`, one document in ~10s — to be
added first, since without it every hypothesis costs a full 16-document run.
Outer: the full parity run, which is the only thing that decides anything.

**Order.** (1) `--only`, (2) the 9.B instrument `backend_spans.py` and the
diagnosis of the code-heavy pair, because it is the part the plan marks
*unattributed* and guessing at it is how this project has been wrong before,
(3) 9.A grouping convergence document by document, worst first, (4) 9.C
superscript, (5) 9.D flip and relicense.

**Files intended.** `exactdoc/parse_pdfium.py`, `exactdoc/backend.py`,
`testkit/*`, and at 9.D `pyproject.toml`, `LICENSE`/`NOTICE`, docs.
**Forbidden:** `exactdoc/parse.py`, `infer.py`, `docxout.py`, `dialect.py` — if a
parity failure traces into the shared pipeline, stop and escalate rather than
tune the shared code to flatter one backend.

**Gate before (measured).** `backend_parity.py --refine 3` on the container:
**8 regressions, 7 same, 1 better**. One more than the plan's 7 —
`02_research_paper` (w 0.76 → 0.57) is a regression here and was not in the
audit's list. The set: `01_whitepaper_market`, `02_research_paper`,
`03_tech_report_code`, `05_memo`, `c1_whitepaper`, `c6_long`, `c7_code`,
`c8_toc_links`. `04_exec_brief` is *better* under pdfium (0.22 → 0.34).

### 9.B — the code-heavy pair, attributed

Built `testkit/backend_spans.py` (new): pairs lines across backends by baseline
and x, then diffs span structure, text, injected space runs, mono flags and
style keys. Run on the two failing documents with two passing ones as controls.

**All four of the plan's candidate hypotheses are wrong.** Measured:

| | c7_code | 03_tech | f1 (control) | r1 (control) |
|---|---|---|---|---|
| space-run diff | **0%** | **0%** | 0% | 0% |
| text diff | **0%** | 36% | 40% | 42% |
| lines unmatched | **16/26** | 9/73 | 0/20 | 0/36 |

Multi-space synthesis (§9.B.1) is not it — space runs agree on every line of
every document. Different text (§9.B.1's consequence) is not it either: the two
*passing* controls have 40% and 42% text differences, more than the failing
`c7_code`, which has none. `LINE_SPLIT_EM` (§9.B.2) is not splitting anything,
and `superscript` (§9.B.4) is unrelated.

What it is: **PDFium does not report leading indentation, and PyMuPDF
synthesises it.** Verified against the raw character stream rather than by
reading grouping code — for `    def __init__(...)`, PDFium's first character is
`d` at x=93.17 with no space anywhere before it, while PyMuPDF reports the same
line beginning at x=72.25 with four leading spaces. PDFium *does* synthesise
spaces between characters (there is a gap to measure); at the start of a line
there is nothing to the left of the first glyph, so the indent is simply
absent. The line box then starts at first ink, the paragraph is written at the
wrong x, and every glyph on the line is displaced by the indent width.

*Fixes made, each measured:*

1. `_reconstruct_indents` — rebuild leading indentation for monospace runs
   against the leftmost line of the run.
2. Excluding lines that share a baseline from those runs. Necessary: a
   configuration table whose cells are monospace puts three on one baseline at
   x=61/153/223, and read as a listing they were "indented" by 18 and 32 spaces.
   Measured cost of the bug: `03_tech` 0.23 → 0.03.
3. `local_pitch` — the block splitter's gap threshold was multiplying a
   **page-wide** median pitch. Page 1 of `03_tech` has fourteen distinct
   pitches and a median of 22.0pt (the table's rows outnumber everything), so
   the threshold was 35.2pt and the 23.0pt blank lines inside a code listing —
   an unmistakable double of the listing's own 11.5pt — were swallowed, fusing
   three PyMuPDF blocks into one. `BLOCK_GAP_FACTOR` is untouched: the factor
   was never wrong, the statistic it multiplied was.

*Result, isolated by an A/B on the same corpus and renders:*

| document | indent OFF | indent ON | pymupdf |
|---|---|---|---|
| `c7_code` | 0.16 | **0.59** | 0.91 |
| `03_tech_report_code` | **0.23** | 0.02 | 0.46 |

So the indent reconstruction is worth +0.43 on one document and −0.21 on the
other, and `local_pitch` alone is score-neutral on both (it reproduces the
0.16/0.23 baseline exactly). Both documents remain regressions either way, so
the *verdict count* is unmoved at this point.

### `local_pitch` reverted — the subset run was hiding its real cost

A two-document run cannot decide a page-wide change, so both variants were then
run over the whole corpus. That is what caught it:

| document | baseline | local pitch | local pitch + indent |
|---|---|---|---|
| `02_research_paper` | 0.57 | **0.02** | **0.02** |
| `c5_graphics` (expected-div) | 0.24 | 0.66 | 0.66 |
| `03_tech_report_code` | 0.23 | 0.23 | 0.02 |
| `c7_code` | 0.16 | 0.16 | **0.59** |
| the other twelve | — | unchanged | unchanged |

`local_pitch` costs `02_research_paper` **0.55** of within-2pt and buys nothing
on the count: 8 regressions before, 8 after, 8 with both. A local window inside
a dense two-column body finds a pitch small enough to cut paragraphs in half —
the mirror image of the problem it fixed on the code listing. **Reverted**, with
the reasoning left in the code where the next person will look for it.

That is the second failed attempt at moving `03_tech_report_code`, so by §12.5
this stops here rather than trying a third estimator. What is *kept* is the
attribution and the instrument: `backend_spans.py`, `--only`, and a named,
measured cause for a defect the register had carried as unexplained.

### Owner decision: land the indent fix, and trace 03 downstream

Escalated per §12.8 and the owner chose to land it and to lift the
forbidden-file rule for the trace. The trace was read-only in the end — it never
needed to edit the shared pipeline, because it found the cause in the parser.

**Where 03 loses it.** Rendered x of the same source line, against a source x of
84.40:

| | `policy=Policy...` | `return downstream...` |
|---|---|---|
| PyMuPDF render | 90.25 (+5.9) | 90.25 (+5.9) |
| PDFium render | 199.70 (+115) | 281.30 (+197) |

Two lines with the *same* source x landing 80pt apart is not a drift, it is a
structural failure: the code listing is being laid out as flowing prose. Reading
the layout confirmed it — PyMuPDF builds that region as

    role=code  rows=1  col_widths=[504.0]
    para leading=11.50 line_breaks=True vis_lines=10 runs=15

and PDFium built it as `role=table`, two columns of 3.0pt and 501.0pt, three
paragraphs with `line_breaks=False`, so `detector = Detector(` and the four
lines beneath it were concatenated into one line of prose.

**Why: the two backends disagree about what a stroked path's bbox means.**
`FPDFPageObj_GetBounds` returns the *ink envelope* — a stroked path inflated by
its line width in every direction — while PyMuPDF returns the geometric path:

| path | PyMuPDF | PDFium |
|---|---|---|
| box border, 0.75pt | `x=54.00..54.00` (w 0.00) | `x=53.25..54.75` (w **1.50**) |
| callout accent, 3pt | `x=57.00..57.00` (w 0.00) | `x=54.00..60.00` (w **6.00**) |

`infer.py`'s table detector reads that 1.5pt bar as a column boundary, which is
where the phantom 3pt first column came from. `_classify` already worked around
this for *orientation* by reading the path points instead of the bounds; taking
the bbox from the same place makes the workaround whole, and it is confined to
`parse_pdfium.py` — the shared pipeline needed no change at all.

With the bbox taken from the points, PDFium builds the region **identically** to
PyMuPDF: `role=code`, one 504.0pt column, `line_breaks=True`, 10 visual lines,
15 runs.

**And the rendered score still did not follow.** `03_tech` 0.02 → 0.03,
`c7_code` **0.59 → 0.30** with `word_recall` slipping 1.00 → 0.95. On the full
corpus — because a two-document subset had already misled this session once —
it is worse still:

    8 regressions -> 9

with `01_whitepaper_market` pages 3/3 → 3/4 (w 0.31 → 0.01), `02_research_paper`
2/2 → 2/3, `c5_graphics` 1/1 → 1/2, and `r1_reportlab_report` newly a regression
at 0.57 → 0.38. **Reverted.**

The reason is worth keeping. A stroked box's *ink envelope* contains its text,
while the geometric path is the centreline — so making the bbox faithful makes
containment tests fail at the edges and box detection starts losing boxes
(`c7_code` drops from two `TableEl`s to one). The convention is not
independently right or wrong; it has to match whatever the containment tests
were tuned against, and they were tuned against PyMuPDF's.

That is the third time this session that a demonstrably more faithful IR scored
*worse*, which is a finding about the pipeline rather than about the parser, and
it is the strongest evidence yet for the plan's RC1: the downstream is tuned to
PyMuPDF's *shape*, including the parts of that shape that are arbitrary. Two
consequences for whoever picks this up:

1. **The remaining regressions are unlikely to fall one parser fix at a time.**
   Three separate faithfulness improvements each cost more than they paid.
   `exp_regroup.py` already showed grouping fully recovers `c6_long` (0.23 →
   0.73) and `c8_toc_links` (0.63 → 1.00) — those two are the honest next
   targets, because there the evidence says the downstream *agrees* with the
   more faithful answer.
2. **A containment/tolerance audit of `infer.py` is the real unlock**, and it is
   a shared-pipeline change that must be measured on *both* backends. The bar:
   pymupdf's numbers may not move at all.

**Gate after this session:** `backend_parity.py --refine 3` → **8 regressions,
7 same, 1 better** — unchanged in count from the session's start, with
`c7_code` 0.16 → 0.59 and `03_tech_report_code` 0.23 → 0.02 inside it.

---

## 2026-07-29 · M2.b — page-space path geometry (plan v2)

**Correction I am acting on.** The stroke-bbox experiment above was confounded
and my conclusion from it was wrong. I derived path bboxes from
`FPDFPath_GetPathSegment` points, which PDFium reports in **object space**,
without applying `FPDFPageObj_GetMatrix`. So the change did not give the corpus
PyMuPDF's convention; it gave every transformed path scrambled coordinates.
That, not "faithfulness is punished", is why pagination broke on exactly the
documents it broke on — and the inference I drew from it (that `infer.py`'s
tolerances are the blocker) has **no valid evidence behind it** and is
withdrawn. `infer.py` stays closed; M2.d is the only way in.

The tell I missed: the two example paths in my own probe table were
identity-matrix paths. A microscope aimed at two objects cannot see a systematic
transform. Law 15 exists now because of this, and law 16 because the same shape
of error nearly landed twice.

**Goal.** Put path geometry in page space throughout `parse_pdfium.py`: matrix
first, then centreline bboxes from the transformed points, then `_classify`,
`_rect_pts` and the frame-edge decomposition all reading the same space.

**Gate before** (canonical environment, unchanged from the last session):

| Measurement | Value |
|---|---|
| `backend_parity.py --refine 3` | **8 regressions, 7 same, 1 better** |
| `golden_ir.py verify` | 7/7 |
| Gate lanes | 12/16 no-refine, 13/16 refine; 0 new, 0 stale |
| `03_tech_report_code` | w 0.02 (pymupdf 0.46) |
| `c7_code` | w 0.59 (pymupdf 0.91) |

**Hypotheses → experiments → expected movement.** Written before running, and
deliberately more falsifiable than "may move":

- **H1 (the probe, and the gate on everything else).** On Chromium/Skia
  documents ≥90% of path objects carry a non-identity matrix, and
  matrix-transformed points reproduce `GetBounds` on ~100% of paths once the
  stroke envelope is accounted for, while raw points reproduce it only on the
  identity ones. There is a strong prior: `_page_chars` already compensates for
  Chromium's 0.75 text matrix, so the same 0.75 should appear on paths.
  **If H1 fails, the scrutiny's finding is wrong and I stop and report rather
  than "fix" anything.**
- **H2 (structural, 03_tech).** With page-space centreline bboxes the 0.75pt
  box border reports width ≤ 0.1pt, the phantom 3.0pt table column disappears,
  and the region classifies `role=code` with `rows=1`, one ~504pt column,
  `line_breaks=True` — matching PyMuPDF's layout dump.
- **H3 (03_tech score).** ≥ 0.23, i.e. it recovers at least the value it had
  before the indent fix, because the phantom column was its attributed cause.
  I expect better than that — 0.30–0.46 — since the indent fix is still in and
  the two were fighting each other.
- **H4 (c7_code).** Holds at ≥ 0.55. Its box is Chromium-produced, so all four
  of its paths currently run mixed-space classification; I do not predict a
  direction for it beyond "does not regress".
- **H5 (the requirement).** Count ≤ 8 and **no new regression documents**.
  Chromium documents c1/c6/c8 run 100% mixed-space classification today, so
  they may move either way; movement in either direction is informative, a new
  regression is a failure.
- **H6 (invariance).** Golden IR stays 7/7 and the pymupdf column of the parity
  table is unchanged — trivially, since no shared code is touched, but checked
  rather than assumed.

**Files intended.** `testkit/backend_paths.py` (new probe, committed first and
alone, per M2.b's build guideline and law 15), then
`exactdoc/parse_pdfium.py`. **Forbidden:** `exactdoc/parse.py`, `infer.py`,
`docxout.py`, `dialect.py`. Baselines (`gate_baseline.json`, `testkit/golden/*`)
are not expected to change at all; if one must, it is its own commit (law 14).

### H1 — confirmed, and reproduced independently

`testkit/backend_paths.py` compares, per path object, the raw-points bbox, the
matrix-transformed-points bbox and `FPDFPageObj_GetBounds`. A geometric bbox
"reconstructs" GetBounds when it lands within 0.6pt after the stroke envelope is
added back.

| document | paths | non-identity matrix | raw reconstruct | worst raw miss | matrix reconstruct |
|---|---|---|---|---|---|
| `01_whitepaper_market` | 41 | 34 | 7 | 588.00pt | **41** |
| `02_research_paper` | 13 | 13 | 0 | 420.00pt | **13** |
| `03_tech_report_code` | 46 | 44 | 2 | 692.00pt | **46** |
| `04_exec_brief` | 18 | 16 | 2 | 590.00pt | 17 (0.60pt) |
| `05_memo` | 1 | 1 | 0 | 623.20pt | **1** |
| `c1_whitepaper` | 43 | **43** | 0 | 758.16pt | **43** |
| `c2_paper2col` | 5 | 5 | 0 | 578.00pt | **5** |
| `c3_tables` | 342 | **342** | 0 | 1680.00pt | **342** |
| `c5_graphics` | 9 | **9** | 0 | 646.50pt | **9** |
| `c6_long` | 50 | **50** | 0 | **5438.00pt** | **50** |
| `c7_code` | 4 | **4** | 0 | 382.00pt | **4** |
| `c8_toc_links` | 3 | **3** | 0 | 226.25pt | **3** |
| `f1_fpdf_brief` | 12 | 0 | **12** | 0.00pt | **12** |
| `l1_word_native` | 11 | 0 | **11** | 0.00pt | **11** |
| `r1_reportlab_report` | 14 | 14 | 0 | 377.40pt | **14** |
| **corpus** | **612** | **578** | **34** | — | **611** |

The correspondence is exact: raw points reconstruct GetBounds on **34** paths,
and there are **34** identity-matrix paths in the corpus. Every Chromium
document is 100% non-identity. Worst raw miss is 5438pt on a Letter page.

These numbers reproduce plan v2 §4's table cell for cell on every column it
reports (`01_whitepaper` 34/41 and 7; `03_tech` 44/46 and 2; `c1` 43/43 and 0;
`c5` 9/9 and 0; `c7` 4/4 and 0) from an independently written probe. The
scrutiny's finding is confirmed, not taken on trust — **H1 holds and the work
proceeds.**

One path, in `04_exec_brief`, misses by 0.60pt after transformation; the other
611 land within 0.12pt and most at 0.00. Bezier control points hull wider than
the drawn curve, which is why the change below keeps `GetBounds` for curves.

**A probe bug found and fixed before the table was trusted.** The first run
reported a worst miss of exactly 1.00pt on hundreds of paths — a suspiciously
round constant. Cause: PDFium reports a stroke *width* of 1.0 on fill-only
objects, and the probe was inflating every filled rectangle by it. The envelope
is now added only when the object is genuinely stroked (draw mode + non-zero
stroke alpha), with the width scaled by the matrix like everything else. Worth
recording because it is the same class of error as the one being corrected:
a number read from this API means nothing until you know what it is measured
in and when it applies.

### The change, and its DrawCmd-level diff

`_page_paths` now applies `FPDFPageObj_GetMatrix` to every segment point before
the y-flip, derives the path bbox from those transformed points (keeping
`GetBounds` for curves, whose control points hull wider than the drawn curve,
and for paths with no points), and scales the stroke width by the matrix too.
`_classify`, `_rect_pts` and the frame-edge decomposition consume the same
points, so the mixed-space logic is gone rather than worked around.

Before/after taken from a **git worktree of the pre-change commit**, so both
sides are real code reading byte-identical PDFs:

| document | draws | shape changes | bboxes moved | worst | stroke there |
|---|---|---|---|---|---|
| `01_whitepaper_market` | 41→41 | none | 25 | 3.00pt | 3.00 |
| `02_research_paper` | 13→13 | none | 9 | 0.90pt | 0.90 |
| `03_tech_report_code` | 46→46 | none | 35 | 3.00pt | 3.00 |
| `04_exec_brief` | 18→18 | none | 5 | 3.50pt | 3.50 |
| `05_memo` | 1→1 | none | 1 | 0.80pt | 0.80 |
| `c1_whitepaper` | 43→43 | none | 0 | — | — |
| `c2_paper2col` | 5→5 | none | 0 | — | — |
| `c3_tables` | 342→342 | none | 0 | — | — |
| `c5_graphics` | 9→9 | none | 2 | 0.75pt | 1.00 |
| `c6_long` | 50→50 | none | 0 | — | — |
| `c7_code` | 4→4 | none | 2 | 0.76pt | 1.00 |
| `c8_toc_links` | 3→3 | none | 0 | — | — |
| `f1_fpdf_brief` | 12→12 | none | 12 | 0.57pt | 0.57 |
| `l1_word_native` | 10→10 | none | 10 | 1.00pt | 1.00 |
| `r1_reportlab_report` | 14→14 | none | 10 | 0.40pt | 0.40 |
| **total** | **611→611** | **none** | **111** | | |

**No path changed shape or disappeared**, and every moved bbox shrank by at most
its own stroke width — which is exactly what removing an ink envelope should
look like. One exception, checked rather than waved through: a `complex` path in
`04_exec_brief` moved 2.60pt against a 2.00pt stroke. It is the line chart's
series polyline, and its new bbox (`x=100.0..470.0`) lands precisely on the
data-marker centres (markers at 97.4..102.6 → centre 100.0; 467.4..472.6 →
centre 470.0). The excess over half the stroke width is the **miter join** at
the sharp vertices, which extends further than the stroke itself. Explained.

The Chromium documents move zero bboxes because Chromium draws its borders as
*filled* rectangles, where the envelope and the path coincide. Their paths were
still being classified in the wrong space, which is what the change fixes for
them.

### H2 — confirmed, exactly

`03_tech_report_code`'s border geometry is now identical to PyMuPDF's, coordinate
for coordinate:

```
PyMuPDF   vline x=54.00..54.00  y=354.70..485.70  w=0.00  lw=0.75
PDFium    vline x=54.00..54.00  y=354.70..485.70  w=0.00  lw=0.75
PyMuPDF   vline x=57.00..57.00  y=493.70..538.70  w=0.00  lw=3.00
PDFium    vline x=57.00..57.00  y=493.70..538.70  w=0.00  lw=3.00
```

and the code box classifies the same way, with the phantom 3.0pt column gone:

```
PyMuPDF   role=code rows=1 col_widths=[504.0]  leading=11.50 line_breaks=True vis_lines=10 runs=15
PDFium    role=code rows=1 col_widths=[504.0]  leading=11.50 line_breaks=True vis_lines=10 runs=15
```

**H6 — confirmed.** Golden IR 7/7, purity 16/16; no shared code was touched.

### The full gate, and the hypothesis I got wrong

`backend_parity.py --refine 3`, canonical environment: **8 regressions, 8 same,
0 better** — count held, no new regression documents.

| document | before | after | Δ |
|---|---|---|---|
| `c7_code` | 0.59 | **0.76** | **+0.17** |
| `03_tech_report_code` | 0.02 | 0.05 | +0.03 |
| `04_exec_brief` | 0.34 *(better)* | 0.20 *(same)* | **−0.14** |
| `01_whitepaper_market` | 0.31 | 0.31 | — |
| `02_research_paper` | 0.57 | 0.57 | — |
| `05_memo` | 0.49 | 0.49 | — |
| `c1_whitepaper` | 0.00 | 0.00 | — |
| `c2_paper2col` | 0.21 | 0.21 | — |
| `c3_tables` | 0.00 | 0.00 | — |
| `c5_graphics` | 0.24 | 0.24 | — |
| `c6_long` | 0.21 | 0.21 | — |
| `c8_toc_links` | 0.54 | 0.54 | — |
| `f1_fpdf_brief` | 0.60 | 0.60 | — |
| `l1_word_native` | 0.03 | 0.03 | — |
| `r1_reportlab_report` | 0.57 | 0.57 | — |

**Scorecard against what I wrote before running:**

| | prediction | outcome |
|---|---|---|
| H1 | ≥90% non-identity on Chromium; matrix reconstructs, raw does not | ✅ 100% on every Chromium doc; 611/612 vs 34/612 |
| H2 | border w ≤ 0.1pt, phantom column gone, `role=code` | ✅ exact coordinate match with PyMuPDF |
| H3 | `03_tech` ≥ 0.23, expect 0.30–0.46 | ❌ **0.05** |
| H4 | `c7_code` holds ≥ 0.55 | ✅ 0.76 |
| H5 | count ≤ 8, no new regressions | ✅ 8, none |
| H6 | golden 7/7, pymupdf lane unmoved | ✅ |

**H3 is the one that matters, and it failed.** The phantom column was fixed —
H2 proves it structurally and perfectly, the layout dump is now
indistinguishable from PyMuPDF's — and `03_tech` moved 0.02 → 0.05. So the
phantom column was *a* cause of that document's drop but not the dominant one.
The attribution in the previous session was incomplete, and I should not have
predicted a full recovery from a structural match: **matching the structure of
one region does not bound the error of the page.** Whatever else is wrong with
`03_tech` is still unnamed, and naming it is M2.d's job, not a guess here.

**The trade, stated explicitly (law 17).** `04_exec_brief` loses 0.14 and its
*better* verdict, landing level with PyMuPDF (0.20 against 0.22) instead of
ahead of it (0.34). That document is the line chart, and its series polyline is
exactly the path whose bbox shrank by the miter join. The old number came from
an inflated chart bbox — a figure region larger than the drawing — so the
document was scoring *better* off a geometric error. I do not think a score
earned that way is worth keeping, and it is not a regression either way. Net
across the corpus: +0.17 and +0.03 on two regression documents, −0.14 on a
non-regression one, thirteen documents pinned exactly, and a whole class of
coordinate-space confusion removed from the parser.

---

## 2026-07-29 · M2.c — grouping convergence: `c6_long`, `c8_toc_links`

**Goal.** Both documents leave the regression set. The evidence for picking
these two is `exp_regroup.py`: grafting PyMuPDF's block boundaries onto pdfium's
geometry recovers `c6_long` 0.23→0.73 and `c8_toc_links` 0.63→1.00, so on these
the downstream *agrees* with the more faithful answer — unlike `03_tech`, where
a perfect structural match moved the score by 0.03.

**Gate before** (canonical environment, after M2.b):

| | pdfium | pymupdf | gap |
|---|---|---|---|
| `c6_long` | 0.21 | 0.76 | **0.55** |
| `c8_toc_links` | 0.54 | 1.00 | 0.46 |
| whole gate | 8 regressions, 8 same, 0 better | | |

Worst first, so `c6_long` leads.

**Method, per §9.A — and no hypothesis yet, deliberately.** The rule change is
not allowed to precede the pattern. Step 1 is a per-page block-boundary diff
(which lines each backend starts a block at), step 2 is *naming* what the
disagreement is, step 3 is the rule and its predicted effect on the other 15
documents, written before the gate runs. §9.A also bans tuning a threshold
before plotting the two distributions it separates, and the `local_pitch` dead
end from the previous session is a standing reminder that a block-split
estimator must be robust in both directions.

**Files intended.** A block-diff instrument in `testkit/`, then
`exactdoc/parse_pdfium.py`. **Forbidden:** `parse.py`, `infer.py`, `docxout.py`,
`dialect.py`. Baselines only in their own commit (law 14); full corpus decides
(law 16).

### Step 1 — the pattern, named

A block-boundary diff (pair lines across backends, compare which of them each
backend starts a block at) gives one pattern and only one:

| document | disagreements | direction |
|---|---|---|
| `c6_long` | 72 of 201 lines | **pdfium MERGES where PyMuPDF splits** — 72, and 0 the other way |
| `c8_toc_links` | 3 of 17 lines | same, 3 and 0 |

With the context, the pattern names itself: pdfium fuses *consecutive
paragraphs and list items*.

```
pdfium MERGES  p1 gap=23.2  prev |measure only average relevance will not see it.|
                            this |The mitigation is unglamorous. Chunk boundaries…|
pdfium MERGES  p1 gap=19.5  prev |Point one for section 1.|
                            this |Point two for section 1, somewhat longer so that…|
pdfium MERGES  p1 gap=18.0  prev |1. Motivation|
                            this |2. Architecture|
```

Body pitch on these pages is ~15pt, the boundaries are 18.0–23.2pt, and the
shipped rule allows anything up to `median_pitch × 1.6` ≈ 24pt into the same
block. So the paragraph boundary falls inside the tolerance.

### Step 2 — the distributions, before any threshold is touched (§12.6)

`testkit/block_gaps.py` (new) labels every consecutive pdfium line pair with
PyMuPDF's answer — same block or not — and plots `gap / reference` for three
candidate references.

**Per document, every reference separates perfectly. Corpus-wide, none does**,
because each document's clean split sits at a *different* ratio:

| document | separable on `p20`? | its own cut |
|---|---|---|
| `c6_long` | yes, 0 of 194 wrong | 1.05 |
| `c8_toc_links` | yes, 0 of 16 | 1.05 |
| `f1_fpdf_brief` | yes, 0 of 11 | 1.00 |
| `r1_reportlab_report` | yes, 0 of 23 | 1.00 |
| `l1_word_native` | yes, 0 of 16 | **1.24** |
| **corpus (685 pairs)** | **no** | best fixed 1.11, still 135 wrong |

That is the §12.6 answer in full: the decision is well-posed *locally* and the
global constant is what is wrong. Scoring candidate rules against PyMuPDF's
labels:

| rule | wrong |
|---|---|
| shipped: `gap ≤ median × 1.60` | **355/685 (52%)** |
| `gap ≤ p20 × 1.60` | 278 (41%) |
| `gap ≤ p20 × 1.30` | 178 (26%) |
| **`gap ≤ p20 × 1.15`** | **140 (20%)** |
| `gap ≤ p20 × 1.05` | 154 (22%) |
| adaptive: per-page Otsu cut on the page's own gaps | 322 (47%) |

Two things worth stating plainly. The shipped rule is **wrong more often than
right** on this labelled set. And the *adaptive* estimator — the clever option,
the one I would have reached for after `local_pitch` — is worse than a fixed
factor on a better reference. Measuring it cost minutes; implementing it would
have cost a session.

*(Caveat, stated because the number is startling: this scores the `else`-branch
condition applied uniformly to every consecutive pair, while the shipped
`_build_blocks_one` has other branches in front of it — the same-baseline case,
the size-change split. So 52% overstates the shipped parser's real error rate.
It is a proxy for ranking rules, not a measurement of the parser. The gate is
the measurement.)*

**Why `p20` rather than the median, as an argument and not a fit.** The
reference is supposed to stand for the *intra-paragraph* line pitch. The median
of all gaps includes the boundary gaps themselves, plus table-row pitches, so it
is biased upward by exactly the quantity it is trying to exclude. The 20th
percentile approximates the tightest recurring pitch on the page, which is what
body text sets. The factor 1.15 sits mid-range of the per-document optima
(1.00–1.24) observed above.

### Step 3 — the change, and what I expect of it (written before running)

`_build_blocks_one`: reference becomes the 20th-percentile gap instead of the
median, and `BLOCK_GAP_FACTOR` 1.6 → 1.15.

- **`c6_long`** recovers substantially; `exp_regroup` put full grouping recovery
  at 0.73, so I predict **≥ 0.50** (from 0.21).
- **`c8_toc_links`** predict **≥ 0.80** (from 0.54).
- **`l1_word_native`** is the document I expect to suffer: its own optimum is
  1.24, above the 1.15 being adopted, so it may over-split. It sits at 0.03
  against PyMuPDF's 0.01 and is *same*, so there is room, but if anything turns
  into a new regression I expect it here.
- **Everything else** should hold. This is a global change to every document's
  blocking, so "should" is doing real work in that sentence — the full gate
  decides, and the requirement is unchanged: **count ≤ 8, no new regressions**.

### Result — 8 regressions → 6, and both predictions narrowly missed

Block boundaries first: on both target documents pdfium now agrees with PyMuPDF
on **every single boundary** — `c6_long` 201 of 201 lines, `c8_toc_links` 17 of
17, from 72 and 3 disagreements. Grouping on these two is finished.

`backend_parity.py --refine 3`, canonical environment: **6 regressions, 10 same,
0 better.**

| document | before | after | Δ | verdict |
|---|---|---|---|---|
| `c6_long` | 0.21 | **0.46** | **+0.25** | still regression (pymupdf 0.76) |
| `c8_toc_links` | 0.54 | **0.78** | **+0.24** | still regression (pymupdf 1.00) |
| `01_whitepaper_market` | 0.31 | **0.48** | **+0.17** | still regression |
| `05_memo` | 0.49 | **0.64** | **+0.15** | **left the set** — equals pymupdf exactly |
| `c1_whitepaper` | 0.00 | **0.12** | **+0.12** | **left the set** (pymupdf 0.18) |
| `c7_code` | 0.76 | 0.72 | −0.04 | still regression |
| `c2_paper2col` | 0.21 | 0.20 | −0.01 | same |
| the other 8 | | | — | unchanged |

**Scorecard.**

| | prediction | outcome |
|---|---|---|
| `c6_long` ≥ 0.50 | | ❌ **0.46** — right direction, missed the number |
| `c8_toc_links` ≥ 0.80 | | ❌ **0.78** — same |
| `l1_word_native` is where a new regression would appear | | ❌ unchanged at 0.03 |
| no new regressions, count ≤ 8 | | ✅ **6**, none |
| pymupdf lane unmoved | | ✅ golden 7/7, purity 16/16 |

Three of five predictions wrong, and the milestone still moved further than any
change so far. Worth being precise about what that means: I predicted the two
documents I was *aiming* at and missed both by 0.02–0.04, while the change's
biggest effects landed on `01_whitepaper_market` and the two documents that
actually left the set — **neither of which I predicted at all.** A global
change to blocking does not respect the document you had in mind.

**The trade (law 17).** `c7_code` −0.04 and `c2_paper2col` −0.01. Neither
changes a verdict, and both are inside the parity comparator's 0.08 tolerance
band. `c7_code` remains far above where this session found it (0.16).

**M2.c's own acceptance is not fully met, and I am not going to claim it is.**
It asks that both target documents *leave the regression set*; they did not,
they improved by ~0.25 each and stayed in. But their block boundaries now match
PyMuPDF's exactly, which means **grouping is exhausted as an explanation for
them** — whatever residual `c6_long` and `c8_toc_links` carry is a different
cause, and naming it is M2.d's re-attribution, not a second grouping attempt.
That is also why I am not iterating further here: §12.5 stops a second attempt
on the same metric, and in this case the instrument says there is nothing left
to converge.

---

## 2026-07-29 · M2.d — re-attribution, and the cause behind three failed predictions

**Gate before.** 6 regressions, 10 same, 0 better. Survivors:
`01_whitepaper_market` .48, `02_research_paper` .57, `03_tech_report_code` .05,
`c6_long` .46, `c7_code` .72, `c8_toc_links` .78.

### The measurement that broke the case open

`testkit/residual.py` (new) splits each document's placement error into the part
a second pass could remove — a per-page affine trend in y, a per-page constant
in x — and the part that survives it, then reports the **ceiling**: the
within-2pt a perfect anchoring fix could reach.

| document | backend | median dx raw→resid | median dy raw→resid | within2 → ceiling |
|---|---|---|---|---|
| `c6_long` | pymupdf | 0.11 → 0.15 | 0.65 → 0.21 | 0.758 → 0.935 |
| `c6_long` | **pdfium** | **0.56 → 0.73** | 1.35 → 0.27 | 0.462 → 0.682 |
| `c8_toc_links` | pymupdf | 0.14 → 0.21 | 0.10 → 0.34 | 1.000 → 1.000 |
| `c8_toc_links` | **pdfium** | **0.61 → 0.76** | 0.10 → 0.32 | 0.784 → 0.763 |
| `c7_code` | pymupdf | 0.26 → 0.04 | 0.70 → 0.35 | 0.915 → 0.989 |
| `c7_code` | **pdfium** | **0.55 → 0.26** | 0.70 → 1.01 | 0.722 → 0.477 |

The vertical axis is fine, and on `c6_long` it is *excellent* (1.35 → 0.27, more
systematic than PyMuPDF's own). **Every document's horizontal error is 2–5×
PyMuPDF's, and it does not shrink when a per-page constant is removed.** That is
diffuse sub-point horizontal error — precisely the shape that no structural fix
can touch, and precisely why three of them didn't.

### The structural instruments say there is nothing left to fix

| document | lines | span count diff | text diff | space-run diff | style diff |
|---|---|---|---|---|---|
| `c6_long` | 201/201 | **0%** | **0%** | **0%** | **0%** |
| `c8_toc_links` | 17/17 | **0%** | 12% | 12% | **0%** |
| `c7_code` | 26/26 | 73% | 0% | 0% | 73% |

`c6_long`'s IR is identical to PyMuPDF's on every axis these instruments can
see — lines, spans, text, spaces, styles, and block boundaries (201/201) — and
it scores 0.46 against 0.76. The difference therefore lives *inside the
instruments' tolerances*: sub-point, per-line, horizontal.

### Cause, measured

`_page_chars` takes **y** from `FPDFText_GetLooseCharBox` — the font-metric box
— with a comment in the code explaining that the tight ink box made every line
start below the true ascent. It still takes **x** from `FPDFText_GetCharBox`,
the tight ink box. The bug was half-fixed.

PyMuPDF reports every line of `c6_long` starting at exactly x=61.500, the pen
origin. pdfium reports the ink left edge, which moves with whichever glyph
happens to start the line:

| first char | PyMuPDF x0 | pdfium x0 | delta |
|---|---|---|---|
| `L` | 61.500 | 63.194 | **+1.694** |
| `1` | 61.500 | 62.606 | +1.106 |
| `R` | 61.500 | 62.004 | +0.504 |
| `m` | 61.500 | 61.794 | +0.294 |
| `T` | 61.500 | 61.574 | +0.074 |
| `w` | 61.500 | 61.489 | −0.011 |

That is the left side bearing, and it is a *different* number for every line.
Probing the API directly (law 15) settles which box is which: `loose.left`
equals `GetCharOrigin`'s x to **±0.000** on every character sampled, and equals
PyMuPDF's line x0 exactly, while the tight box is off by +0.074 to +1.694.

**This one defect explains all three failed predictions on this branch.** It is
per-character, so no per-page correction removes it; it is present on every line
of every document, so structural convergence cannot reach it; and it is exactly
2–5× the horizontal error PyMuPDF carries, which is what the residual table
measures.

**Hypothesis → change → expected movement.** Take x from the loose box, as y
already is. Expected: median |dx| falls to PyMuPDF's order (~0.1–0.3pt) on every
document, and within-2pt rises across the board — most on the documents whose
structure is already exact (`c6_long`, `c8_toc_links`). Risk to name in advance:
the space-synthesis thresholds (`SPAN_GAP_EM`, `SPACE_GAP_EM`, `LINE_SPLIT_EM`)
were calibrated against *ink* gaps, and advance boxes tile, so gaps shrink and
fewer spaces may be synthesised. The structural instruments will show that as a
text/space-run diff before the gate sees it — if they do, this needs splitting
into two coordinate systems rather than one. Requirement unchanged: **count ≤ 6,
no new regressions.**

### Result — 6 regressions → 3

Line x0 agreement first: median delta **+0.368 → +0.000** on `c6_long` and
**+0.399 → +0.000** on `c8_toc_links`. The named risk did not materialise —
`c8_toc_links`'s text diff went 12% → **0%**, `c6_long` stayed at 0%, and
`c7_code`'s span fragmentation *improved* 73% → 65%. Advance boxes tile, so the
gap heuristics saw cleaner input rather than degraded input.

`backend_parity.py --refine 3`: **3 regressions, 13 same, 0 better.**

| document | before | after | Δ | |
|---|---|---|---|---|
| `03_tech_report_code` | 0.05 | **0.48** | **+0.43** | **left the set** — *above* pymupdf's 0.46 |
| `c6_long` | 0.46 | **0.76** | **+0.30** | **left the set** — equals pymupdf exactly |
| `c8_toc_links` | 0.78 | **1.00** | **+0.22** | **left the set** — equals pymupdf exactly |
| `c7_code` | 0.72 | **0.82** | +0.10 | still regression (pymupdf 0.91) |
| `c4_i18n` | 0.49 | 0.57 | +0.08 | expected-divergence |
| `01_whitepaper_market` | 0.48 | 0.53 | +0.05 | still regression (0.72) |
| `c1_whitepaper` | 0.12 | 0.15 | +0.03 | |
| `02_research_paper` | 0.57 | 0.57 | — | still regression (0.76) |
| the rest | | | ±0.01 | |

**Scorecard.** I predicted median |dx| would fall to PyMuPDF's order and that
the documents with already-exact structure would gain most. Both held:
`c6_long` and `c8_toc_links` were the two structurally-exact documents and they
gained 0.30 and 0.22, landing on PyMuPDF's number *to the second decimal*. The
one I did not predict is `03_tech_report_code` at +0.43 — the document that had
resisted three previous fixes — which now scores **above** the incumbent.

**Aggregate.** Mean within-2pt over all 16 documents: **0.384 → 0.461**, against
PyMuPDF's 0.511. The branch has now closed **75%** of the gap it started with
(0.312 → 0.461 against a 0.511 target).

**What this says about the three failed predictions earlier on this branch.**
They were not failures of the fixes; they were masked by a per-character error
underneath them. The indent reconstruction, the page-space geometry and the
grouping convergence were all correct and all necessary — `c6_long` could only
land exactly on 0.76 because its blocks were already exactly right, and
`03_tech` could only reach 0.48 because its code box was already classified
correctly. Each looked disappointing in isolation and paid in combination. That
is worth remembering the next time a correct change measures flat.

**Invariance:** golden IR 7/7, purity 16/16, pymupdf column unchanged.

**Remaining three**, with the 0.08 comparator band:

| document | pdfium | pymupdf | needs |
|---|---|---|---|
| `c7_code` | 0.82 | 0.91 | **0.02** |
| `01_whitepaper_market` | 0.53 | 0.72 | 0.11 |
| `02_research_paper` | 0.57 | 0.76 | 0.11 |

---

## 2026-07-29 · M2.e — the last three

**Gate before.** 3 regressions, 13 same, 0 better.

**Horizontal is finished.** The residual table on the current renders:

| document | median dx pymupdf | median dx pdfium |
|---|---|---|
| `01_whitepaper_market` | 0.30 → 0.31 | **0.26 → 0.29** |
| `02_research_paper` | 0.10 → 0.11 | **0.10 → 0.12** |
| `c7_code` | 0.26 → 0.04 | **0.27 → 0.04** |

pdfium now matches or beats PyMuPDF horizontally on all three. Everything left
is vertical, or structural.

**Three separate causes, each named before any rule is written.**

1. **`c7_code` — span fragmentation on identical styles.** 26 lines, and PyMuPDF
   emits 26 spans (1.00 per line) against pdfium's 105 (4.04). Of pdfium's 79
   intra-line span boundaries, **79 are between spans whose style keys are
   identical**, every one at a gap of exactly 3.401pt — one space at that size.
   `_build_lines` tests `gap > SPAN_GAP_EM` in the *same* condition as the style
   change, and that test runs *before* the space-insertion branch, so a
   space-sized gap ends the span instead of becoming a space. The line's text is
   still right (text diff 0%), but it reaches the writer as four runs instead of
   one, and LibreOffice lays fragmented runs out slightly differently.
2. **`01_whitepaper_market` — trailing spaces.** 25% of lines differ in text,
   with space-run diff 0%: pdfium appends one trailing space PyMuPDF does not
   (`|•|` vs `|•·|`, `|Tier|` vs `|Tier·|`, `|…Confidential|` vs
   `|…Confidential·|`). PDFium's end-of-line generated space is being kept.
3. **`02_research_paper` — 4 missing lines** (93 against 89) plus the largest
   vertical error left anywhere: median |dy| 1.29 against PyMuPDF's 0.04, and it
   barely improves under a per-page affine fit (1.15). That is a different
   problem from the other two and the hardest of the three.

**Order and hypotheses.** Take them cheapest-first, one commit each.

- **H1 (span splits).** A span should end where the *style* ends. A gap with
  identical style on both sides should insert spaces and continue, which is what
  PyMuPDF does. Note `LINE_SPLIT_EM` already ends the *line* at 1.10em, so any
  gap still under consideration is small enough for spaces to bridge.
  Expected: pdfium spans-per-line on `c7_code` 4.04 → ~1.0; `c7_code` within2pt
  0.82 → ≥ 0.88; text unchanged (0% diff must stay 0%).
- **H2 (trailing space).** Strip a single trailing generated space from a line.
  Expected: `01_whitepaper_market` text diff 25% → near 0%; within2pt improves
  by an unknown amount — I will not pretend to predict it, since a trailing
  space affects placement only via wrap and alignment.
- **H3 (`02_research_paper`).** Unnamed as yet; diagnose after the first two,
  since both change line construction and may move it.

Requirement throughout: **count ≤ 3, no new regressions**, pymupdf lane
untouched.

### H1 result — structurally exact, and score-neutral. The prediction failed.

Two changes, interdependent and therefore one commit. Splitting spans on style
alone was *wrong on its own*: the gap it stopped consuming then reached the
space-synthesis branch and produced `def··rerank`, doubling every space
(c7_code text diff 0% → 65%). Chasing that exposed the real defect underneath —
PDFium reports a generated space's box as degenerate (`x..x` at one coordinate),
so the branch that inherits the previous character's end gives it 1.70pt where
its true advance is 5.10pt, and the remaining 3.401pt surfaces as a phantom gap
indistinguishable from positioned text.

Giving the space one space-advance of width (capped at the next character) fixed
both. The cap matters: running it to the next character also closes *table cell*
gaps, which `LINE_SPLIT_EM` splits rows on — measured, that fused cells and cost
`01_whitepaper_market` 130 lines → 105 and `03_tech_report_code` 73 → 53.

Structural convergence afterwards, on every document measured:

| document | span count diff | text diff | space-run diff |
|---|---|---|---|
| `c7_code` | 65% → **0%** | 0% → **0%** | 0% → **0%** |
| `01_whitepaper_market` | 5% → **0%** | | |
| `02_research_paper` | 20% → **0%** | | |
| `03_tech_report_code` | 13% → **0%** | | |
| `c6_long`, `c8_toc_links` | **0%** | **0%** | **0%** |

`c7_code` now emits 26 spans for 26 lines — exactly PyMuPDF's 1.00 per line,
down from 105.

**And the gate did not move.** 3 regressions, 13 same. `c7_code` 0.82 before and
0.82 after; every other document unchanged except `r1_reportlab_report`
0.58 → 0.55 and `l1_word_native` 0.03 → 0.01 (which now equals PyMuPDF exactly).

**H1 predicted `c7_code` ≥ 0.88. It scored 0.82. The prediction failed, and the
hypothesis behind it — that span fragmentation was costing placement — is
falsified.** Fragmented runs and merged runs lay out identically here; the
writer's output was already equivalent.

**The trade (law 17), and why this is kept anyway.** It costs
`r1_reportlab_report` 0.03, changes no verdict, and buys no measured score. What
it buys is correctness that is not visible in this metric: without the
generated-space fix the parser emits *doubled spaces* in its text — content that
is simply wrong, and that `live_text_cov` cannot see because it strips
whitespace. It also removes 79 spurious runs from one document's DOCX. And this
branch has twice now seen structurally-correct changes measure flat and then pay
in combination (M2.b and M2.c both looked disappointing until the metric-box fix
landed). That is an argument from precedent, not proof, and it is labelled as
such.

### H2 result — text converged, score flat, and the r1 loss came back

PDFium synthesises a space at the end of a line where the producer merely
stopped drawing. PyMuPDF does not report it. Dropping it (after RTL reordering,
so "trailing" means the end of the logical text):

| document | text diff before → after |
|---|---|
| `03_tech_report_code` | 33% → **0%** |
| `01_whitepaper_market` | 29% → **12%** |
| `02_research_paper` | 36% → **22%** |

Gate: **3 regressions, 13 same** — unchanged again, with
`r1_reportlab_report` 0.55 → **0.58**, recovering exactly the 0.03 the previous
commit cost it. So the two commits together are score-neutral and leave four of
the six documents I have been working with byte-identical to PyMuPDF on lines,
spans, text, space runs, styles and block boundaries.

### Where M2.e stops

**Gate: 3 regressions, 13 same, 0 better.** Down from 8 at the session's start.

| document | pdfium | pymupdf | structural diff remaining |
|---|---|---|---|
| `c7_code` | 0.82 | 0.91 | **none — 0% on every measure** |
| `01_whitepaper_market` | 0.53 | 0.72 | text 12% |
| `02_research_paper` | 0.57 | 0.76 | text 22%, 4 lines short (89 vs 93) |

**The plateau is real and worth naming.** `c7_code` is now identical to PyMuPDF
on every axis every instrument in this repository can measure — 26 lines, 26
spans, 0% text, 0% space runs, 0% style keys, block boundaries matching — and it
scores 0.82 against 0.91. Its residual decomposition says the horizontal error is
already PyMuPDF's (0.27 vs 0.26 raw, 0.04 vs 0.04 after fit) and its *vertical*
residual is better than PyMuPDF's (0.20 vs 0.35). It is within 0.02 of the
comparator's tolerance band and I cannot find a structural difference left to
close.

That is the honest boundary of this approach: **structural convergence on the IR
is finished, and three documents remain.** What is left is vertical placement
under `--refine`, which is a writer/refiner interaction rather than a parser
one — `02_research_paper` carries median |dy| 1.29 against PyMuPDF's 0.04 and
barely improves under a per-page affine fit, which is the signature of a
different mechanism entirely, and it is also the document that is 4 lines short.

Per §12.5 this is where I stop rather than try a third parser-side idea: two
hypotheses (H1 span fragmentation, H2 trailing spaces) were both structurally
confirmed and both scored flat. The next move needs new attribution, and on the
evidence it points outside `parse_pdfium.py` — which makes it an M2.d escalation
packet question, not another parser change.

---

## 2026-07-29 · Decision-memo session 1 — `02_research_paper`, then the text diffs

Following the memo's §5 sequencing and §6 kickoff. Target-selection rule
accepted: while any document in the regression set shows a structural diff, the
next target is the largest structural diff on the worst-gapped document. That
resolves the "third self-picked target" worry — the rule picks, not me.

**Gate before.** 3 regressions, 13 same, 0 better.

### The four missing lines — named, and both leading hypotheses falsified

Evidence ask answered. They are all on **one baseline**:

| page | y | x0..x1 | size | text |
|---|---|---|---|---|
| 1 | 585.30 | 378.55..415.75 | 9.5 | `decoding ` |
| 1 | 585.30 | 423.59..449.20 | 9.5 | `builds ` |
| 1 | 585.30 | 457.04..468.92 | 9.5 | `on ` |
| 1 | 585.30 | 476.76..548.00 | 9.5 | `rejection-sampling` |

- **Memo hypothesis 1 (whitespace-only lines dropped by construction):
  falsified.** None of them is whitespace, and the PyMuPDF IR for this document
  contains **zero** whitespace-only lines.
- **Memo hypothesis 2 (superscript fragments): falsified.** All four are body
  text at 9.5pt, the document's body size, and none is a marker.
- **What it actually is:** pdfium is not *missing* lines. **PyMuPDF is
  fragmenting one.** These four are consecutive word-groups of a single
  justified line, split at its stretched word gaps (7.84pt each, a constant
  0.83em). pdfium emits the whole line, `378.55..548.00`, as one Line — and
  `LINE_SPLIT_EM` at 1.10em (10.45pt here) correctly declines to split at 7.84pt.
  Every pdfium line matched a PyMuPDF line; there are **zero** lines in pdfium
  that PyMuPDF lacks.

So the "4 missing lines" is a **line-count difference in which pdfium is the
more faithful side**, not a defect. Nothing to fix, and I am not going to
reproduce a fragmentation to flatter a count.

### The text diffs — one mechanism, quoted

Same justified text, and this one *is* a defect:

```
mupdf  |Speculative·decoding·accelerates·autoregressive·generation|
pdfium |Speculative··decoding··accelerates··autoregressive··generation|

mupdf  |with·a·large·one.·Fixed·draft·models,·however,·leave|
pdfium |with··a··large··one.··Fixed··draft··models,··however,··leave|

mupdf  |Priya·Raman···Diego·Álvarez···Hannah·Cole|   runs=[3, 3]
pdfium |Priya·Raman··Diego·Álvarez··Hannah·Cole|     runs=[2, 2]
```

Justified text stretches its word gaps. A space *character* is already present;
the stretched remainder still exceeds `SPACE_GAP_EM`, so the synthesis adds
another on top. The existing guard caps the addition at one for proportional
text (`n_sp = min(n_sp, 1)`) — which is exactly how every gap comes out as two
spaces instead of one.

**Hypothesis → change → expected movement.** In proportional text a gap that is
already occupied by a space character should contribute **no** additional space;
MuPDF emits one space however far the gap is stretched. Monospace keeps the
existing behaviour, because there the count is load-bearing (code indentation)
and the earlier measurement stands. Expected: `02_research_paper` text diff
22% → near 0, `01_whitepaper_market` 12% → near 0; both are justified-text
documents and this is the whole of their remaining structural diff. Score
prediction, written before running and deliberately modest given the last two
flat results: **02 improves, because doubled spaces displace every word after
them on a justified line — unlike the fragmentation and trailing-space fixes,
this one moves ink.** Requirement unchanged: count ≤ 3, no new regressions.

*(Counter-example noted and not swept under: `1··Introduction` → `1·Introduction`
runs the other way — PyMuPDF emits two spaces at a wide heading gap where pdfium
emits one. That is a second, rarer pattern with the opposite sign; it is left
alone this session rather than fitted, and recorded here so it is not lost.)*

### Result — text converged again, score identical again. Prediction failed.

| document | text diff | space-run diff |
|---|---|---|
| `02_research_paper` | 22% → **8%** | 22% → **7%** |
| `01_whitepaper_market` | 12% → **8%** | 5% → **1%** |

**Gate: 3 regressions, 13 same — every single number identical to the previous
run.** `02_research_paper` 0.57 before and after; `01_whitepaper_market` 0.53
before and after.

I predicted this one would move, and said why: *"doubled spaces displace every
word after them on a justified line — unlike the fragmentation and
trailing-space fixes, this one moves ink."* **It does not, and now I know why:**
in justified text the renderer redistributes inter-word space to fill the
measure, so the *number* of spaces in the source has no effect on where the
words land. LibreOffice re-justifies to the same width whether the source says
one space or two. The doubled spaces were wrong content, and positionally inert.

**That is three structurally-confirmed, score-flat hypotheses in a row** — H1
span fragmentation, H2 trailing spaces, H3 justified spacing — and the third one
retroactively explains the first two. Text- and span-level differences in this
corpus do not reach `within2pt` at all, because the renderer normalises exactly
those degrees of freedom. §12.5 stops this line of work, and this time the stop
is principled rather than merely procedural: **the class of defect has been
shown not to matter to the metric.**

**The trade (law 17):** no score movement, no regression, no verdict change. Kept
on the same grounds as the trailing-space fix — one space is the correct content
and two is not, `live_text_cov` strips whitespace so it cannot see the
difference, and a user opening the DOCX would. Structural fidelity is worth
having on its own terms; it is simply not what the last three documents are
losing on.

**Structural convergence is now finished and demonstrated finished.** Every
document in the regression set is at or near 0% on every structural instrument,
and the remaining gaps are entirely vertical placement — which is memo §5 item 4,
gated behind the `c7_code` noise floor.

### `c7_code` noise floor (memo §4) — step 3, not step 2

| refine | pymupdf | pdfium | gap |
|---|---|---|---|
| 0 | 0.56 | 0.38 | −0.180 |
| 1 | 0.91 | 0.82 | −0.090 |
| 2 | 0.91 | 0.82 | −0.090 |
| 3 | 0.91 | 0.82 | −0.090 |
| 3 (repeat) | 0.91 | 0.82 | −0.090 |

The raw spread across configurations is 0.090, which touches the memo's ≥0.09
step-2 trigger — but reading it that way would be wrong. Refine 0 is a different
*configuration* (no correction loop at all), not a noisy repeat of the same one.
At refine 1, 2 and 3 the numbers are **identical**, the repeat is bit-identical,
and the gap never changes sign. The harness is not noisy here; it is exact.
So: **step 3 — something systematic survives below the structural floor.**

### And it was mine

Per-word attribution (memo §4 step 3's suggested tool). The entire gap is **17
words on exactly two source lines**, and pdfium's horizontal error accumulates
linearly along each:

```
word          src y   pymupdf dx,dy      pdfium dx,dy
quality       103.9   (+0.03, -1.95)     ( -2.62, -1.40)
degrades      103.9   (-0.03, -1.95)     ( -5.31, -1.40)
non-linearly  103.9   (-0.08, -1.95)     ( -7.99, -1.40)
...                                       ...
embedding     103.9   (-0.43, -1.95)     (-34.72, -1.40)
```

−2.67pt per word gap, perfectly linear — one space advance at that size. Words
clearing 2pt under PyMuPDF but not pdfium: **17. The other way round: 0.**

The block diff named the cause: `pdfium SPLITS where PyMuPDF merges`, three
times, every one at exactly gap=15.0 with overlap 489.7 — the body-text pitch.
**This was my own M2.c change.** `c7_code` sets its code listings at an 11.25pt
pitch, which drags the page-wide 20th percentile *below* the body text's 15.0pt,
so body paragraphs split into one block per line, each became its own justified
paragraph, and a one-line justified paragraph is not stretched to the measure.
Exactly the mirror of the median's failure: dragged *up* by tables then, *down*
by code now.

**Fix: compute the body pitch per type size.** Text of one size shares one
leading, so the reference lives with the text rather than with the page. It is
not the reverted sliding window — a window has no idea what it is averaging
over; a size bucket is a property of the text itself. Falls back to the page
percentile when a size has fewer than three samples.

**Result: 3 regressions → 2, 13 same, 1 better.**

| document | before | after | |
|---|---|---|---|
| `c7_code` | 0.82 | **0.91** | **left the set — equals PyMuPDF exactly** |
| `05_memo` | 0.64 | **0.88** | **BETTER than PyMuPDF's 0.64** |
| everything else | | | unchanged |

Block boundaries: `c7_code` 23/26 → **26/26**, `c6_long` and `c8_toc_links` hold
at 201/201 and 17/17.

**The memo's §4 owner decision is now moot.** `c7_code` needed 0.02 and gained
0.09; it sits *on* PyMuPDF's number. No `ACCEPTED_SHORTFALL` entry is required,
and I have not created the mechanism.

**Remaining: 2.** `01_whitepaper_market` 0.53 vs 0.72, `02_research_paper` 0.57
vs 0.76. Both are the vertical-placement question — memo §5 item 4.

---

## 2026-07-29 · Decision-memo session 2 — the vertical question (read-only first)

**Gate before.** 2 regressions, 13 same, 1 better. Only `01_whitepaper_market`
(0.53 vs 0.72) and `02_research_paper` (0.57 vs 0.76) remain, and for the first
time there is a single open line of attack rather than several.

**Read-only, per memo §5 item 4 and §3.** No parser change is planned before the
histogram says what the error is shaped like.

**Note on the memo's dissolution route.** §3 offered: *if the dy histogram is
bimodal with a mode near one leading, the four missing lines are the cause and
the dy question dissolves into Q3.* That route is closed — the four lines turned
out to be PyMuPDF fragmenting one justified line, with pdfium the more faithful
side, so there is nothing to close. The histogram is still the right first
measurement; it just cannot dissolve into that answer.

**Prediction, written before running.** `02_research_paper`'s median |dy| is
1.29pt and its post-affine residual is 1.15pt — a per-page affine fit removes
almost none of it. A missing-line or wrap difference would show as a mode near
one leading (≈13pt at this document's 9.5pt type). 1.29pt is two orders below
that. So I predict:

- **unimodal, not bimodal**, centred near 1–1.5pt, with no mass near 13pt;
- therefore **not** a line-count or wrap problem, but a small per-paragraph
  anchoring offset — the `para_top = baseline − (leading − 0.21·size)` model or
  `space_before`, quantised;
- and because it survives a per-page affine fit, it must vary *between*
  paragraphs rather than accumulate down the page.

If instead there is a mode near one leading, I am wrong and the cause is
structural after all.

### Result — prediction confirmed, and the cause located

The histogram is **unimodal with no mass near one leading**, exactly as
predicted. But the control is what makes it decisive — the two backends produce
*the same distribution, displaced*:

| bucket | PyMuPDF | | bucket | pdfium |
|---|---|---|---|---|
| **+0.0** | **252** | → | **+1.5** | **225** |
| +1.0 | 35 | → | +2.5 | 47 |
| **+3.0** | **55** | → | **+4.5** | **55** |

Every cluster displaced by exactly **+1.5pt**, and the 55-word cluster appears
with *identical count* on both sides. That is a constant offset, not scatter.
It is also why a per-page affine fit removes so little: a least-squares line
through a multi-modal distribution sits between the modes.

**Where it enters.** Baselines are identical on every line (`dbase = +0.00`).
The line *boxes* are not: pdfium's y0 sits 0.57–2.60pt lower, scaling with type
size. `margin_t` is derived from the topmost line's box top, and comes out
**63.30 (PyMuPDF) against 64.90 (pdfium)** — a 1.6pt page-wide shift, which is
the +1.5 mode.

**Why the boxes differ — and why this one cannot simply be "converged".** The
box is font-dependent in both, from *different metric sources*:

| font | PyMuPDF up/size, down/size | pdfium up/size, down/size |
|---|---|---|
| Helvetica | 1.075, 0.299 | 0.905, 0.211 |
| Helvetica-Bold | 1.070, 0.307 | 0.905, 0.211 |
| Times-Roman | 1.053, 0.281 | 0.891, 0.215 |
| Times-Bold | 1.044, 0.341 | 0.891, 0.215 |
| Symbol | 1.010, 0.293 | **1.010, 0.293** |

pdfium *is* reading font metrics (Helvetica and Times differ), just not the same
ones — and on Symbol, where both fall back to the embedded metrics, they agree
exactly. PyMuPDF's numbers are its own built-in base-14 table. Reproducing them
means vendoring MuPDF's private font metrics, which §13 forbids outright and
which this branch has already proved is version-dependent.

**Causality tested, not assumed.** A labelled temporary experiment scaled the
box toward PyMuPDF's ratios (1.188 above the baseline, 1.417 below):

| document | shipped | scaled | pymupdf |
|---|---|---|---|
| `02_research_paper` | 0.57 | **0.64** | 0.76 |
| `01_whitepaper_market` | 0.53 | 0.54 | 0.72 |

So the box convention **is** a real cause, worth +0.07 on the document with the
worst vertical error — and it is **not the whole gap**: 0.64 is still 0.12 short,
and `01_whitepaper_market` barely moves, so it has a different problem again.
The experiment was reverted; a fitted pair of constants that does not even close
the gap is not something to ship.

**Where this leaves M2.** The remaining two documents are not blocked on
anything structural in the parser — they are blocked on a design question the
parser cannot answer alone:

> `margin_t` (and paragraph anchoring) is derived from line-box *tops*, a
> quantity on which two correct parsers legitimately disagree because it comes
> from font-metric tables they do not share. Baselines, which both report
> identically to 4,734 of 4,734, carry the same information without the
> disagreement.

That is a question about `infer.py`'s derivation, with a valid experiment and a
measured magnitude behind it — which is the first time on this branch that the
escalation-packet bar in plan v2 §5.M2.d has actually been met on evidence
rather than on frustration.
