# exactdoc status

This is the current measured state. The corpus is 16 frozen fixtures pinned by
SHA-256; canonical figures come from the pinned Linux/LibreOffice environment.
Regression baselines answer “did this get worse?” They are not an absolute claim
that every document meets release quality.

## Shipping quality

The shipping product remains quality-first:

```text
pdfium/standard/libreoffice/refine3@240dpi
```

`raw` is PDFium/standard with the refinement loop off. **PDFium is core; PyMuPDF
is optional through `[mupdf]`** — the licence migration landed 2026-08-06 and
inverted that pair.

| Canonical profile | Page match | Mean within 2pt | Mean live text | Median dy50 |
|---|---:|---:|---:|---:|
| product | 16/16 | 0.5241 | 0.9588 | 1.15pt |
| raw | 15/16 | 0.3471 | 0.9588 | 1.95pt |

Measured 2026-08-06 in the canonical environment, fingerprint `3ca438f1…`; both
lanes PASS. Evidence:
`docs/evidence/parser-default-flip-2026-08-06.json`.

**These numbers are the re-recorded baseline and are slightly worse than the
pre-flip ones** (product `<2pt` 0.5389 → 0.5241, `dy50` 0.62 → 1.15; raw 0.3604
→ 0.3471 and 1.975 → 1.95; page match unchanged in both lanes). The record was
re-recorded because `profile_id` changed with the default parser, which makes
the old one a description of a configuration nothing ships. All 32 per-document
movements reproduce the ratified parity record to the digit, and a control
confirmed the old parser still reproduces the old record exactly from this tree,
so the movement is the parser and nothing else.

**Two caveats these figures carry and cannot express.** The measurement
environment installs the `[mupdf]` extra to run the parity reference arm, and
the quality ladder needs that extra, so a default install produces different —
worse — output on `c1_whitepaper`, `l1_word_native` and `c4_i18n`; see the
licensing section below. And `profile_id` has no text-metrics axis, so nothing
in the name above says which of the two configurations was measured.

Product page match reached 16/16 on one document: the striped-table assembler
took `c3_tables` from one page out to exact, and its word recall 0.331→0.9359
with it. Separately, the two-column right-edge fix took `c2_paper2col` median dy
29.2→0.85pt and within-2pt 0.1948→0.4857 — placement, not pagination. Raw page
match moved 13/16→14/16; its two remaining mismatches are `c1_whitepaper` and
`c5_graphics`. Raw median dy50 2.2→2.79pt is the c3 word population reordering
the median rather than a placement regression: raw c3 word recall moved
0.3137→0.8648 and its dy50 2.5→7.45pt with it.

**The gate baseline was deliberately re-recorded** (`29945f2`) as part of that
run. The committed `c3_tables` records had gone stale — the assembler had
already improved the document and the gate refuses a record that no longer
describes reality. Attribution was checked before re-recording, not assumed:
with the new inference rules disabled the `c3` output is byte-identical, so the
movement is the assembler's and nothing else's. A re-record is a claim that the
new numbers are the true ones; the before/after diff above is that claim's
evidence.

Known product limitations remain:

- Complex/nested table layouts remain deferred. The ordinary striped long table
  in `c3_tables` is now assembled as one editable table.
- D10 rasterised text regions in `c5_graphics`, `04_exec_brief` and — since the
  parser flip — `c4_i18n`, whose complex-script runs PDFium rasterises where
  PyMuPDF kept them live (`live_text_cov` 1.0 → 0.9091, `raster_frac` 0.0 →
  0.0909). Ratified as a D10 shortfall on 2026-08-04 under DEC-D2, on Google
  evidence rather than the LibreOffice proxy, and carried into
  `gate_baseline.json`'s `shortfall_defects` when the baseline was re-recorded.
  The gate refused to pass until it was written down, which is the check working.
- Heavy LaTeX and highly designed/vector pages are deferred; image-only scan/OCR
  PDFs are explicitly rejected as OCR-required rather than silently converted.

The project prioritises ordinary digital text, multi-column pages, common
tables, and i18n. A rasterised figure can be the honest fallback for a designed
region, but its text is counted as non-live by the quality metrics.

## Migration gates: all four MET, migration complete

