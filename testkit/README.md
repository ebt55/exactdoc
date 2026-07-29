# testkit — independent fidelity measurement for exactdoc

This shares **no code** with `exactdoc/`. That is the point: `exactdoc/verify.py`
calls `exactdoc.infer()` to decide which source text to exclude from its own
coverage denominator, so anything the converter chooses to rasterise disappears
from its own score. A converter must not define its own ground truth.

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

`pypdfium2` is in that list deliberately. It is not needed to convert a PDF,
but `backend_parity.py` — the acceptance test for the whole licence swap —
cannot run without it, and it was once omitted here: a `uv sync` evicted it and
the parity gate spent an unknown number of runs reporting `ModuleNotFoundError`
instead of regressions. A gate that cannot run looks exactly like a gate that
passes.

```bash
python testkit/gen_corpus.py testkit/adv --strict && python corpus/make_corpus.py
```

```bash
python testkit/corpus_manifest.py verify && python testkit/runall.py
```

`runall.py` runs both lanes and exits non-zero if either fails, so it works as
the CI check.

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
| the raw lane regressed | `REFINE=lanes` returned only the refined lane's status |
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
| `corpus_manifest.json` | the exact 16 documents, their generator, dialect and source page count. Not a content hash — both generators embed timestamps, so the bytes differ every run and a hash would fail every run |
| `gate_baseline.json` | every gated metric of every document, per lane, numerically, plus the environment it was measured on and the defect ID each shortfall answers to |
| `parity_policy.json` | the backend-swap acceptance rule: comparison margins, the two expected divergences with their rendered evidence, and the two accepted shortfalls with numeric floors |

Re-record deliberately, on the canonical environment, and say so in the commit
message:

```bash
GATE_BASELINE=update python testkit/runall.py     # after a ratified change
```

```bash
python testkit/corpus_manifest.py update          # after a generator change
```

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

Built during the permissive-parser port, each because a question could not
otherwise be answered. They compare the two backends on the same document and
need no oracle, so they run in seconds.

| File | Answers |
|---|---|
| `backend_parity.py` | **the swap's verdict**, against `parity_policy.json`. Marks each document REGRESSION / same / BETTER / expected-div / accepted. `--only <doc>` for one document; `--update-policy` to re-record the accepted floors |
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
