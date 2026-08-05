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
| B4 | DEC-D2 and GDOCS-05 ratification | Explicit owner decisions. A gate an executor can satisfy alone is not a gate. **Partly discharged 2026-08-04**: the author ratified the Google Docs *quality* policy with one bounded waiver (recorded with its provenance in that policy's `review.rationale`). DEC-D2 — the two provisional *parity* findings — and GDOCS-05, the default flip, are untouched and still owner-only |
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

## 2026-08-04 — the quality policy is ratified, and pass 4 assesses clean

Four consented full-corpus passes ran today. All four were operationally clean;
blocking quality findings fell **11 → 4 → 3 → 1**:

| pass | blocking | cleared by |
|---|---:|---|
| 1 | 11 | — (the 3pt boundary compensation had regressed it from 7) |
| 2 | 4 | retiring that compensation |
| 3 | 3 | `l1_word_native` dy 15.19 → 1.93pt |
| 4 | **1** | `l1` dx 39.82 → 1.35pt; `c2_paper2col` SSIM 0.6772 → 0.7087 |

The pass-4 clearances have named mechanisms, which is the difference between a
fix and a coincidence. `l1`'s horizontal drift was a font substitution error —
Libre Baskerville, chosen from Docs-measured metrics, landed a packing
prediction of 1.0004 against the source pitch. `c2` cleared on a 1.0pt scoped
section-break compensation and beat its own ~0.69 raw-proxy extrapolation.

**The decision.** The repository author decided, in the coordinating session
today, to ratify the policy with a single documented waiver for `01`'s cover
band while the residual fixes proceed in parallel. Recording the provenance
matters here more than usual: ratification is the one act the standing
constraints say an executor must not perform on its own authority (B4), so the
policy's `review.rationale` states that the decision was taken by the author and
relayed, that the named approver is an attestation recorded on that relay, and
that the approver should confirm it against the file. An attestation nobody can
trace is the thing the provisional/ratified split exists to prevent.

**The policy could not express the decision, so the schema grew.** v2's
`per_document` applies uniformly to every document in a tier. The only ways to
pass `01` were to lower `mean_ssim` for all thirteen blocking fixtures, or to
move `01` to the non-blocking tier — a bar moved to clear a failure, or a tier
treated as a property of a score rather than of a document. Both are failures
this repository has already named. v3 adds `waivers`: one metric, one document,
floored, ratified-only. Three outcomes, two of which still block — inside the
band is `waived` and reported; past the floor is `out-of-bounds` and blocking;
clearing the tier bar entirely is a blocking `stale-waiver`, so retirement is
enforced rather than remembered. Every other metric on a waived document is
untouched, so `01` would still block on drift, recall, coverage or pagination.

**The waiver:** `01_whitepaper_market` `mean_ssim`, floor 0.65 against a measured
0.6589 — about a hundredth below, which absorbs run-to-run jitter and nothing
else. Cause is probe-measured, not inferred: Docs adds space above a page-leading
cover band unconditionally, requested `[0, 4, 8, 14.4, 20]` rendering as
`[14.55, 18.83, 22.83, 29.23, 34.83]`, an addition and not a clamp. The writer
compensates what is compensable; the remainder is a ~14.6pt band floor, with a
missing 4pt accent bar and a ~2pt band-to-body gap filed as the fixable
residue. `01` clears page match, live text, both recalls and both drift bounds
on the same pass, so this is visual registration, not conversion.

**Result:** assessed offline against pass 4, `operational_pass: true`,
`quality_pass: true`, **`overall_pass: true`**, zero blocking findings. That is
**clean pass 1 of the 2** the migration gate requires. Two things belong next to
that sentence rather than beneath it: the pass became clean partly *because* a
waiver was ratified after it was measured, and the second pass must be a fresh
consented run.

## 2026-08-05 — two defects that were hiding each other, and a re-record

Canonical environment, fingerprint `3ca438f17d905cef…`, evidence at
`docs/evidence/c1-band-and-cards-2026-08-05.json`.

**1. The symptom.** `c1_whitepaper` — the gated fixture standing in for exactly
the document class this converter exists for — measured `within2pt` **0.0000 in
both parser arms**. Not low: zero. No word anywhere in the document landed
within 2pt of its source position, on either backend.

**2. Why it was zero, and why that was two answers.** Auditing placement per
line rather than in aggregate showed the field is not one thing. Above the stat
cards both arms are identical to 0.01pt at a flat **−13.5pt**; below them PyMuPDF
jumps to **+101.7** and PDFium does not move at all. A flat constant plus one
step — not a leading model error, not accumulation.

- **The constant (both arms).** c1's cover band is a Chromium full-bleed fill
  inset to `y0=7.16`, and `top_bands` seeds only on `y0 <= 2.5`, so it ships as
  an ordinary in-flow box table. Its cell holds *one* paragraph carrying two
  source lines — a 9.77pt title and an 8.0pt subtitle — because the paragraph
  splitter wants a size ratio over 1.3 (this is **1.221**) or a baseline gap over
  26.3pt (this is **16.94**). Neither fires, the renderer sets both runs on one
  line, and the row comes out **98.15pt against a declared 112.68pt**. Every
  element below inherits the lost line. The quality ladder fixes precisely this,
  computes it correctly, and **was switched off in every profile**.
- **The step (PyMuPDF only).** The three stat cards share an exact source
  y-extent and sit in 9.33pt gutters; after `build_figure`'s ±2pt clip padding
  the gap is 5.3pt and `_merge_figures` expanded by **4.0** — missing by 1.3pt.
  Three stacked block figures cost 171pt of flow against the source's 57pt.
  PDFium merged the row on its own and showed no step; **the two arms
  disagreeing was itself the evidence that the row is one figure.**

**3. The cancellation, which is the real lesson.** Turning the ladder on *alone*
made c1's raw-lane `dy_p50` go **101 → 116.2** and word recall **0.797 →
0.7667**, and the gate correctly called both regressions. Nothing had broken:
removing the −11.7pt error stopped it partly hiding the +115pt one. THEORY §6
recorded the ladder as a compensator that "neither improved page counts" — true
of the ladder alone, false once the thing cancelling it was also fixed. **A
compensator that does not pay alone has not been shown not to pay.** The two
changes therefore land as one commit and are pinned together by
`tests/test_card_row_and_ladder_default.py`.

**4. The deliberate re-record.** With both fixes live the raw lane went red on
two **stale** findings — c1's `page_err` cleared 0 but was recorded as 1, and
word recall reached 0.9697 against a recorded 0.797. Same inverse failure as
2026-08-04: the gate was red *about the record*, not about quality. Re-recorded
with `GATE_BASELINE=update` and re-verified by a chained plain run that gates
against the record just written — **PASS both lanes, zero regression findings,
zero stale findings.** Every moved value improves; no floor was lowered.

| lane | page match | mean within-2pt | mean live text | median dy50 |
|---|---:|---:|---:|---:|
| product, before | 16/16 | 0.5161 | 0.9652 | 0.675pt |
| product, after | 16/16 | 0.5389 | 0.9652 | 0.62pt |
| raw, before | 14/16 | 0.3349 | 0.9652 | 2.79pt |
| raw, after | 15/16 | 0.3604 | 0.9652 | 1.975pt |

**Zero regressions across all 32 cells** (16 documents × 2 lanes); 24 are
byte-identical. c1's raw lane goes `2/3 → 2/2` pages and `dy_p50` **101.0 → 2.0**;
the arms now agree (PDFium 2.00, PyMuPDF 2.05) where they disagreed by 87pt.
Two documents moved without being targeted, and that is why this needed
adjudication rather than a quiet landing: `c4_i18n` within-2pt **0.1966 →
0.5043** in both lanes, and `l1_word_native` product `dy_p50` **14.69 → 0.01**.

**5. What is left, named so nobody re-discovers it as new.** Page 2's first
paragraph carries `space_before=1050` twips and the renderer drops `w:before` at
a page top after a hard break — **−53.4pt**, now the sole driver of c1's residual
`dy_p90`, and unfixed here because scoping it needs live Docs evidence rather
than the LibreOffice proxy. And once the vertical error is gone, **horizontal**
re-wrap drift dominates (`dx_p50` 2.62, justified lines at 25–38pt), which is why
within-2pt lands at 0.10–0.14 rather than near 1.0 despite `dy_p50` 2.0.

**Predicted, not measured:** c1's live Google Docs `dy_p50` should go **9.30 →
~2–3pt**, clearing the `c1_marginal` advisory. D-A is a structural line-count
error rather than a line-metric translation, so it ought to transfer — but per
the standing rule this is a prediction awaiting a live pass, not a result.

**A defect found while doing this, not yet fixed.** `assess` refuses the
committed evidence files. It validates the evidence shape with an exact key set,
and the stamping step that files a run into `docs/evidence/` adds a `git`
provenance key — so the archived copy of a run cannot be re-assessed by the tool
that produced it. The verdict above was therefore obtained from a copy with that
one key removed and nothing else changed:

```
docs/evidence/gdocs-2026-08-04-pass4-qualification.json  sha256 311389ab…
de-stamped copy actually assessed                        sha256 d921de1a…
```

This was deliberately *not* fixed in the same change. Loosening a strict
validator is a decision about what evidence is allowed to contain, and making it
a side effect of a ratification is exactly the mixing the standing constraints
forbid. Either the stamp belongs inside the schema or the archive should keep
the raw file beside the stamped one; that is a separate commit.

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

---

## 2026-08-05 — the ladder flip, measured on sixteen documents, was wrong about four

Canonical environment, fingerprint `3ca438f17d905cef…`. Evidence at
`docs/evidence/ladder-gating-2026-08-05.json`; raw sweep at
`docs/evidence/parity-expanded-2026-08-05e.json`.

**The mistake, stated first.** The ladder default was turned on in `c9d36df` on
the strength of a 32-cell sweep over the gated sixteen with zero regressions.
That was the wrong evidence for the change. A default that every document flows
through is not characterised by sixteen pinned documents, and
`parity-expanded-2026-08-05d` found what they could not see: four candidate-side
regressions, page drift across the y-series, and a degraded reference arm.
**A change to a global default is measured on both corpora before it lands.**

**Two failures, and the figure-merge was innocent of both.** Ablation
(`ladder` / `merge` / `both`, per document) put `merge` equal to `none` on every
affected document, so all of it is the ladder's.

*It cut text it cannot measure.* `_predictable` checked that the font FAMILY
maps to a base-14 name and never that the CHARACTERS are in that font's WinAnsi
repertoire. Measured with `get_text_length` at 11pt, base-14 resolves Latin
glyph by glyph — `aaaaaaaaaa` 48.84pt against `mmmmmmmmmm` 85.58pt — and returns
an **identical 13.75pt** for narrow and wide Cyrillic. Per character: Latin
4.95pt, Cyrillic 1.47, Greek 1.64, CJK 1.10. It was not approximating those
scripts, it was not seeing them, and it returned a number anyway.

But the rule that follows is *not* representability, because `c4_i18n`'s CJK is
equally invisible and locking it moved within-2pt 0.1966 → 0.5043. CJK is
written **without spaces**: the renderer breaks it wherever its own measurement
lands and cannot reproduce the source's break by luck, and the metric error is
uniform across the run so a width fraction still maps onto the right character.
Cyrillic and Greek break at spaces exactly like Latin, so the renderer already
reproduces the source wrap and a lock can only disturb it — `x06_lo_euro_scripts`
went dy_p50 1.5 → 13.0. So: measured text, **or** a script continuum.

*It spent page height the page had not got.* `x10_chrome_tables_plain` is the
clean exhibit: the same two locks improved dy_p50 17.2 → 1.65 and within-2pt
0.015 → 0.0991 while taking the document 2/2 → 2/3 pages and word recall 0.9963
→ 0.8657. The placement was right and the page could not hold it. Flow locks now
require the page to stay a quarter empty *after* the lock; table cells are
exempt, because there the row height is declared by the source and restoring it
is the entire point.

**Result.** Gated sixteen: **identical to the recorded baseline, to every digit**,
PASS both lanes, zero findings, no re-record. Expansion: x06, x10, x11 and x12
back to their -05c values on every named dimension; x01 keeps an improvement it
never lost; y-series page_err residual **+4 across eight documents against -05d's
+26**, with y03, y10 and y13 exactly back and y01 and y12 better than -05c.

**Two framings worth not re-chasing.** `x01` and `l1_word_native` were reported
as regressions and are not. Both had *zero absolute moves*: their parity verdicts
worsened because the **reference arm improved faster**. On l1 the candidate went
dy_p50 24.59 → 9.89 and the reference 34.99 → 8.49 — returning that document to
its -05c verdict would mean discarding a 25pt gain on both backends.

**One acceptance item not met, and why it is reported rather than fixed.**
`y10_nist_fips180`'s reference arm does not recover: word recall 0.4872 → 0.3238,
dy_p50 49.56 → 58.97, from one extra page early in a 43-page document. Five locks
survive both gates and none is wrapped prose — two are tab-separated fragments
(`(i)\t(i) j 0`), one has a 6.0pt-wide second line, two have interior line widths
varying by 180–280pt. They are definition lists and symbol tables that `infer`
flattened into paragraphs. The fix is an interior-width uniformity test — and it
was measured to also refuse `l1_word_native`'s bullet list, dropping l1's word
recall 1.0 → 0.9931 against a `gate_baseline.json` that records 1.0 in both lanes
and a standing instruction not to re-record. **Trading a gated document's recall
for an expansion document's is an adjudication, not an implementation detail.**