| Gate | Status | Evidence |
|---|---|---|
| **(a)** expanded same-profile parity, no unratified regressions | **MET** 2026-08-05 | `docs/evidence/parity-expanded-2026-08-05f.json`, closed at commit `a3dd2ef`. Zero unratified findings across all four adjudication paths. |
| **(b)** two clean consented full-corpus Google Docs passes | **MET** 2026-08-04 | Passes 4 and 5, both assessed clean under the ratified policy. |
| **(c)** no-PyMuPDF / base-wheel proof | **MET** 2026-08-06 | `docs/evidence/base-wheel-proof-2026-08-06.json`. Wheel built from the flipped tree, installed into a virtualenv that never had PyMuPDF: 8 packages with no copyleft term, 25/25 modules importing, 16/16 gated fixtures converting, suite green (482 run, 46 skipped, 0 failed). The PyMuPDF seam is **empty**. |
| **(d)** dependency, provenance and licence audit | **first pass** | `docs/license-audit.md`. §10 items 1, 2, 4, 5 and 8 remain open and did not close with the migration. |

The migration itself is done: PDFium is the core parser and default backend,
PyMuPDF is the optional `mupdf` extra, the gate baseline was re-recorded at the
new profile identity, and the licence is Apache-2.0. Commits `900f0ab`,
`f457567`, `017c1e1`, `160b831`.

**Four of four gates is not a release**, and the remaining work is release work
rather than migration work:

1. **A post-flip live Google Docs qualification pass.** Gate (b)'s two clean
   passes were measured on the pre-flip tree. The parser default has changed
   since, and the standing rule here is that a gdocs-profile claim is never
   promoted on LibreOffice-proxy evidence alone — so the live numbers must be
   re-established against Google's own exports. Consent-gated, per pass.
2. **`verify.py`.** Outstanding and unchanged by this work.
3. **Packaging.** The wheel builds and installs correctly (gate (c) proves it),
   but nothing is published, and the base-wheel proof is Linux-only while
   pypdfium2 ships per-platform binaries.
4. **A permissive text shaper**, so the quality ladder works without the AGPL
   extra. See the licensing section: this is the sharpest of the four, because
   without it the *default* install is worse than the measured one on the
   exemplar document.

## The Google Docs output profile — not shipping

`PDFIUM_GDOCS_CANDIDATE` names the explicit non-shipping profile. The parser in
that name is now simply the default; what makes the profile non-shipping is the
pair of axes after it — Google-safe serialisation with the correction loop off:

```text
pdfium/gdocs/none/refine0@240dpi
```

Both arms of the 2026-08-04 same-profile run, 16 documents, scored against the
LibreOffice proxy. The absolute numbers mean little on their own — this is a
Google-Docs output profile graded by a renderer that is not Google — so the
reference arm is shown beside the candidate, because the gap between them is the
only thing parity actually measures:

| Same-profile arm | Page match | Mean within 2pt | Mean live text | Median dy50 |
|---|---:|---:|---:|---:|
| candidate (PDFium) | 15/16 | 0.0694 | 0.9566 | 13.78pt |
| reference (PyMuPDF) | 14/16 | 0.0712 | 0.9652 | 13.27pt |

The `candidate-refined` diagnostic profile was not remeasured on 2026-08-04, so
its earlier figures are not carried forward here. The candidate-arm row above is
derived from that day's evidence and therefore **predates `c1cbc2a`**, which
improved `c2_paper2col` on four dimensions; no canonical parity run has been
recorded against the newer tree, so the aggregates are not restated from a
partially updated set.

Same-profile PDFium/PyMuPDF parity is **7 regressions, 6 same, 3 better** as
raw measurement — `--measure` runs with empty margins, which is what makes every
movement visible and is not the adjudicated verdict. The 2026-08-04 evidence
recorded 8/6/2; `c1cbc2a` then retired one. The composition matters more than
the count:

- `c7_code` is now **same**. It was a material regression; the Google-Docs cell
  margin fix closed it, and every compared dimension is now identical.
- `c1_whitepaper` is now **better than the reference** — page error 1 against 0,
  word recall 0.8273 against 0.9697, and both placement dimensions with them.
