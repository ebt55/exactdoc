# Using exactdoc

The full reference for installing and running the converter: every extra, the
Python API, batch mode, exit codes, and what happens when LibreOffice is missing
or misbehaves. The [README](../README.md) has the short version, and
`exactdoc --help` lists every flag.

## Install

```bash
git clone https://github.com/ebt55/exactdoc && cd exactdoc
pip install -e .            # core (PDFium backend) — no AGPL code
# optional extras:
pip install -e ".[mupdf]"   # PyMuPDF reference backend — AGPL-3.0, see deep-dive/licensing.md
pip install -e ".[gdocs]"   # exactdoc-gdocs CLI (Google auth + qualification)
pip install -e ".[test]"    # test/measurement toolkit
```

The shipping profile's refinement loop renders through LibreOffice headless
(`soffice`); see *When LibreOffice is missing or fails* below for what happens
without it. Conversion is local; nothing is uploaded.

## Usage

```bash
exactdoc report.pdf -o report.docx

# Google-Docs-safe OOXML, still fully offline:
exactdoc --output-profile gdocs --refine 0 report.pdf -o report.docx
```

`--refine 0` with `--output-profile gdocs` is the profile qualified live in
Google Docs (`pdfium/gdocs/none/refine0@240dpi`). With refinement on, the layout
is corrected against LibreOffice's render, and a layout tuned for LibreOffice is
measurably not tuned for Google Docs.

```python
from exactdoc import convert

convert("report.pdf", "report.docx")

# Google-Docs-safe OOXML, still fully offline:
convert("report.pdf", "report.docx", output_profile="gdocs", oracle="none",
        refine_rounds=0)
```

Batch conversion over folders is deterministic and safe to re-run:

```bash
exactdoc --input-dir pdfs --out-dir docx --recursive --result-json batch.json
```

Use `--continue-on-error`, `--overwrite`, or `--scan-only` as appropriate.
Discovery is case-insensitive and preserves relative paths; existing outputs
require `--overwrite`; batch runs are serial today (`--workers` must be `1`).
Limits are 500 documents, 250 pages/document, 2,000 pages/run, 250 MiB/file.
Result JSON is atomically published and contains only relative paths, safe
errors, hashes, counts and options.

Input errors are deliberately stable: encrypted PDFs report unsupported input;
malformed or truncated PDFs report parse errors; high-confidence image-only
scans exit with an explicit OCR-required code (17, or 18 for partial batch
failures). Output publication is transactional: candidates stay private until
structural DOCX validation succeeds, then replace the destination atomically —
a failed conversion never corrupts an existing output.

### Exit codes

A failed conversion prints `error: <reason>` to stderr and exits with a stable
code (`exactdoc/cli.py`, `EXIT_CODES`):

| Code | Meaning |
|---:|---|
| 0 | Converted (a degraded LibreOffice run still exits 0, with a warning; see below) |
| 2 | The command line itself is wrong (an unknown flag, or a missing input) |
| 3 | Invalid configuration |
| 4 | A cloud oracle was asked for without `--allow-cloud-upload` |
| 5 | Unsupported input, such as an encrypted PDF |
| 6 | The PDF could not be parsed (malformed or truncated) |
| 7 | The requested parser backend is not installed |
| 8 | The output could not be written |
| 9 | A resource limit was exceeded |
| 10–16 | The render oracle failed: 11 means LibreOffice is not installed; 12–16 are Google Docs oracle stages (auth, upload, import, export, cleanup) |
| 17 | The PDF is an image-only scan and needs OCR first |
| 18 | Batch mode: some documents failed or need OCR |
| 19 | The PDF is a fillable form, which is refused |
| 20 | Over the page cap (250 by default); `--max-pages N` raises it, `--max-pages 0` removes it |

### When LibreOffice is missing or fails

Two different situations, deliberately handled differently:

- **Not installed.** Asking for refinement (the default) with no `soffice` on
  the machine is an error before anything is written: `OracleUnavailableError`,
  **exit code 11**. Install LibreOffice, or pass `--refine 0` to convert
  open-loop on purpose. Converting open-loop silently would make the default
  profile mean the raw one on that machine, for every document, with nothing to
  say so.
- **Installed, but it crashes, hangs or writes nothing mid-run.** The
  conversion has already produced a valid DOCX by then, so it is not thrown
  away: the best candidate so far is published — the best measured refine
  round, or, if the very first render failed, the open-loop DOCX — and the
  failure is reported as a warning, not an error. The CLI exits **0** and
  prints `warning: the libreoffice oracle failed in refine round N; …` to
  stderr. From Python, `convert()` raises
  `exactdoc.errors.OracleDegradedWarning` through `warnings.warn`, and
  `exactdoc.convert.convert_result()` returns a `ConversionResult` whose
  `warnings` carry an `oracle-degraded` entry and whose `degraded` is True
  (`resolved_options` names the rounds that actually ran). A batch result
  row lists the warning under `warnings`.

  To get the old all-or-nothing behaviour, escalate the warning:
  `warnings.simplefilter("error", OracleDegradedWarning)`. It is raised before
  publication, so the conversion then fails and the destination is untouched.
  The gate and the quality sweep do exactly that, so a degraded conversion is
  never measured as the shipping product.

LibreOffice keeps one private profile per conversion (created on the first
render, removed at the end), under a short directory: a profile beneath a long
TEMP path crashes soffice on Windows. Set `EXACTDOC_SOFFICE_ROOT` to choose
that directory explicitly.
