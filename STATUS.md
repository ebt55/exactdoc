# exactdoc status

This is the current measured state. The corpus is 16 frozen fixtures pinned by
SHA-256; canonical figures come from the pinned Linux/LibreOffice environment.
Regression baselines answer “did this get worse?” They are not an absolute claim
that every document meets release quality.

## Shipping quality

The shipping product remains quality-first:

```text
pymupdf/standard/libreoffice/refine3@240dpi
```

`raw` is PyMuPDF/standard with the refinement loop off. PyMuPDF is core;
PDFium is optional through `[pdfium]`.

| Canonical profile | Page match | Mean within 2pt | Mean live text | Median dy50 |
|---|---:|---:|---:|---:|
| product | 16/16 | 0.5161 | 0.9652 | 0.675pt |
| raw | 14/16 | 0.3349 | 0.9652 | 2.79pt |

Measured 2026-08-04 in the canonical environment, fingerprint `3ca438f1…`; both
lanes PASS. Evidence: `docs/evidence/canonical-gate-2026-08-04.json`.

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
- D10 rasterised text regions in `c5_graphics` and `04_exec_brief`.
- Heavy LaTeX and highly designed/vector pages are deferred; image-only scan/OCR
  PDFs are explicitly rejected as OCR-required rather than silently converted.

The project prioritises ordinary digital text, multi-column pages, common
tables, and i18n. A rasterised figure can be the honest fallback for a designed
region, but its text is counted as non-live by the quality metrics.

## PDFium migration candidate — not shipping

`PDFIUM_GDOCS_CANDIDATE` is the explicit non-shipping profile:

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

**This is one clean pass, not a release.** The migration gate asks for two, and
the second must be a fresh consented run.

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

The project is AGPL-3.0-or-later today. PyMuPDF is core, which is the current
licensing blocker. PDFium is optional and is the migration path, not proof that
the switch is ready.

Apache-2.0 is the preferred future target because its patent grant and
business-friendly terms better suit the intended distribution. It remains
contingent on removing PyMuPDF from the core/default path, expanded PDFium
parity and two clean Google passes, plus dependency/provenance/license audit
(including bundled PDFium dependencies) and appropriate legal review. This is
project strategy, not legal advice.

## Reproduce safely

```bash
bash scripts/bootstrap.sh --strict
python testkit/corpus_manifest.py verify
python testkit/runall.py
```

Use `testkit/runall.py --absolute` for release qualification, not the ordinary
regression check alone. Never re-record canonical numeric evidence from a local
machine or to silence a failure.