- `c2_paper2col` entered the list and then left it again on the same day. It
  entered because the *incumbent* improved: the right-column-edge fix landed for
  both arms and PyMuPDF took more of it, 0.1039 within-2pt and 10.05pt median dy
  against the candidate's 0.0131 and 23.55pt. It left when `c1cbc2a` absorbed a
  superscript into its host line in the PDFium parser instead of leaving it a
  line of its own — dy 23.55→10.00 and within-2pt 0.0131→0.1247, with live text,
  word recall and raster fraction all reaching the reference exactly. The
  episode is the harness working as intended: a candidate that stands still
  while the incumbent improves is a candidate that got worse, and saying so
  found a real parser defect.
- Plain memo placement is no longer a regression: `05_memo` is better on median
  dy, 13.36→7.36pt.

Applying `testkit/parity_policy.json`, now bound to the full profile, leaves
**no unwaived regressions and two tracked provisional findings**: complex
scripts (`c4_i18n`) and designed-page rasterisation (`c5_graphics`). The other
raw movements sit inside the policy margins and are not divergences it tracks.
Provisional means visible, bounded and attributed — it does not mean accepted.
Nothing is ratified, so the policy cannot report a pass by construction. **The
candidate is not adopted and is not releasable.**

A general bottom-margin relief fixed the candidate's `c1_whitepaper` and
`c2_paper2col` overflow; the candidate now matches page count on 15 of 16
fixtures, one better than the PyMuPDF reference at the same profile, whose
`c1_whitepaper` is still a page out. It intentionally does not treat
`c5_graphics` (designed graphics) as a margin problem — that document is a page
out under both backends. Complex/nested tables remain an explicit candidate
limitation.

## Google Docs qualification

The packaged user CLI is `exactdoc-gdocs` (install `.[gdocs]`; for example,
`exactdoc-gdocs auth`). It provides authentication, cleanup attempts for created
Drive objects, orphan-ledger blocking, and safe evidence handling. Testkit
qualification separates preparation from a consented upload:

```bash
python testkit/gdocs_oracle.py prepare <dir>
python testkit/gdocs_oracle.py run <dir> --allow-cloud-upload
```

`prepare` is offline and hash-binds the exact candidate. `run` is the upload
operation and separately reports operational success and quality success. Drive
objects are always cleanup-attempted; an orphan ledger blocks continued work.

**Four consented full-corpus passes ran on 2026-08-04** for
`pdfium/gdocs/none/refine0@240dpi`. Every one was operationally clean — 16
attempted, 16 succeeded, zero failed, no `.gdocs_orphans.json` — and blocking
quality findings fell across the day:

| pass | blocking findings | what cleared | evidence |
|---|---:|---|---|
| 1 | 11 | — (the 3pt boundary compensation regressed it from 7) | `gdocs-2026-08-04-qualification.json` |
| 2 | 4 | the boundary-compensation retirement | `…-pass2-qualification.json` |
| 3 | 3 | `l1_word_native` dy 15.19→1.93pt | `…-pass3-qualification.json` |
| 4 | **1** | `l1` dx 39.82→1.35pt, `c2_paper2col` SSIM 0.6772→0.7087 | `…-pass4-qualification.json` |

The two that cleared in pass 4 cleared for named, measured reasons, not drift.
`l1_word_native`'s horizontal drift was a font-substitution error: adopting
Libre Baskerville, chosen from Docs-measured metrics, landed its packing
prediction of 1.0004 against the source pitch. `c2_paper2col` cleared its SSIM
bound on a 1.0pt scoped section-break compensation, beating the ~0.69 raw-proxy
extrapolation. Twelve of the thirteen blocking `ordinary_digital` fixtures now
clear every threshold unaided.

