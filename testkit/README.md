# testkit — independent fidelity measurement for exactdoc

This shares **no code** with `exactdoc/`. That is the point: `exactdoc/verify.py`
calls `exactdoc.infer()` to decide which source text to exclude from its own
coverage denominator, so anything the converter chooses to rasterise disappears
from its own score. A converter must not define its own ground truth.

## Quick start

```bash
pip install pymupdf python-docx numpy pillow reportlab fpdf2 lxml
```

```bash
python testkit/gen_corpus.py testkit/adv
```

```bash
python testkit/runall.py testkit/adv my_samples exactdoc_v1.1/corpus/pdfs
```

`runall.py` exits non-zero when any document misses the gate, so it works as
the CI check. LibreOffice and Chrome/Edge are found automatically; override
with the `SOFFICE` / `CHROME` environment variables.

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
its structure more than its content does**. The corpus in
`exactdoc_v1.1/corpus/` is five ReportLab documents — one dialect, authored by
the same process that was tuned against it. Chromium/Skia, the likely producer
for anything printed from a browser, was absent and is where the tool fails
hardest.
