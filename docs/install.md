# Installing exactdoc

The [README](../README.md) has the two-line version. This page has the rest:
what LibreOffice adds and which fonts it needs, how long a conversion takes,
the optional extras, and the one part of exactdoc that can use the network.

## exactdoc itself

You need Python 3.9 or newer (check with `python --version`). A clean install
was checked on Linux and Windows
([record](evidence/beta-install-2026-10-05.json)), and the `install` workflow
installs and converts on Python 3.9 to 3.14 on every push.

Until the first beta (0.3.0b1) is on PyPI, install from a clone:

```bash
git clone https://github.com/ebt55/exactdoc && cd exactdoc
pip install .
exactdoc --version
```

Once it is published, `pip install --pre exactdoc` installs it. (`--pre`
because 0.3.0b1 is a pre-release.)

That is all you need to convert PDFs. Everything below is optional.

## LibreOffice: the layout check

**[LibreOffice](https://www.libreoffice.org/download/)** (free) gives the best
layout. When it is installed, exactdoc opens its own DOCX in LibreOffice,
compares each page with the PDF and corrects page breaks and spacing. Without
it, the command line converts in one pass and prints a note saying so. From
Python, `convert()` does not fall back on its own: it raises
`OracleUnavailableError` so a script never receives an unchecked DOCX it did
not ask for; pass `refine_rounds=0, oracle="none"` to convert without
LibreOffice. [usage.md](usage.md#when-libreoffice-is-missing-or-fails) has the
details, including what happens when LibreOffice crashes mid-run.

### How long it takes

The check renders the document up to four times. In the project's test
container, one conversion at a time, a 31-page IRS publication took 31
seconds with it and the 126-page Form 1040 instructions 2 min 34 s
([measurement](evidence/release-documents-2026-10-11.json)). `--refine 0` skips the
check and is the fastest; `--refine 1` is a middle way: about a third less
time on long documents, for up to six more pages in our measurements
([measurement](evidence/refine-speed-2026-10-05.json)).

### Fonts for LibreOffice

The check is only as good as the fonts LibreOffice draws with. The DOCX names
Calibri, Cambria, Arial and Times New Roman, and LibreOffice needs their free
metric twins (Carlito, Caladea and Liberation) to set them at the right widths.
On Linux, install them with LibreOffice (Debian and Ubuntu package names):

```bash
sudo apt install libreoffice-writer fonts-crosextra-carlito fonts-crosextra-caladea fonts-liberation
```

On Windows and macOS the installers from libreoffice.org include these fonts.
Without them LibreOffice draws Calibri text in a different font, and the check
corrects the layout against the wrong widths: a NIST publication whose text is
82% Calibri, rendered in LibreOffice without the layout check, had 30% of its
words on the right page without the twins and 74% with them
([measurement](evidence/carlito-2026-10-06.json)).

## Making a DOCX for Google Docs

`--output-profile gdocs` writes the same document in a form that Google Docs'
importer reads correctly. It works offline in every install; upload the DOCX
to Google Drive and open it with Google Docs. Use it with `--refine 0`: the
LibreOffice check tunes the layout for LibreOffice, and that is measurably not
the right tuning for Google Docs.

```bash
exactdoc report.pdf -o report.docx --output-profile gdocs --refine 0
```

## Optional extras

```bash
pip install "exactdoc[gdocs]"   # exactdoc-gdocs: measure a DOCX inside Google Docs with your own account
pip install "exactdoc[mupdf]"   # PyMuPDF reference parser: AGPL-3.0, changes nothing in the output
pip install "exactdoc[test]"    # the test and measurement toolkit, for development
```

From a clone, use `pip install -e ".[gdocs]"` and so on. The `mupdf` extra
changes your licence obligations for anything you distribute; see
[deep-dive/licensing.md](deep-dive/licensing.md).

## What talks to the network

Converting a PDF reads the file and writes the DOCX on your computer and
nothing else: no telemetry, no network calls, no account. The only code that
talks to the internet is the optional Google Docs measurement
(`--oracle gdocs`, and the `exactdoc-gdocs` command that signs it in). It needs
the `gdocs` extra and your own Google account, and a conversion uploads
nothing unless you also pass `--allow-cloud-upload`; without it, asking for the
Google Docs measurement stops with exit code 4.