The qualified conservative striped-table assembler makes
the `c3_tables` long table one editable 46-row × 4-column DOCX table, IDs 1–45
exactly once, and paginates it naturally without inventing a repeating header.
It also consolidates the 5-row `c1_whitepaper` comparison table. It rejects
ambiguous multiline content, cards, and callouts and coalesces pages only at an
edge with matching geometry; it does not claim to solve complex/nested regional
tables. Local LibreOffice review was indicative only; the 2026-08-02 live run
showed `c3_tables` 3→3 rather than 3→4, live 0.9226/doc recall 0.9359 unchanged,
word recall 0.3120→0.8215, within-2pt 0→0.1076, SSIM 0.5785→0.7573, and IoU
0.0973→0.1448. dy50/dy90 are 2.94→7.85pt and 80.52→103.34pt because the table
now matches many more words. Visual review found all 45 rows in an editable
continuous three-page table; row distribution differs from the source.
`c1_whitepaper` remains 2→2 with live/document/word recall
0.9654/0.9697/0.9697 and dy50/dy90 9.30/54.79pt unchanged; within-2pt,
SSIM, and IoU have tiny 0.0719→0.0688, 0.8006→0.7993, and 0.1568→0.1563
tradeoffs. PDFium preserves stretched literal interword spaces, removing the
`01_whitepaper_market` word staircase; shipping PyMuPDF output is unaffected.

`testkit/gdocs_quality_policy.json` defines blocking ordinary documents, tracked
designed-stress documents, unsupported-input refusal, exact metrics, and
explicit owner ratification. The offline `assess` command hash-binds its source
evidence and never performs a cloud operation.

**The policy is now ratified** (schema v3), by the repository author on
2026-08-04, carrying **one bounded waiver**: `01_whitepaper_market` `mean_ssim`,
floored at 0.65 against a measured 0.6589. Assessed against pass 4, the result
is `operational_pass: true`, `quality_pass: true`, **`overall_pass: true`**,
zero blocking findings. The waiver is *reported*, not hidden — the finding still
appears as `waived` and the tier still says it has one.

The waiver is deliberately narrow, and the schema enforces the narrowness rather
than trusting the prose:

- it covers **one metric on one document**. `01` would still block on drift,
  recall, coverage or pagination — waiving a metric is not waiving a document;
- it is **floored**, not open-ended. Below 0.65 the finding blocks again;
- it **expires by mechanism**. If `01` reaches the 0.70 bar unaided the waiver
  becomes a `stale-waiver` and blocks every assess until the entry is deleted,
  so retirement is enforced rather than remembered.

Its cause is probe-measured, not inferred: Docs adds space above a page-leading
cover band unconditionally (requested top margins `[0, 4, 8, 14.4, 20]` rendered
as `[14.55, 18.83, 22.83, 29.23, 34.83]` — an addition, not a clamp). The writer
compensates what is compensable; pass 4 records the remainder as a ~14.6pt band
floor, with two residual fixable causes filed — a missing 4pt accent bar and a
~2pt band-to-body gap. `01` clears page match, live text, both recalls and both
drift bounds on the same pass, so this is a visual-registration cost rather than
a conversion defect. The three stress fixtures produce eight tracked
non-blocking findings, unchanged.

**Migration gate (b) is now MET**: passes 4 and 5 both assess clean under the
ratified policy. That is the two consecutive clean full-corpus Google passes the
gate asks for — and it is one gate of four, not a release.

### Migration gate (a) is GREEN — every finding ratified, none unaccounted

As of 2026-08-05, bound to `docs/evidence/parity-expanded-2026-08-05f.json`, all
four adjudication paths run clean:

| path | policy | result |
|---|---|---|
| gated 16 / candidate | `parity_policy.json` | 0 regressions, 4 ratified, `ok=True` |
| gated 16 / shipping | `product_parity_policy.json` | 0 regressions, 4 ratified, `ok=True` |
| expansion / candidate | `expansion_parity_policy.json` | 11 MAJOR, all 11 ratified, 0 policy failures |
| expansion / shipping | `expansion_parity_policy.json` | 7 MAJOR, all 7 ratified, 0 policy failures |

**Zero unratified findings, zero stale entries, zero floor breaches.** That is
gate (a) answered from enforced data rather than from a reading of the evidence:
every number came out of the adjudicators themselves, and each of the 26
document×profile entries cites the binding measurement it was floored against.

Three artifacts, because a policy binds to one profile and one corpus:
`parity_policy.json` (gated 16, candidate), `product_parity_policy.json` (gated
16, shipping settings — new, read through the existing
`backend_parity.py --profile product --policy …` with no new machinery), and
`expansion_parity_policy.json` (29 expansion documents, both profiles, read by
`expansion_policy.py`). None of them can be read as another; the readers refuse
cross-binding in every direction.

