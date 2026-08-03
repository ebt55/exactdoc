# exactdoc — execution log

**Purpose:** let any session resume the Google-Docs-first build plan without
re-deriving where things stand. The plan itself is
`docs/exactdoc-google-docs-production-build-plan.md` (gitignored, private). This
file is the committed record of what has been executed against it.

**Read this first, then `git log`, then STATUS.md.**

---

## Standing constraints

From plan §17, and they are not negotiable by a session that finds them
inconvenient:

1. Never change corpus, threshold, exception, environment and converter in one
   commit.
2. A canonical-environment change needs a new environment ID and an explicit
   baseline/policy migration.
3. A baseline may be re-recorded only after full-corpus success in the named
   environment, and must show the before/after diff.
4. Provisional findings never count as a pass.
5. Missing work, missing documents, NaN, errors, cleanup failure and
   zero-test execution are failures.
6. Google and LibreOffice evidence stay separate.
8. Do not tune on holdouts.
9. No cloud action without explicit consent and a recoverable cleanup path.
12. Update README/ROADMAP/STATUS/PR bodies from generated evidence in the same
    change that alters a product claim.

---

## Done

| ID | What | Evidence |
|---|---|---|
| INT-00 | PR graph consolidated; #1 merged with a merge commit preserving `0cd7d11`; #2/#3 closed as superseded | `docs/evidence/pr-transition.md` |
| **Consolidation** | **PR #4 merged to `main` (`ef653c9`) with 19 commits, deliberately red.** All five feature branches deleted after verifying every commit was reachable from `main`; remote is now `main` alone. No open PRs, no open issues | `git log --first-parent main` |
| REL-01A (partial) | Conversion/refinement DOCX publication is now genuinely transactional: private candidates are structurally validated before atomic replacement; failures preserve existing bytes and leave no predictable `.best` artifact. This does **not** mark the wider offline-boundary work or `ConversionResult` complete. | Atomic-output checks; 224/224 values unmoved |
| GDOCS-04 table tranche | Consented Google qualification of `pdfium/gdocs/none/refine0@240dpi`: operational pass, 16/16 succeeded, zero orphan ledger. Page match 14/16→15/16; c3 is now an editable continuous 3-page table with all 45 rows. The overall run remains false solely because `quality.status=missing` (`failure_stage=quality-policy`), not because operational work failed. | `testkit/batch/gdocs_candidate_tables2.gdocs-qualification/gdocs_qualification.json` |
| GDOCS-04B policy v2 | Strict tiered draft policy and offline evidence reassessment implemented. Existing evidence remains operationally valid; 9/13 ordinary fixtures clear every draft threshold, with seven blocking findings across four documents. The policy is unratified and therefore cannot pass by construction. | `testkit/gdocs_quality_policy.json`; `docs/evidence/gdocs-candidate-tables2-assessment.json` |
| GDOCS-04C symbol lists (local) | Corroborated leading OpenSymbol `U+F0B7` markers canonicalised to Unicode bullets. l1 is now three editable hanging-indent items; only l1 `document.xml` changes across the 16 prepared packages. Local proxy doc/word recall 0.9583→0.9792, dx50 90.29→64.93pt, dy50 12.79→10.39pt, SSIM 0.7887→0.7946. Fresh Google evidence still required. | `exactdoc/dialect.py`; `tests/test_symbol_list_markers.py` |
| DET-02a | Environment identity made exact and enforced. Recorded reference, both-direction font matching, `fonts.conf` verified by content, fingerprint enforced | `testkit/canonical_env.json`, fp `3ca438f1…` |
| DET-02b | `accepted_shortfalls` split into `provisional_shortfalls` (cannot authorise) and `ratified_shortfalls` (owner/date/issue/review). Four D2 docs provisional; nothing ratified | `testkit/parity_policy.json` schema 2 |
| DET-02c | Two false-green tests repaired: the PyMuPDF-free proof searched only gitignored dirs and returned 0 having converted nothing; the generator test discarded both exit codes and required 3 of 16 documents | `tests/test_no_pymupdf.py`, `tests/test_corpus_generation.py` |
| DET-02d | Canonical image built and recorded; stale `c4_i18n` floors remeasured; all six floors bound to their environment | `docker/gate.Dockerfile` |

**Found along the way, each now tested:**

- `backend_parity.py --update-policy` — the documented way to record floors —
  raised `NameError` before writing anything. It had never worked, which is why
  the stale floors were never refreshed.
- `scripts/fonts.conf` is hashed into the fingerprint but `.gitattributes` did
  not pin `*.conf` to LF, so a Windows checkout recorded a digest no Linux
  checkout could reproduce.
