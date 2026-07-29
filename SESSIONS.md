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
      `continue-on-error` on the lanes. Verified by running the same commands
      in the container: `9 known failure(s) in the record, 0 new, 0 stale`,
      `GATE_EXIT=0`. *(CI itself has not been triggered — the branch is not
      pushed; see the note below.)*
- [x] Numbers recorded in STATUS.md §1 as the Linux/CI baseline, beside the
      Windows column.
- [x] A deliberately broken environment still produces a passing
      corpus-generation run with an explicit skip report.
- [x] `pypdfium2` declared in `testkit/README.md`'s quick start; `SOFFICE` /
      `CHROME` documented in a table.
- [x] Mojibake (plan §8.6): **not present** — bullets are `E2 80 A2`. No golden
      churn spent on a defect that had already been fixed.

**Not done, and why.** The workflow file cannot be *observed* green until the
branch is pushed to GitHub, and `gh` is unauthenticated on this machine.
Everything the workflow runs has been run here, in the same image family, with
the same commands — but "CI is green" is a claim only a CI run can make, so it
is recorded as unverified rather than checked.

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