**Ratified is not fixed.** Every entry is a real divergence, floored in both
directions and stale-checked, so clearing one fails until the entry is deleted
and worsening past a floor fails immediately. Three dissolutions are recorded as
dissolutions rather than quietly dropped: `c5_graphics` left the gated policy
because the backends stopped differing there at all, `c1_whitepaper` because
`c9d36df` fixed the two defects that were hiding each other on it, and
`x02_lo_report_toc` because its divergence is gone. `y10` deliberately has **no**
candidate-profile entry — it reads `minor` there only because the reference
degraded (the adjudicated #44 trade), and an entry would have disguised that as
candidate health.

Two classes worth naming, because both look like regressions and neither is.
**Reference-improved-faster** (`l1_word_native`, `x01`): both arms improved
substantially — l1 by ~25pt on each side — and the gap widened because the
*reference* improved more. The candidate's absolute value is the best it has
measured; x01's candidate within2pt of 0.3160 beats the pre-improvement
reference's 0.2132. Their review conditions are written against *absolute*
regression so an improving candidate can never be used to hide a real loss later.
**Token artifact** (`y03`, `y10`, `x03`): `word_recall` counts tokens at the same
page index, so on a paginating document it largely restates pagination. y10 is
99.3% artifact — the reference itself scores 0.807 on tokens against 0.9984 on
characters — and y03 is 93%, with its 48 genuine absences named as U+23A2/U+23A5
bracket pieces, 0.37% of one non-gating document, fix declined on risk against
value with the c7 regression as precedent.

`05_memo`'s waiver bar was removed, and it is worth recording why rather than
just that. The guard held through three batches and stopped the last one: the
ratification arrived, the guard refused, and the decision went back to the owner
instead of being taken by an edit. It was then granted explicitly. The entry
exists because someone with the authority said so, which is what the guard was
built to force. `f1_fpdf_brief` keeps its bar, because no such decision has been
made about it.

### Parity policy ratified, and the dy threshold artifact resolved

The **parity** policy is now ratified too (2026-08-04, DEC-D2, on the Google
evidence rather than on the LibreOffice proxy, which is what its own scheduling
note required). Its two D10 findings — `c4_i18n` complex-script raster fallback
and `c5_graphics` designed-page rasterisation — moved from `provisional_shortfalls`
to `ratified_shortfalls`, each carrying an owner, a date, `DEC-D2`, and a review
condition. Ratified is not fixed: both remain real divergences, both remain
floored in both directions, and clearing either entirely still fails as a stale
record. What changed is only that they can no longer block a swap by themselves.

A `dy_p50` **absolute-magnitude exemption** landed with it, resolving task #22's
decision item. `dy_p50` is computed on glyph tops, and PyMuPDF reads the declared
base-14 ascent (Helvetica 1.070–1.075 em) where PDFium substitutes a generic
~0.905 em — an apparent offset of ~0.17 × type size, 1.8pt at 10.5pt, **with the
baselines identical**. Near zero, `dy_p50`'s proportional margin collapses to its
0.5pt floor, so documents moved 0.04→1.29pt and were graded regressions over a
fraction of one line's leading. The rule: a `dy_p50` delta is not a regression
when both arms are under 2.0pt, *provided* `within2pt` did not move adversely on
the same document. The metric definition deliberately stays glyph-tops —
redefining it would invalidate the gate baseline, this policy's floors and every
live-pass record simultaneously, to correct a reporting convention that moves
nothing a reader sees. See [docs/dy-ascent-artifact.md](docs/dy-ascent-artifact.md).

The condition is doing real work, not decorating the rule. Five gated base-14
documents sit inside the 2.0pt ceiling at the shipping settings; the exemption
clears **three** — `01_whitepaper_market`, `05_memo`, `f1_fpdf_brief`.
`02_research_paper` and `03_tech_report_code` are held back because their
`within2pt` collapses 0.7614→0.5685 and 0.4602→0.2803, far outside its 0.08
margin: the dy framing was masking a real placement regression on those two, and
they keep a MAJOR verdict on `within2pt` either way. The ceiling must not be
raised — absorbing the next divergences up would need ~13pt, ~17pt, ~21pt and
~68pt, which would blind the policy to four genuine structural divergences.

So of the eight documents in the 8/16 shipping-placement figure — which was the
backend-swap comparison, not the shipping product's own quality — three clear on
the exemption, `02`/`03` remain on `within2pt`, `c1` and `r1` are real and
tracked as task #29, and `c4_i18n` is the ratified tracked divergence.

### The pagination campaign: closed, and exonerated

The long-document pagination campaign is **closed**. Seven mechanisms landed,
and the page-count improvements are large: `y01` 158→92 pages against an 80-page
source, `y02` 314→142, `y09` 116→64, with `y13` gaining 32 pages of correction
and `y12` 55 on a one-line wrap margin. U+0002 hyphen recovery landed alongside
it, taking `y12`/`y13` recall past 0.996, and a `candidate_profile_id` mislabel
in the parity tooling was fixed. The expanded-parity snapshot for 2026-08-05 is
committed with its full regression list.

**It is also exonerated, and that took ablation rather than argument.** The
candidate-arm regressions on `y01`/`y09`/`y03` looked like campaign fallout and
are not: reverting `parse_pdfium.py` alone restores the −04b page counts exactly
(109/68/72), reverting all of the campaign's `infer`/`docxout` changes moves
nothing at all, and disabling the campaign's margin guard makes `y01` markedly
**worse** (114→162). The campaign's mechanisms measurably help the candidate
arm. The actual culprits are three recent PDFium parse commits — `ff84556`
list-marker split, `d3df9a0` gutter exemption, `0e96d64` hyphen — each of which
fixed a real defect, so the answer is parse-side refinement, not revert.

Migration remains blocked on, all in flight unless noted:

- **task #31, pdfium line-count inflation from the parse fixes**
  (`y01`/`y09`/`y03`/`y02`), now merged with **#34** (`y17`/`x10`/`x07`
  segmentation) and `y13`'s gutter-crossing rate into a single **pdfium
  line-segmentation convergence campaign**, owned by the pagination agent;
