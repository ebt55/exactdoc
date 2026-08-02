# testkit — independent fidelity measurement for exactdoc

This shares **no code** with `exactdoc/`. That is the point: `exactdoc/verify.py`
calls `exactdoc.infer()` to decide which source text to exclude from its own
coverage denominator, so anything the converter chooses to rasterise disappears
from its own score. A converter must not define its own ground truth.

The harness reads PDFs with **PyMuPDF**, matching the quality-first shipping
profile. Backend parity separately converts
through the explicit PDFium candidate while retaining an independent reference
arm.

## Quick start

On Linux, one command provisions everything below and prints a capability
report — Python packages, the LibreOffice and Chromium oracles, and the
metric-compatible fonts the oracle renders with:

```bash
bash scripts/bootstrap.sh
```

By hand, or on Windows/macOS:

```bash
pip install -e ".[test,pdfium]"
```

PyMuPDF is a core runtime dependency. The `pdfium` extra is deliberate because
`backend_parity.py` compares the explicit PDFium candidate with the shipping
PyMuPDF reference. The cloud Google Docs oracle is not part of this local gate
environment and is installed separately when qualification needs it.

```bash
python testkit/gen_corpus.py testkit/adv --strict && python corpus/make_corpus.py
```

```bash
python testkit/corpus_manifest.py verify && python testkit/runall.py
```

`runall.py` runs both lanes and exits non-zero if either fails, so it works as
the CI check.

## Google Docs qualification evidence

Google Docs qualification is a separate, consented cloud operation for the
explicit non-shipping candidate; it is not part of the local `runall.py` gate:

```bash
python testkit/gdocs_oracle.py prepare <dir>
python testkit/gdocs_oracle.py run <dir> --allow-cloud-upload
python testkit/gdocs_oracle.py assess <gdocs_qualification.json>
```

`prepare` is offline and hash-binds the candidate. `run` may upload and reports
operational and quality verdicts independently. The latest live run on 2026-08-02
for `pdfium/gdocs/none/refine0@240dpi` was operationally successful: 16
attempted, 16 succeeded, zero failed, and no `.gdocs_orphans.json` remained
after cleanup. Against the prior live candidate, page match improved 14/16→15/16,
mean within-2pt 0.1378→0.1443, mean word recall 0.8745→0.9064, SSIM
0.7767→0.7878, and IoU 0.2108→0.2138; live text remained 0.9568. Median dy50
rose 4.98→6.68pt because `c3_tables` now matches many more words and changes
median ordering, not because of a broad regression. Only `c5_graphics` remains
a page mismatch (1→2).

The candidate adds a
conservative striped-table assembler: `c3_tables` is one editable 46-row ×
4-column DOCX table, IDs 1–45 exactly once, naturally paginated without an
invented repeating header. It also consolidates `c1_whitepaper`'s 5-row
comparison table. The detector rejects ambiguous multiline/cards/callouts and
coalesces only page-edge segments with matching geometry; it does not claim to
solve complex/nested regional tables. Local LibreOffice review was indicative
only; live Google review now shows `c3_tables` 3→3 (rather than 3→4), live
0.9226/doc recall 0.9359 unchanged, word recall 0.3120→0.8215, within-2pt
0→0.1076, SSIM 0.5785→0.7573, and IoU 0.0973→0.1448. Its dy50/dy90 are
2.94→7.85pt and 80.52→103.34pt because many more words match. All 45 rows are
present in an editable continuous three-page table, although row distribution
differs from source. `c1_whitepaper` remains 2→2 with live/document/word recall
0.9654/0.9697/0.9697 and dy50/dy90 9.30/54.79pt unchanged; within-2pt, SSIM,
and IoU have tiny 0.0719→0.0688, 0.8006→0.7993, and 0.1568→0.1563 tradeoffs.
`c5_graphics` remains a deferred gradient/rounded/rotated designed-page
limitation. PDFium
preserves stretched literal interword spaces, removing the
`01_whitepaper_market` word staircase; shipping PyMuPDF is unaffected.

This is operational success only. The strict draft v2 policy has blocking
`ordinary_digital`, tracked/nonblocking `designed_stress`, and unsupported-input
refusal tiers plus explicit owner ratification. `assess` is offline, constructs
no Drive service, hash-binds the source evidence, writes a separate atomic
assessment, and returns 1 while a valid assessment fails quality.

