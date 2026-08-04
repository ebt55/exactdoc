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
| 2026-08-04 canonical run | Stale `c3_tables` baseline records found and the baseline deliberately re-recorded after byte-identical attribution; both lanes re-verified PASS; parity policy rebound to a full profile ID as provisional. See the dated entry at the end of this file | `docs/evidence/canonical-gate-2026-08-04.json`, `29945f2` |

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
gate PASS (product)   pagematch 16/16  <2pt 0.5161  live 0.9652  dy50 0.675
gate PASS (raw)       pagematch 14/16  <2pt 0.3349  live 0.9652  dy50 2.79
parity FAIL           2 failures
```

Measured 2026-08-04, canonical fingerprint `3ca438f1…`, evidence
`docs/evidence/canonical-gate-2026-08-04.json`. Two failures, both deliberate:

| n | kind | resolution |
|---:|---|---|
| 2 | provisional shortfalls (`c4_i18n` D10, `c5_graphics` D10) | DEC-D2, owner ratification |

The two previously unwaived `dy_p50` regressions are gone: at the candidate's
own profile `05_memo` and `f1_fpdf_brief` are better and same respectively. They
remain out of every waiver section, by test. `c2_paper2col` was a third
provisional shortfall for part of the same day and was retired by `c1cbc2a`;
the gate lines above predate that commit and the parity count does not.

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

---

## 2026-08-04 — stale baseline found, re-recorded on purpose, re-verified

Canonical environment, fingerprint `3ca438f17d905cef…`, evidence committed at
`docs/evidence/canonical-gate-2026-08-04.json`.

**1. The discovery: the baseline had gone stale.** The gate refused the
`c3_tables` records, and it was right to. The striped-table assembler had
already moved that document — product `page_err` 1→0 and word recall
0.331→0.9359 — while the committed record still described the document as it had
been. A record that no longer describes reality is the failure mode the stale
check exists for, and it fired. This is worth stating plainly because it is the
inverse of the usual worry: the gate went red not because quality dropped but
because quality improved and the record did not follow.

**2. The attribution check, before any re-record.** A baseline may only be
re-recorded after full-corpus success in the named environment, with the
before/after diff shown (§17 rule 3) — but "which change caused this?" is not
answered by a diff. It was answered by disabling the new inference rules and
re-converting: **`c3` output is byte-identical with them off.** So the movement
is the striped-table assembler's and nothing else's. Byte-identity is the only
form of this check that cannot be argued with; a metric that merely "looks
unchanged" would have left the attribution a hypothesis.

**3. The deliberate re-record** (`29945f2`). Justification, in order: the
improvement is real, it is attributed to a single named change, the environment
is canonical and unchanged, and the corpus is the same 16 frozen fixtures — so
the record was wrong and the measurement was right. The re-record was not
performed to clear a red gate; the gate was red *about the record*, and leaving
it red would have meant preserving a number known to be false. Before/after,
both lanes:

| lane | page match | mean within-2pt | mean live text | median dy50 |
|---|---:|---:|---:|---:|
| product, before | 15/16 | 0.4981 | 0.9652 | 0.675pt |
| product, after | 16/16 | 0.5161 | 0.9652 | 0.675pt |
| raw, before | 13/16 | 0.3349 | 0.9652 | 2.2pt |
| raw, after | 14/16 | 0.3349 | 0.9652 | 2.79pt |

Two movements are worth naming so nobody re-chases them as regressions. Raw
median dy50 rose 2.2→2.79pt: `c3` now matches many more words (raw word recall
0.3137→0.8648) and its own dy50 moved 2.5→7.45pt with them, which reorders the
median. That is a word-population effect, not drift. And `c2_paper2col`'s
two-column right-edge fix moved product dy50 29.2→0.85pt with within-2pt
0.1948→0.4857, and raw dy50 26.8→4.0pt — placement, not pagination.

**4. Fresh verification: both lanes PASS.** Product 16/16 page match, 0.5161
mean within-2pt, 0.9652 mean live text, 0.675pt median dy50. Raw 14/16, 0.3349,
0.9652, 2.79pt. Gate mutation tests all clear (83 cases). The corpus resolved
16 of 16 with no problems, and the environment reported canonical with no
mismatches.

**5. Parity refused adjudication, correctly.** `testkit/parity_policy.json` was
bound only by `recorded_refine_rounds: 3`; refine rounds name neither a backend
nor an output profile, oracle or DPI. The tool said so and told the operator
what to do instead: measure with `--measure`, then create a policy explicitly
bound to the named profile, because `--update-policy` deliberately does not
migrate findings across a profile boundary. The `--measure` run
(`pdfium/gdocs/none/refine0@240dpi`, 16 documents, empty margins) reports **8
regressions, 6 same, 2 better** — raw movements, explicitly unadjudicated and
never release-ready.

A new policy bound to that full profile ID now replaces the legacy file. It is
**provisional and unratified**: it was written with three tracked findings
(`c2_paper2col` D2, `c4_i18n` D10, `c5_graphics` D10) and carries two, because
`c1cbc2a` retired `c2_paper2col` the same day — the superscript-absorption fix
took it to BETTER on every dimension and the entry became a stale waiver, which
`adjudicate()` refuses. Each remaining finding is bounded by floors measured in
this environment, and `ratified_shortfalls` is empty, which is the executable
form of "nothing is authorised". The four D2 core-14 findings the old file carried were
measured at another profile and are **not** migrated and **not** retired — their
profile has simply not been remeasured. The prior rendered evidence for
`c4_i18n` (PDFium reports RTL in logical order) and `c5_graphics` (PDFium keeps
the gradient band PyMuPDF drops) is preserved inside those entries rather than
used to excuse them, because it was produced at a profile this policy does not
govern.

Live Google truth was the committed 2026-08-02 evidence at the time of this
run, which touched none of it. It has since been superseded by the 2026-08-04
live qualification (`ee0d06c`) — operationally clean, quality worse: 11 blocking
findings across 8 ordinary fixtures, attributed to `ff518be`'s 3pt per-boundary
compensation and retired in `41e8e7f` on remeasurement against Google's own
exports. That retirement is unconfirmed until a fresh consented pass.

---

## 2026-08-04 — a shadow of a frozen fixture, found by the licence audit

The licence audit (`docs/license-audit.md`) had to enumerate everything this
repository redistributes, which meant counting tracked PDFs rather than trusting
the two manifests to be the whole story. They were not: **47 PDFs were tracked
and only 45 were manifested.**

The other two, plus three more binaries, sat in `tmp/pdfs/`:

```
tmp/pdfs/l1_word_native.pdf     tmp/pdfs/l1_symbol_fix.pdf
tmp/pdfs/l1_symbol_fix.docx     tmp/pdfs/l1_symbol_fix.png
tmp/pdfs/l1_source.png
```

**How they got in.** `0d3d03e`, whose message is "Updating .md files." It
carried the l1 symbol-list-marker work — `exactdoc/dialect.py`,
`tests/test_symbol_list_markers.py` — the doc updates its message describes, and
five binary files from the debugging session that produced it: the input, the
output, and before/after renders. An over-broad `git add`, in a commit message
that mentioned none of it. `.gitignore` had no `tmp` entry, so nothing stopped
it and nothing would have stopped the next one.

**Why it mattered more than untidiness.** `tmp/pdfs/l1_word_native.pdf` shares
its name with a frozen, SHA-256-pinned gate fixture and is *not* that file:

| | bytes | sha256 | content fingerprint |
|---|---:|---|---|
| `testkit/fixtures/l1_word_native.pdf` (pinned) | 44,035 | `fa9e0742…` | `28c27dbb…` |
| `tmp/pdfs/l1_word_native.pdf` (shadow) | 81,769 | `dddef295…` | `28c27dbb…` |

The content fingerprints are **identical**. That digest covers page geometry and
whitespace-normalised text and carries no timestamp, so the two files are the
same document — same page, same words, nearly double the bytes. Which is the
worst version of this hazard, not the mildest: opening both and comparing them
tells you nothing, because there is nothing to see. Only the manifest's sha256
separates them, and only for the copy the manifest describes. The other copy was
governed by nothing.

Nothing read them — grepped for `tmp/pdfs`, `l1_symbol_fix` and `l1_source`
across the tree; the only references were in the audit that found them. So they
were removed from tracking **and from disk**: leaving an unpinned shadow of a
gated input in the worktree preserves the hazard while hiding it from `git
status`, and the bytes remain recoverable from `0d3d03e` if anyone ever wants
them. `tmp/` is now in `.gitignore` with the reason written next to it.

**The general lesson is the one this repository keeps paying for.** The
manifests make corpus identity mechanical, and they do it only for files inside
the directories they describe. A file one directory away is outside the system
entirely — not failing its checks, simply absent from them — and absence is the
failure mode that no check reports. It took an audit that counted the tree
rather than reading the manifests to notice.