- **#33** `y06` writer-path OOM;
- **#28** `x03` markers;
- **#27** `y03`/`y10` recall.

Local follow-up now canonicalises only corroborated leading OpenSymbol private-use
bullets into safe Unicode list markers. `l1_word_native` becomes three separate
editable hanging-indent items; no other prepared DOCX part changes anywhere in
the 16-document corpus. LibreOffice proxy recall/drift/SSIM improve, but the
committed assessment remains the last live Google truth until fresh consent.

The `c2_paper2col` margin blocker — an inset abstract winning right-margin
inference over the verified right-column edge, narrowing the content area by
about 42pt and shifting the second column left by about 21pt — has a landed fix
(`ff518be`). Against the LibreOffice proxy it is a large move: product `c2`
median dy 29.2→0.85pt and within-2pt 0.1948→0.4857, and raw `c2` median dy
26.8→4.0pt.

The same commit also introduced `GDOCS_PARA_BOUNDARY_COMP_PT = 3.0`, and that is
what took the live pass from seven findings to eleven. It has been **retired**
(`41e8e7f`) on remeasurement against Google's own exported PDFs: across 187
single-column boundaries in 12 documents, Docs' own contribution at a paragraph
boundary is about **+0.10pt**, not 3pt. Boundaries given the full compensation
rendered a gap 2.90pt *smaller* than the source — Docs honoured the subtraction
and gave nothing back, so the space was lost once per boundary and accumulated
down the page. `c6_long` carries 17.4 boundaries per page and drifted 25.84pt.
The earlier ~3pt reading came from probes written with `lineRule="exact"`, which
this profile already retranslates, so the compensation double-counted the same
height. Heading (+0.75pt) and table (+1.04pt) residuals are real but sit at the
writer's own half-point quantisation noise floor and are recorded rather than
applied.

A column-aware counterfactual predicts eleven of thirteen ordinary documents
inside the 10pt bound, with `c1_whitepaper` marginal and `l1_word_native`
carrying a separate cause. **That is a prediction, not a measurement.** Two
parser fixes landed alongside it — superscript absorption (`ebcb3be`) and
annotation-based links (`bb1687d`, which moved no metric) — and the standard
profile is verified byte-identical throughout, so the shipping lanes cannot have
moved. The 2026-08-04 live findings remain the live truth until a fresh
consented run replaces them; nothing here retires them.