The latest evidence has 9/13 ordinary fixtures within every draft threshold.
Seven blocking findings remain across `01_whitepaper_market` (SSIM),
`c2_paper2col` (dx/dy/SSIM), `c7_code` (dx), and `l1_word_native` (dx/dy).
The policy is intentionally still unratified, so `quality_pass=false` and
`overall_pass=false`. Do not ratify or weaken it merely to declare the candidate
releasable. Expand the corpus to 40–60 PDFs and review the thresholds after the
blocking layout issues are fixed; the current 16 fixtures are regression
evidence, not market coverage.

## The gate, and what it refuses to let through

`runall.py` produces numbers; **`gate.py` decides**, and it is a pure function
over already-measured results so that `tests/test_gate_mutations.py` can break
one thing at a time and assert the verdict turns red — no corpus, no oracle, no
minute. That separation exists because the previous gate lived inside the runner
and could not be tested, and an untested gate is a claim. These are the claims it
was making falsely, each now a test:

| False green | Why it happened |
|---|---|
| the renderer failed on every document | `harness.evaluate()` returns `{"error": ...}` and nothing looked for the key |
| a required metric vanished | absent metrics were skipped (`if v is None: continue`), so losing `within2pt` removed the check instead of failing it |
| a known shortfall slid arbitrarily far | the baseline stored the *names* of failing metrics; `04_exec_brief`'s 0.941 live text could have fallen to 0.10 |
| a page count went from 1 over to 40 over | `page_match` is a boolean and cannot record magnitude; `page_err` is now derived and gated |
| 8 of 16 corpus documents did not exist | nothing compared the run to a manifest; the generator exits 0 after skipping |
| two documents shared a basename | the second silently overwrote the first's DOCX *and* its result row |
| either named lane regressed | the runner returned only one lane's status instead of requiring both raw and product |
| the parity policy contradicted itself | the code exited on `regressions == 0` while the docs said two documents were accepted divergences, so CI marked the step `continue-on-error` |

Three separate questions, because they have different answers:

- **regression** — anything worse than the recorded number beyond tolerance, on
  every document and every metric, passing or not. The pull-request gate.
- **absolute** (`--absolute`) — every document clears its release threshold. The
  release-qualification gate. It fails today, by design and on the record.
- **stale** — a recorded shortfall that now passes. The record is then wrong, and
  a wrong record re-admits the regression it exists to catch.

Tolerances are sized from measurement, not taste: three environments (CI Linux, a
local `ubuntu:24.04` container, Windows) agree on every structural number and
differ in the third decimal of `within2pt`, so the tolerances sit an order of
magnitude above that noise and an order of magnitude below any regression this
project has actually shipped.

### Files the gate reads

| File | What it pins |
|---|---|
| `corpus_manifest.json` | the exact 16 documents, their generator, dialect, source page count **and a content fingerprint**. Not a hash of the file bytes — both generators embed timestamps, so a byte hash would fail every run; the fingerprint covers page geometry and normalised text, which carry no timestamp. Recorded per extractor, because the two parsers genuinely disagree on some documents, and an extractor with no recorded fingerprint fails rather than skips |
| `gate_baseline.json` | every gated metric of every document, per lane, numerically, plus the environment it was measured on and the defect ID each shortfall answers to |
| `parity_policy.json` | the backend-swap acceptance rule: the complete conversion profile ID, per-dimension comparison margins, expected divergences with rendered evidence, and shortfalls bounded by numeric floors in both directions. A policy/profile mismatch fails before any floor is applied |

### Recording is refused unless the run deserves to be believed

A baseline is what every later run is judged against, so writing one is the most
consequential operation here — and it used to have no preconditions at all.
`GATE_BASELINE=update` on a laptop, over a subset of the corpus, with a renderer
failure in the middle, would overwrite the canonical record with numbers
describing none of it, and every subsequent run would then agree with it.

Now refused unless the run is on the **canonical environment**, covers the **whole
manifest**, and produced a result for both **raw and product**; `--only` may
not record parity floors at all. The write itself goes through a temporary file and
`os.replace`, so an interrupted record cannot leave a truncated file where the
baseline used to be.

