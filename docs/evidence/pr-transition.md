# INT-00 — pull-request transition record

**Recorded:** 2026-07-30, before any mutation.
**Authority:** `docs/exactdoc-google-docs-production-build-plan.md` §6, INT-00.
**Purpose:** capture the exact pre-transition graph so every later step is
reversible by inspection, and so no branch or public SHA is lost.

INT-00 step 2 is a standing constraint on everything below: **no force-push, no
branch deletion, no rewritten public SHA.** Nothing in this record was produced
by a mutating command; every figure comes from `gh pr view`, `git merge-base`,
`git rev-list` and the live Actions log.

---

## 1. Baseline — the graph as found

| PR | State | Base | Head | Head SHA | Commits ahead of base | Files vs merge-base | Merge-base |
|---|---|---|---|---|---:|---:|---|
| [#1](https://github.com/ebt55/exactdoc/pull/1) | open, ready | `main` | `claude/exactdoc-execution-plan-42d13a` | `0cd7d11` | 28 | 34 | `e6993fd` |
| [#2](https://github.com/ebt55/exactdoc/pull/2) | open, **draft** | `main` | `claude/exactdoc-pr1-gate` | `6d8c47b` | 29 | 51 | `e6993fd` |
| [#3](https://github.com/ebt55/exactdoc/pull/3) | open, **draft** | `claude/exactdoc-pr1-gate` | `claude/exactdoc-pr2-backend-seam` | `5ee2651` | 1 | 16 | `6d8c47b` |
| [#4](https://github.com/ebt55/exactdoc/pull/4) | open, **draft** | `claude/exactdoc-pr2-backend-seam` | `claude/exactdoc-pr3-gate-hardening` | `50f38a0` | 5 | 39 | `5ee2651` |

`origin/main` is at `e6993fd`. PR #4 is **35 commits ahead of `main`**, which
matches the plan's §2.2 audit exactly (29 + 1 + 5 = 35).

### 1.1 Correction to the plan's own diagram

The plan's §6 graph draws PR #2 as nested under the execution-plan branch:

```text
main e6993fd
└─ execution-plan 0cd7d11       PR #1, 28 commits, green
   └─ gate 6d8c47b              PR #2
```

**Live reality: PR #2's base is `main`, not `claude/exactdoc-execution-plan-42d13a`.**
`claude/exactdoc-pr1-gate` is 29 commits ahead of `main` — the execution-plan
branch's 28 commits plus `6d8c47b` itself — so the *branch* ancestry is as
drawn, but the *pull request's* declared base is `main`.

This does not change any INT-00 instruction. The retarget in step 3 still
produces the intended seven-commit diff, verified in §2 below. Recorded because
the plan is the contract and a contract that misdescribes the starting state
should be corrected in writing rather than silently worked around.

### 1.2 CI state as found

| PR | Check | Conclusion | Run |
|---|---|---|---|
| #1 | `gate` | **SUCCESS** | [run 30480720641](https://github.com/ebt55/exactdoc/actions/runs/30480720641/job/90673840032) |
| #2 | `gate` | FAILURE | [run 30516346898](https://github.com/ebt55/exactdoc/actions/runs/30516346898/job/90786978363) |
| #3 | `gate` | FAILURE | [run 30516356886](https://github.com/ebt55/exactdoc/actions/runs/30516356886/job/90787010158) |
| #4 | `gate` | FAILURE | [run 30519997999](https://github.com/ebt55/exactdoc/actions/runs/30519997999/job/90798038765) |

---

## 2. Verification of the proposed retarget (step 4, computed in advance)

Retargeting PR #4 from `claude/exactdoc-pr2-backend-seam` to
`claude/exactdoc-execution-plan-42d13a` was modelled with `git merge-base` and
`git rev-list` before being requested:

```text
merge-base(execution-plan, pr3-gate-hardening) = 0cd7d11
commits in 0cd7d11..50f38a0                    = 7
files changed across that range                = 56
```

**The seven commits, in order:**

| # | SHA | Subject |
|---:|---|---|
| 1 | `6d8c47b` | gate: make green mean green -- fail-closed evidence, and one product profile |
| 2 | `5ee2651` | backend: the permissive runtime boundary -- convert with PyMuPDF absent |
| 3 | `952f7a9` | gate: close audit-found false-green paths |
| 4 | `1893d34` | parity: attribute both unwaived regressions, and scope floors to their profile |
| 5 | `d41bf57` | corpus: freeze the 16 inputs, and make "canonical" mean an exact toolchain |
| 6 | `d1f9781` | fonts: pin what the renderer can see, and re-record against it |
| 7 | `50f38a0` | docs: record the confirmed CI state -- green except parity, lanes bit-identical |

This satisfies the step 4 exit condition — exactly seven commits — and the
merge-base is `0cd7d11`, PR #1's head, confirming no commit from the older
28-commit plan is pulled in.

**The 56 files, by area** (step 4 also requires that no unexpected file from the
28-commit plan appears):

- packaging/CI/meta (3): `.gitattributes`, `.gitignore`,
  `.github/workflows/gate.yml`
- docs (4): `README.md`, `ROADMAP.md`, `STATUS.md`, `THEORY.md`
- package (12): `exactdoc/` — `__init__`, `backend`, `cli`, `convert`,
  `docxout`, `ladder`, `metrics`, `options`, `parse_pdfium`, `refine`,
  `targets`, `verify`
- scripts (2): `scripts/bootstrap.sh`, `scripts/fonts.conf`
- testkit code/policy (17): incl. `backend_parity.py`, `corpus_manifest.py`,
  `corpus_manifest.json`, `gate.py`, `gate_baseline.json`,
  `parity_policy.json`, `runall.py`, `evidence.py`, `_paths.py`
- frozen corpus (16): `testkit/fixtures/*.pdf` — the 16 SHA-256-pinned inputs
- tests (3): `test_corpus_generation.py`, `test_gate_mutations.py`,
  `test_no_pymupdf.py`

All 56 are accounted for by the gate/backend/corpus/font work the seven commits
describe. No unexplained file.

---

## 3. Verification of the parity claim (step 5)

The plan's §2.2 and §2.3 assert that PR #4's body understates its own CI
failure: five parity failures, not two. **Confirmed against the live log** of
run 30519997999, step "Backend parity - the licence-swap verdict":

```text
2 regression(s), 5 same, 3 better, 2 expected-divergence, 4 accepted, 0 missing
  regression    05_memo.pdf          worse on dy_p50: 0.59 -> 1.89
  below-floor   c4_i18n.pdf          doc_recall 0.9748 against a ratified floor of 0.9874
  below-floor   c4_i18n.pdf          dy_p50 0.8 against a ratified floor of 0.15
  below-floor   c4_i18n.pdf          within2pt 0.3017 against a ratified floor of 0.5745
  regression    f1_fpdf_brief.pdf    worse on dy_p50: 0 -> 1.2
FAIL
```

Five failing lines: two `dy_p50` regressions plus three `c4_i18n` below-floor
dimensions.

Two consequences worth recording separately:

1. **`ROADMAP.md` is wrong on this point too.** Its §"CI status" says the parity
   gate "fails on exactly the two unwaived regressions and nothing else." The
   three `c4_i18n` below-floor failures are not mentioned. The roadmap's own
   tally line (`2 regressions, 5 same, 3 better, 2 expected divergences, 4
   accepted`) is accurate as a *verdict* count but omits the floor breaches,
   which are a separate failure class and are what makes the count five.
2. **The breached floors are labelled `ratified`, and they are stale.** The
   `c4_i18n` floors (`doc_recall` 0.9874, `dy_p50` 0.15, `within2pt` 0.5745)
   were recorded before `d1f9781` pinned the font set. `c4_i18n` is the CJK +
   Arabic + Hebrew document, so it is precisely the document a font-environment
   change moves. This is the policy/environment debt DET-02 must remeasure — not
   waive, and not re-record as a new waiver for `05_memo` or `f1_fpdf_brief`.

---

## 4. Transition steps — status

Owner authorized steps 3–8 in full on 2026-07-30, including the merge to `main`.

| Step | Action | Status |
|---:|---|---|
| 1 | Record base/head/SHA/merge-base/counts/files/CI for #1–#4 | **done** — §1 |
| 2 | No force-push, no branch deletion, no rewritten SHA | **honoured** — verified §4.1 |
| 3 | Retarget #4 → `claude/exactdoc-execution-plan-42d13a` | **done** |
| 4 | Verify #4 shows exactly the 7 commits | **done** — GitHub computed 7 commits / 56 files, matching the §2 prediction exactly |
| 5 | Rename #4, correct body to five parity failures | **done** — §4.2 |
| 6 | Cross-link then close #2/#3 as superseded; keep branches | **done** — both commented and closed, branches kept |
| 7 | Merge #1 with a **merge commit** so `0cd7d11` stays an ancestor | **done** — merge commit `2d2a1d4` |
| 8 | Retarget #4 → `main`; re-verify 7 commits | **done** — base `main`, 7 commits, 56 files, merge-base `0cd7d11` |
| 9 | Contingency if #1 is squash/rebase-merged | **not needed** — §4.3 proves a real merge |
| 10 | Leave #4 draft and red until DET-02 and DEC-D2 land | **holding** — #4 is still draft, still red |

### 4.1 Step 2 verification — nothing lost

`git ls-remote --heads origin`, after all mutations:

```text
0cd7d11  claude/exactdoc-execution-plan-42d13a
6d8c47b  claude/exactdoc-pr1-gate
5ee2651  claude/exactdoc-pr2-backend-seam
50f38a0  claude/exactdoc-pr3-gate-hardening
50f38a0  claude/exactdoc-production-readiness-28974a
e6993fd  main            <- now 2d2a1d4, see §4.3
```

All six branches present. Every pre-transition SHA still reachable at the same
ref. Closing #2 and #3 used `gh pr close` without `--delete-branch`.

### 4.2 Step 5 — what was corrected in #4

Title is now *"production foundations: a gate that can fail, a permissive backend
seam, and a pinned environment."* Three false statements were removed from the
body:

| Was | Now |
|---|---|
| "Stack 3 of 3, based on PR 2" | combined seven-commit PR based on PR #1's branch, superseding #2/#3 |
| "the parity gate now fails on 2 unwaived regressions" | five failing lines: 2 unwaived `dy_p50` regressions **plus** 3 `c4_i18n` below-floor dimensions |
| "**GitHub Actions has not yet run these commits.**" | run 30519997999, quoted verbatim with both lane results |

Added: a "known-remaining, deliberately not fixed here" section naming the stale
`c4_i18n` floors, the `ratified`-vs-provisional mismatch in the policy JSON, the
two unwaived regressions, and `ROADMAP.md`'s incorrect claim.

### 4.3 Step 7 — the merge was a real merge

```text
$ git rev-list --parents -1 origin/main
2d2a1d47f5a744f7e44ef913a83d3b3c0d86f35a  e6993fdb8275bad10d4c91b1e97633b970630105  0cd7d11d546f3227e1fa2bfd01e6ac650a1ef5c6

$ git merge-base --is-ancestor 0cd7d11 origin/main
(exit 0 — ancestry preserved)
```

Two parents: the old `main` tip `e6993fd` and PR #1's head `0cd7d11`. Not a
squash, not a rebase. `main` is now `2d2a1d4`.

---

## 5. Exit gate — met

- [x] #1 merged with ancestry preserved (`0cd7d11` is an ancestor of `main`)
- [x] #4's seven-commit diff against the execution-plan branch verified (§2)
- [x] #4's seven-commit diff against `main` verified after step 7 (7 commits, 56 files, merge-base `0cd7d11`)
- [x] #4 title/body match the live run, including five parity failures
- [x] CI state and known failures recorded from the live run (§1.2, §3)
- [x] no branch lost, no commit rewritten

**INT-00 complete.** #4 remains draft and red by design; DET-02 is what makes its
executable policy honest.

### 5.1 Final graph

```text
main 2d2a1d4  (merge of e6993fd + 0cd7d11)
└─ PR #4  claude/exactdoc-pr3-gate-hardening 50f38a0  → base main, 7 commits, draft, red

closed, branches kept:
   PR #2  claude/exactdoc-pr1-gate         6d8c47b   (= #4 commit 1 of 7)
   PR #3  claude/exactdoc-pr2-backend-seam 5ee2651   (= #4 commit 2 of 7)
merged:
   PR #1  claude/exactdoc-execution-plan-42d13a 0cd7d11
```