## Conversion safety, batch, and scan handling

Encrypted PDFs map to an unsupported-input error. Malformed or truncated PDFs
map to parse errors. Writer and refinement candidates remain private until DOCX
structural validation succeeds; only then is an existing destination replaced
atomically. Failures preserve existing bytes and do not leave predictable
adjacent `.best` artifacts.

The CLI keeps positional single-file conversion and adds deterministic serial
batch conversion: `exactdoc --input-dir pdfs --out-dir docx --recursive
--result-json batch.json`. It discovers PDFs case-insensitively, preserves
relative paths, avoids symlinks/output subtree, requires `--overwrite` for
existing outputs, and atomically publishes a privacy-safe result JSON. It caps
files at 500 documents, 250 pages/document, 2,000 pages/run, and 250 MiB/file.
`--workers` currently accepts only `1`; it does not pretend to parallelise.
Google cloud qualification is rejected for batches.

`--scan-only` and normal conversion use a conservative local detector. Only
high-confidence image-only scans are rejected as OCR-required; mixed documents
proceed and blank/digital/mixed are distinguished. No OCR engine is included.
All 16 frozen fixtures avoid false OCR-required classification.

## Verified local checks

The current working tree passes 99 native `unittest` tests (2 platform skips),
the gate mutation suite (83 cases, all clear), the batch suite (14 pass, 1
Windows symlink skip), corpus purity (16/16), the no-PyMuPDF PDFium smoke check,
atomic-output checks, and the 16-entry corpus manifest check. These are local
verification results, not canonical LibreOffice or Google qualification
evidence.

## Licensing and release strategy

**The project is Apache-2.0 as of 2026-08-06.** PDFium via pypdfium2 is the core
dependency and the shipping backend; PyMuPDF moved to an optional `mupdf` extra
and is still the reference arm every parity measurement is written against. A
default `pip install exactdoc` resolves eight packages, none carrying a copyleft
term. Apache-2.0 was chosen because its patent grant and business-friendly terms
better suit the intended distribution.

All four migration gates were met before the switch: expanded same-profile
parity ratified with zero unratified findings (`a3dd2ef`), two clean consented
Google Docs passes, the base-wheel proof
([docs/evidence/base-wheel-proof-2026-08-06.json](docs/evidence/base-wheel-proof-2026-08-06.json)),
and the dependency/provenance/licence audit
([docs/license-audit.md](docs/license-audit.md)).

**Three things the switch did not do, listed here because a completed migration
is exactly where they would otherwise vanish:**

1. **No legal review has happened**, and LIC-01 — the provenance of the initial
   source itself and the right to relicense it — is untouched and still called a
   hard blocker. Apache-2.0 in `LICENSE` does not settle either. This is project
   strategy, not legal advice.
2. **The default install is measurably worse than a `[mupdf]` one.** The quality
   ladder is on by default and needs base-14 text metrics that only MuPDF
   supplies in this tree, so a base wheel runs an inert ladder: `c1_whitepaper`
   raw-lane `within2pt` returns to 0.0000 and `dy_p50` to 13.49 (against 0.1031
   and 2.00 with the extra), `l1_word_native` `dy_p50` 3.31 → 11.04, `c4_i18n`
   `within2pt` 0.4397 → 0.3017. The other 13 documents are identical. c1 is the
   standing exemplar for the ordinary-document release bar, so this is a release
   blocker in all but name; the fix is a permissive shaper in
   `exactdoc/metrics.py`.
3. **The canonical numbers describe the `[mupdf]` configuration**, because the
   measurement container installs the extra to run the parity reference arm, and
   `profile_id` carries no text-metrics axis to say so.

## Reproduce safely

```bash
bash scripts/bootstrap.sh --strict
python testkit/corpus_manifest.py verify
python testkit/runall.py
```

Use `testkit/runall.py --absolute` for release qualification, not the ordinary
regression check alone. Never re-record canonical numeric evidence from a local
machine or to silence a failure.