- `test_committed_parity_policy_is_wellformed` looped over a renamed section,
  found nothing, and passed on zero assertions.

Mutation suite 153 → 198 assertions, green on Windows and in the canonical image.

---

## Current gate state, and why it is red

```
gate PASS (product)   pagematch 15/16  <2pt 0.4981  live 0.9652  dy50 0.675
gate PASS (raw)       pagematch 13/16  <2pt 0.3349  live 0.9652  dy50 2.2
parity FAIL           6 failures
```

Six failures, all deliberate:

| n | kind | resolution |
|---:|---|---|
| 2 | unwaived `dy_p50` regressions (`05_memo`, `f1_fpdf_brief`) | DEC-D2, after Google evidence |
| 4 | provisional D2 shortfalls | DEC-D2, owner ratification |

**Parity cannot go green by engineering.** It is a decision queue. Do not
"fix" it, do not widen a waiver, do not re-add `continue-on-error`.

CI additionally reports NOT canonical — correctly. The runner is Python 3.12.13
against the image's 3.12.3 and ships four extra DejaVu variants. That closes only
when `gate.yml` runs inside the published image.

---

## Blocked on the owner

Nothing below can be unblocked by a session, and three of them gate a release.

| # | Needs | Why it cannot be delegated |
|---|---|---|
| B1 | `write:packages` on the `gh` token, or `gate-image.yml` on `main` | Publishing the canonical image. Without it CI can never be canonical |
| B2 | **LIC-01 provenance ledger** | Requires knowledge of where the initial code came from and the right to relicense it. Plan calls it a hard blocker: if rights cannot be established, that material cannot be relicensed |
| B3 | Legal sign-off on LIC-02 | Not a measurement |
| B4 | DEC-D2 and GDOCS-05 ratification | Explicit owner decisions. A gate an executor can satisfy alone is not a gate |
| B5 | Google Cloud project + test account, protected CI environment | Credentials and org policy |
| B6 | PyPI / TestPyPI trusted publishing | Publishing under the owner's identity |

**B2 is the one to start now.** It runs in parallel with everything and a bad
answer invalidates the whole relicence.

---

## Next, in order

### REL-01A — offline conversion boundary · *partially complete*

Split `target` into `output_profile` (how the DOCX is serialised) and `oracle`
(what renders it during refinement). Today one field means both, so
`target="gdocs"` cannot say "Google-Docs-safe OOXML, offline" — which is exactly
the shipping profile.

- [ ] `exactdoc/errors.py` — typed hierarchy
- [ ] `exactdoc/result.py` — `ConversionResult`, requested vs resolved options
- [x] transactional DOCX publication for writer/refinement candidates; structural
  validation before atomic replacement, with failure preservation
- [ ] `exactdoc/profiles.py` — the two axes, legacy `target=` migration
- [ ] CLI exit codes + `--json`
- [ ] failure-injection and concurrency tests

**Invariant: G1 must move zero recorded fidelity values.** It changes contracts
and safety, not layout. The transactional-publication slice has passed its
atomic-output checks; the remaining boundary work still needs the full proof.

### Then

Next quality work is the diagnosed c2 two-column right-edge/margin defect, then
the remaining ordinary-document blockers, followed by a broader 40–60-PDF frozen
corpus and owner policy review. The l1 symbol-list fix remains locally verified
but live-Google pending.
Annotation/internal-TOC preservation and heading/list semantics follow without
displacing those release blockers. Google full-corpus qualification happens
only after explicit upload consent, followed by a second clean release pass.
`GDOCS-01` packaged oracle →
`GDOCS-02` visual+semantic gate → `GDOCS-03` first real Google measurement →
`DEC-D2` → `GDOCS-04` fixes → `GDOCS-05` default flip → `LIC-03` → `PKG` →
`CI-01` → `RELEASE-01` remains the release sequence.

Do not start Google fidelity tuning before GDOCS-03 produces a complete
discovery artifact. Optimising against LibreOffice for a Google target is the
mistake the whole plan is shaped to avoid.

---

## Reproducing the canonical environment

```
docker build -f docker/gate.Dockerfile -t exactdoc-gate:dev .
docker run -d --name exactdoc-canon -w /work exactdoc-gate:dev sleep infinity
docker cp . exactdoc-canon:/work        # copy; do NOT bind-mount from Windows
docker exec -e FONTCONFIG_FILE=/work/scripts/fonts.conf exactdoc-canon \
  bash -c 'cd /work && bash scripts/bootstrap.sh --strict'
```

A full both-lane gate plus a parity run is 20–40 minutes. Windows renders with
real Arial/Times and is indicative only; CI Linux is the number of record.
