# Using exactdoc

The full reference for installing and running the converter: every extra, the
Python API, batch mode, exit codes, and what happens when LibreOffice is missing
or misbehaves. The [README](../README.md) has the short version, and
`exactdoc --help` lists every flag.

## Install

From PyPI, once the first beta (0.3.0b1) is published:

```bash
pip install exactdoc            # core (PDFium backend) — no AGPL code
pip install "exactdoc[gdocs]"   # + the exactdoc-gdocs CLI (Google auth + qualification)
```

From a clone (the only way before the beta, and the way to develop):

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
without it. Conversion is local; nothing is uploaded. `exactdoc --version`
prints the installed version.

Python 3.9 or newer is required; the `install` workflow proves 3.9 and 3.12 on
Linux, Windows and macOS on every push. One known difference: on a width
that lands exactly on a rounding tie, Python 3.9–3.11 and 3.12+ can write a
run's horizontal scale one percent apart, because 3.12 changed how `sum()`
adds floats. Published numbers are measured on 3.12.

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
| 1 | An internal error: a bug. The traceback is printed, followed by where to report it |
| 2 | The command line itself is wrong (an unknown flag, or no PDF given) |
| 3 | Invalid configuration, or an output that would replace something it should not: the default `<name>.docx` already exists (pass `-o` or `--overwrite`), or `-o` names the input PDF |
| 4 | A cloud oracle was asked for without `--allow-cloud-upload` |
| 5 | Unsupported input, such as an encrypted PDF |
| 6 | Not a readable PDF: empty, not a PDF at all (no `%PDF-` header), or malformed or truncated |
| 7 | The requested parser backend is not installed |
| 8 | The output could not be written: its path is a folder, or its folder cannot be written. Checked before converting, so it fails in a second |
| 9 | A resource limit was exceeded |
| 10–16 | The render oracle failed: 11 means LibreOffice is not installed; 12–16 are Google Docs oracle stages (auth, upload, import, export, cleanup) |
| 17 | The PDF is an image-only scan and needs OCR first |
| 18 | Batch mode: some documents failed or need OCR |
| 19 | The PDF is a fillable form, which is refused |
| 20 | Over the page cap (250 by default); `--max-pages N` raises it, `--max-pages 0` removes it |
| 21 | The input file does not exist, or is a folder (use `--input-dir` for a folder). Every input is checked before the first is converted |

The error is one line. For the failures you can fix yourself (a password, a
scan, a damaged file, LibreOffice asked for but missing) a `hint:` line follows
it.

### What the command prints

On success, one line per document on stdout:

```text
wrote report.docx  (31 pages, 19.4s)
```

While a long document converts, a status line on the terminal (stderr) shows
the stage and the time so far -- reading, layout, writing, or which pass of the
LibreOffice check. It is drawn only on an interactive terminal, never into a
pipe or a log, and only once a stage has taken more than a second.

Without `-o`, the DOCX is written next to the PDF with the same name and a
`.docx` extension, but never over an existing file: `exactdoc report.pdf`
stops with exit 3 if `report.docx` exists, because that is very often the Word
document the PDF was exported from. Pass `-o` to choose a name, or
`--overwrite` to replace it. An explicit `-o` always replaces.

### How long it takes

With LibreOffice installed, the default conversion renders its own DOCX up
to four times and reads each render back. Three things keep that affordable,
none of which changes the output:

- the PDF's own text lines, which the first check compares against, come from
  the conversion's reading of the PDF rather than a second reading;
- a render of 16 pages or more is read back by up to four worker processes
  (one fewer than the machine's CPUs), each taking a slice of the pages. Set
  `EXACTDOC_READ_WORKERS=1` to read in one process, or another number to fix
  the count;
- with LibreOffice 7.4 or newer, the renders leave out picture quality,
  bookmarks and notes, which the check never reads. Older versions get the
  ordinary export.

`--refine 0` skips the check altogether and is the fastest; `--refine 1` is a
middle way. Measurements are in
[docs/evidence/refine-speed-2026-10-05c.json](evidence/refine-speed-2026-10-05c.json).

### Reporting a bad conversion

```bash
exactdoc --diagnose report.pdf
```

prints what the converter's decisions depend on -- the program that made the
PDF, its page sizes and fonts, how it was classified (digital, scan, form) and
the layout exactdoc found (columns, tables, lists, headings) -- with none of
the document's text, title, author or file name. It converts and writes
nothing. Paste it into a
[bad-conversion report](https://github.com/ebt55/exactdoc/issues/new?template=bad-conversion.yml)
instead of attaching a private PDF; read it first, since producer and font
names can identify an organisation.

### When LibreOffice is missing or fails

Two different situations, deliberately handled differently:

- **Not installed.** The command line and the Python API differ here, on
  purpose:
  - **`exactdoc file.pdf` with no refinement options** converts in one pass
    (exactly `--refine 0`), exits **0**, and prints a note to stderr saying
    LibreOffice was not found, what that skips, and where to get it. A
    first-time user without an office suite is the commonest case, not a
    misconfiguration. The note is printed every time, so the fallback is never
    silent; `--refine 0` hides it.
  - **Refinement asked for by name** -- `--refine N` with N > 0, or
    `--oracle libreoffice` -- is an error before anything is written:
    `OracleUnavailableError`, **exit code 11**, with a hint to install
    LibreOffice or pass `--refine 0`. So is `convert()` from Python with the
    default profile: converting open-loop silently there would make the
    default profile mean the raw one on that machine, for every document, with
    nothing to say so. A script that wants the open-loop conversion asks for
    it (`refine_rounds=0, oracle="none"`).
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