```bash
GATE_BASELINE=update python testkit/runall.py     # both lanes, whole corpus
```

```bash
python testkit/backend_parity.py --profile candidate --measure  # discover; always nonzero
# After review, create a policy bound to that exact full profile; then re-record:
python testkit/backend_parity.py --profile candidate --update-policy
```

```bash
python testkit/corpus_manifest.py update          # after a generator change
```

Say so in the commit message. A re-record is a claim that the new numbers are
*better evidence*, not a way to make a failure disappear.

### Determinism: frozen inputs, pinned fonts

Two variables decide whether a number is reproducible, and both had to be nailed
down before CI agreed with the recorded baseline:

| | |
|---|---|
| **inputs** | 16 PDFs frozen in `testkit/fixtures/`, pinned by SHA-256. They used to be regenerated per run, so a Chromium 149 → 150 difference on the runner made `c4_i18n` a different document and moved its drift 0.15pt → 0.7pt |
| **fonts** | `scripts/fonts.conf`, applied via `FONTCONFIG_FILE`. With the corpus already frozen byte-for-byte, the same document still moved 0.15pt → 2.1pt, because a runner image ships a large font collection and LibreOffice resolved its CJK and RTL runs to faces the measurement environment lacks. Liberation covers Latin only |

The second one is the subtler lesson: installing the right fonts is half the job,
and **seeing no others is the other half**. `fonts.conf` replaces fontconfig's
search path rather than adding to it.

### External tools

| Tool | Needed for | Override |
|---|---|---|
| LibreOffice | render-back: every metric except the corpus itself | `SOFFICE=/path/to/soffice` |
| Chrome/Chromium/Edge | generating the 8 Chromium/Skia corpus documents | `CHROME=/path/to/chrome` |
| Liberation + DejaVu fonts | what the LibreOffice oracle renders with | — |

Discovery order is: an exported variable, then whatever `scripts/bootstrap.sh`
recorded in `scripts/env.sh`, then the search path. `_paths.py` reads `env.sh`
itself, because nobody sources it — every CI step is its own shell, and so is
every command anyone pastes. Measured in a bare `ubuntu:24.04` container:
bootstrap reported `chromium OK <playwright shell>` and the very next command
reported `chromium=MISSING` and generated 3 of 16 documents. CI escaped it only
because the GitHub runner image ships `/usr/bin/google-chrome`, which is
provisioning by accident.

A missing tool makes `gen_corpus.py` skip the documents it produces and say so.
Without `--strict` it exits 0, which is right for a contributor on a thin machine
and wrong for the environment of record — so **CI passes `--strict`**, and a skip
is a failure there. A tool that is *present and failing* exits 1 either way.
Ubuntu's `chromium-browser` package is the case that motivates that second
distinction: a snap shim that installs, sits on `PATH`, and fails on every
invocation inside a container.

## Metrics

| Metric | Meaning | Why it exists |
|---|---|---|
| `page_match` | source page count == rendered page count | pagination drift is the loudest failure |
| `live_text_cov` | 3-gram coverage of **all** source text by *live* DOCX text | **raster-blind**: text baked into an image counts as lost. This is the metric that catches a converter quietly turning a page into a picture |
| `doc_recall` | source words present anywhere in the render | did content survive at all |
| `word_recall` (`place`) | source words present **on the right page** | content placement |
| `dy_p50/p90`, `dx_p50/p90` | drift of matched words, in points | layout accuracy |
| `within2pt` | share of words within 2pt of their source position | the strict fidelity number |
| `ssim`, `ink_iou` | pixel similarity of rendered pages | whole-page sanity |
| `n_media`, `media_bytes` | images embedded in the DOCX | rasterisation budget |

Word matching is **positional, not reading-order**: each source word is paired
with the nearest identically-spelled word on the same rendered page, greedily by
distance. Reading-order alignment silently mis-scores multi-column pages,
because sorting by `y` interleaves the columns and a 1pt shift flips the
interleave.

### On SSIM

SSIM is a weak document metric and should never be the headline number. It is
dominated by whitespace, and it *rewards* a fully-rasterised page: the resume
that was converted into two flat images scores 0.594 — comparable to genuinely
good conversions. `live_text_cov` and `within2pt` are the metrics that
distinguish a document from a photograph of a document.

