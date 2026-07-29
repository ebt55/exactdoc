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
