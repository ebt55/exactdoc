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
python testkit/gen_corpus.py testkit/adv && python corpus/make_corpus.py
```

```bash
REFINE=lanes python testkit/runall.py testkit/adv corpus/pdfs
```

`runall.py` exits non-zero when any document misses the gate, so it works as
the CI check.

### External tools

| Tool | Needed for | Override |
|---|---|---|
| LibreOffice | render-back: every metric except the corpus itself | `SOFFICE=/path/to/soffice` |
| Chrome/Chromium/Edge | generating the 8 Chromium/Skia corpus documents | `CHROME=/path/to/chrome` |
| Liberation + DejaVu fonts | what the LibreOffice oracle renders with | — |

Both are auto-discovered (`_paths.py`); the environment variables win when set.
A missing tool makes `gen_corpus.py` skip the documents it produces and say so,
exiting 0 — but the resulting corpus is smaller than the one the recorded
baselines were measured on, so its numbers are not comparable to them. A tool
that is *present and failing* exits 1 instead. Ubuntu's `chromium-browser`
package is the case that motivates the distinction: it is a snap shim that
installs, sits on `PATH`, and fails on every invocation inside a container.

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
| `runall.py` | batch convert + score + CI gate |
| `gen_corpus.py` | adversarial corpus across 4 producer dialects (Chromium/Skia, ReportLab, fpdf2, LibreOffice) |
| `probe.py` | dump a PDF's producer, fonts, drawings and what `infer()` decided |
| `wrapdiag.py` | compare source vs rendered wrap geometry; find the first diverging line per page |
| `drift_decomp.py` | split vertical drift into per-page constant offset, accumulation slope, and irreducible scatter |
| `ooxml_audit.py` | inventory the emitted OOXML vocabulary and flag Google-Docs risks |
| `edge_cases.py` | degenerate inputs: empty, image-only, landscape, mixed page sizes, rotated, encrypted, truncated |
| `exp_chromefix.py` | A/B prototype of the Chromium-dialect fix (monkey-patched, edits nothing) |
| `exp_sweep.py` | sweeps the wrap-width correction, measuring line-break agreement |

## Producer dialects

`gen_corpus.py` generates from four engines because **a PDF's producer changes
its structure more than its content does**. `corpus/make_corpus.py` adds five
ReportLab documents — one dialect, authored by the same process that was tuned
against it. Chromium/Skia, the likely producer for anything printed from a
browser, was absent from the original corpus and is where the tool failed
hardest. The two generators together make the 16-document gate corpus:
8 Chromium/Skia, 6 ReportLab, 1 fpdf2, 1 LibreOffice.