## Tools

| File | Purpose |
|---|---|
| `harness.py` | the metrics; importable, or `python harness.py src.pdf out.docx workdir` |
| `runall.py` | convert + score both lanes; produces the numbers, applies no policy of its own |
| `gate.py` | **the decision.** Pure over already-measured results, so it can be mutation-tested without a corpus |
| `corpus_manifest.py` | `verify` / `update` the exact 16-document manifest |
| `evidence.py` | the one artifact every published number traces to: commit, dependency and oracle versions, profile, corpus, both lanes, parity |
| `backend_superscript.py` | does PDFium's hardcoded `superscript=False` reach a DOCX? Measured: no |
| `gen_corpus.py` | adversarial corpus across 4 producer dialects (Chromium/Skia, ReportLab, fpdf2, LibreOffice) |
| `probe.py` | dump a PDF's producer, fonts, drawings and what `infer()` decided |
| `wrapdiag.py` | compare source vs rendered wrap geometry; find the first diverging line per page |
| `drift_decomp.py` | split vertical drift into per-page constant offset, accumulation slope, and irreducible scatter |
| `ooxml_audit.py` | inventory the emitted OOXML vocabulary and flag Google-Docs risks |
| `edge_cases.py` | degenerate inputs: empty, image-only, landscape, mixed page sizes, rotated, encrypted, truncated |
| `exp_chromefix.py` | A/B prototype of the Chromium-dialect fix (monkey-patched, edits nothing) |
| `exp_sweep.py` | sweeps the wrap-width correction, measuring line-break agreement |

### Backend-comparison instruments

Built during the candidate-parser port, each because a question could not
otherwise be answered. They compare the two backends on the same document and
need no oracle, so they run in seconds.

| File | Answers |
|---|---|
| `backend_parity.py` | **the swap's verdict**, against `parity_policy.json`. `--profile product|candidate|candidate-refined` selects a complete profile; the policy must match its full profile ID. `--measure` reports raw differences but is always unadjudicated/nonzero and never writes policy. `--only <doc>` narrows diagnosis; `--update-policy` only re-records a policy already bound to the selected full profile |
| `backend_geom.py` | is the *geometry* the same? (baselines, leadings, sizes, fonts) |
| `backend_spans.py` | is the *line content* the same? span boundaries, text, injected space runs, mono flags, style keys |
| `backend_paths.py` | which coordinate space are path points in? Answer: object space — 578 of 612 corpus paths carry a non-identity matrix, and untransformed points miss by up to 5438pt |
| `block_gaps.py` | does a block-split threshold exist? Plots the two distributions it must separate and scores candidate rules against PyMuPDF's own answers |
| `residual.py` | is the remaining placement error systematic or scatter? Reports the **ceiling** a perfect anchoring fix could reach, and `--hist` shows whether the error is a few lines displaced by a whole leading or every line off by a fraction |
| `margin_probe.py` | do the backends agree on the page's vertical origin, and would they under a baseline-anchored derivation? |
| `golden_ir.py` | frozen per-document parser digests. A **microscope** for locating a disagreement — `backend_parity.py` is the contract that decides whether it matters |
| `exp_regroup.py` | grafts PyMuPDF's block boundaries onto the other backend's geometry, to isolate grouping from everything else |

Two habits these encode, both learned expensively:

- **Probe a native API's quantity before building on it.** Object space vs page
  space, ink envelope vs geometric path, before-matrix vs after-matrix font
  sizes — this API has all three traps and the project has hit all three.
- **A subset run never decides.** `--only` exists for iteration speed; a change
  is judged on the full corpus, because a two-document run once looked clean
  while costing a third document 0.55.

## Producer dialects

`gen_corpus.py` generates from four engines because **a PDF's producer changes
its structure more than its content does**. `corpus/make_corpus.py` adds five
ReportLab documents — one dialect, authored by the same process that was tuned
against it. Chromium/Skia, the likely producer for anything printed from a
browser, was absent from the original corpus and is where the tool failed
hardest. The two generators together make the 16-document gate corpus:
8 Chromium/Skia, 6 ReportLab, 1 fpdf2, 1 LibreOffice.
