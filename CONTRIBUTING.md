# Contributing to exactdoc

Thank you for trying exactdoc. The most useful thing you can send is a
conversion that went wrong.

## Reporting a bad conversion

1. Run `exactdoc --diagnose your.pdf`. It prints what the converter's
   decisions depend on (the program that made the PDF, its page sizes and
   fonts, and the layout exactdoc found) with **none of the document's text**.
   It converts and writes nothing.
2. Read the output through. Producer and font names can identify an
   organisation; remove anything you would rather not share.
3. Open a [bad-conversion report](https://github.com/ebt55/exactdoc/issues/new?template=bad-conversion.yml)
   and paste it in, with a cropped screenshot of the problem if you can.

**Do not attach a confidential PDF.** Everything in an issue is public, for
ever, attachments included.

If exactdoc would not install, or stopped with an error you did not expect
(a traceback, or "This is a bug"), use the
[install or crash report](https://github.com/ebt55/exactdoc/issues/new?template=install-or-crash.yml)
instead. Security problems go through [SECURITY.md](SECURITY.md), not an
issue.

## What to expect

exactdoc is maintained by one person. Every report is read, but replies are
best effort and can take a week or more. A report with `--diagnose` output, the
command you ran and what you expected is the one most likely to be fixed,
because it can be reproduced without your document.

## Running the tests

```bash
git clone https://github.com/ebt55/exactdoc && cd exactdoc
pip install -e ".[test]"
python -m unittest discover -s tests
```

Tests that need LibreOffice, the optional PyMuPDF extra or the pinned fonts
skip themselves, so the suite runs on any machine; this is what the `install`
workflow runs on Linux, Windows and macOS.

The quality gate is different: it converts 16 frozen test documents and
renders them in a pinned copy of LibreOffice with pinned fonts, and its numbers
only mean something in that environment. It runs in the container built from
[docker/gate.Dockerfile](docker/gate.Dockerfile), as
[.github/workflows/gate.yml](.github/workflows/gate.yml) does. A change that
moves the gate's numbers needs that run, and the evidence it writes, before it
can be merged. See [docs/README.md](docs/README.md) for the measurement
documents.

## Licence

exactdoc is Apache-2.0. By contributing you agree that your contribution is
licensed under the same terms. Do not add a dependency without updating
[docs/license-audit.md](docs/license-audit.md); `tests/test_packaging_metadata.py`
fails until you do.
