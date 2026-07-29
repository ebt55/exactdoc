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
