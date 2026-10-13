# exactdoc

**Turn a PDF into a Word document that looks like the original and that you
can actually edit.**

exactdoc writes a DOCX made of real headings, paragraphs, lists, tables,
footnotes and page headers, and lays them out so each page matches the PDF.
Its output is measured by opening it in Microsoft Word, LibreOffice and Google
Docs and comparing every page with the original. It runs entirely on your
machine: no telemetry, no account, and no network unless you ask for the
optional Google Docs measurement ([details](docs/install.md#what-talks-to-the-network)).

![Animation. On the left, page 1 of a whitepaper as the original PDF. On the right, the DOCX exactdoc made from it, shown in turn as Microsoft Word, Google Docs and LibreOffice lay it out. All four pages look almost the same.](docs/images/hero-readers.gif)

<sub>Page 1 of one of the project's test whitepapers, converted with the default
settings; Google Docs shows the DOCX made for it ([still image](docs/images/hero-readers.png),
[how it was made](docs/images/README.md)). Small differences remain: Google Docs
adds a thin white strip above the dark band, and the footer's page number sits
further left than in the PDF, set larger in Word and Google Docs.</sub>

> **Beta (0.3.0b3), on PyPI.** How it does on PDFs it has never seen, good
> and bad, is [below](#tested-on-documents-it-has-never-seen).

## Install

You need Python 3.9 or newer.

```bash
pip install --pre exactdoc
exactdoc --version
```

Optional, and recommended: **[LibreOffice](https://www.libreoffice.org/download/)**
(free). When it is installed, exactdoc opens its own DOCX in it, compares each
page with the PDF and corrects page breaks and spacing. Without it, exactdoc
converts in one pass and says so. [docs/install.md](docs/install.md) covers the
fonts LibreOffice needs on Linux, how long the check takes, and the optional
extras.

## Quick start

```bash
exactdoc report.pdf                                    # writes report.docx next to it
exactdoc report.pdf --output-profile gdocs --refine 0  # a DOCX made for Google Docs
exactdoc --input-dir pdfs --out-dir docx --recursive   # a whole folder
```

```python
from exactdoc import convert
convert("report.pdf", "report.docx")                                  # with LibreOffice's check
convert("report.pdf", "report.docx", refine_rounds=0, oracle="none")  # without LibreOffice
```

exactdoc never replaces a file you did not name. The Google Docs option writes
the same document in a form Google Docs' importer reads correctly; it is still
made offline, and you upload it to Drive yourself. Every option, the Python API
and the exit codes are in [docs/usage.md](docs/usage.md).

## What you get

The DOCX is built from the same pieces you would use to write the document in
Word yourself, not from text boxes pinned to the page:

![Page 2 of the whitepaper's DOCX with its parts labelled: a header that repeats on every page, a bulleted list, Heading 2 and Heading 1 styles, a table with real rows and cells, a chart kept as a picture, and a footer with a live page number.](docs/images/editable-structure.png)

- **Headings** use Word's heading styles, so the navigation pane and Google
  Docs' outline work.
- **Paragraphs** flow and re-wrap when you edit them.
- **Lists** are real bulleted and numbered lists.
- **Tables** are real tables, with merged cells and rows that run over pages.
- **Headers and footers** repeat on every page, with live page numbers.
  **Footnotes** are real Word footnotes (plain text in the Google Docs output,
  because Docs moves real ones), and links still work.
- **Charts, logos and artwork** stay pictures, placed where the PDF has them.

## What works, and what does not yet

What exactdoc promises depends on the program that made the PDF. Documents
written as flowing text in **Word, Google Docs, LibreOffice or LaTeX** are
promised. Designed layouts are not, yet. Numbers below are from the 0.3.0b3
release measurement ([record](docs/evidence/release-measurement-2026-10-13-b3.json))
and, where they say "never seen", from [the test below](#tested-on-documents-it-has-never-seen)
([results](docs/evidence/holdout4-2026-10-13.json)).

| Kind of PDF | Today |
|---|---|
| Letters, memos, minutes, policies and other documents of up to 20 pages written in Word, Google Docs or LibreOffice | Works well: of 13 never seen, all 13 kept their page count, with at least 99% of their words on the right page, in LibreOffice and Word |
| Résumés | Mostly: of 3 never seen, all 3 kept their page count in LibreOffice and 2 in Word; a 5-page résumé packet came back with 6 pages in Word |
| Papers of up to 20 pages written in LaTeX | Mostly: of 8 arXiv papers never seen, 6 kept their page count in LibreOffice and 5 in Word, but two came back unusable: a 19-page paper at twice its length, an 11-page paper missing 15% of its words ([below](#tested-on-documents-it-has-never-seen)) |
| Reports over 20 pages | Good: three government reports never seen (24, 35 and 69 pages) came back page for page, with at least 99% of their words on the right page, in LibreOffice and Word |
| Long documents written in LaTeX | Partly: a 26-page arXiv paper never seen came back with 31 pages (30 in Word), and a 168-page PhD thesis with 179 (180 in Word) |
| Tables, simple two-column pages, headers, footers, footnotes, links | Works well |
| Latin, Cyrillic and Greek text | Works well |
| Chinese, Japanese and Korean text | Partly: the text survives, but some runs become pictures |
| Arabic, Hebrew and Persian (right-to-left) | Partly: right-to-left paragraphs in reading order; pages can grow, and the Google Docs output is not yet right-to-left |
| Long documents opened in Google Docs | Mostly: some gain pages (IRS Publication 15: 62 pages for 59). Not part of the never-seen test |
| Designed reports and annual reports (InDesign, Affinity, QuarkXPress, Publisher) | Not yet: the text stays editable, but the layout does not hold |
| Multi-column booklets (IRS, GPO, Federal Register style) | Not yet: IRS Publication 501 grows from 31 pages to 45 in LibreOffice |
| Dense journal papers, equations | Not yet: equations come apart, and pages can be added |
| Slide decks, brochures, posters | Not yet |
| Web pages printed from a browser | Mostly: of 3 never seen, 2 came back page for page in LibreOffice and Word; a 5-page code of conduct came back with 6 |
| Scans without a text layer, fillable forms, over 250 pages | Refused with a clear message and exit code (no OCR is built in; `--max-pages` raises the cap) |

<table>
<tr>
<td width="50%"><img src="docs/images/works-tables.png" alt="A page of tables, PDF beside DOCX. A table with merged header cells, a nested table and a long striped table look the same in both."></td>
<td width="50%"><img src="docs/images/not-yet-dense-paper.png" alt="Page 1 of a two-column arXiv paper beside its DOCX. The text and columns match, but a summation equation is broken apart, outlined in red."></td>
</tr>
<tr>
<td><b>Works:</b> tables become real Word tables, merged cells included.</td>
<td><b>Not yet:</b> in a dense arXiv paper (CC BY 4.0) the text converts, but equations come apart.</td>
</tr>
</table>

To see which program made a PDF, open **File → Properties** in a PDF viewer and
read the Producer and Application fields, or run `exactdoc --diagnose your.pdf`,
which prints them without any of the document's text. The full list, with
numbers, is in [docs/deep-dive/limitations.md](docs/deep-dive/limitations.md);
more side-by-side pictures are in [docs/examples.md](docs/examples.md).

## How we know

Measured, not eyeballed. Every change must pass 16 frozen test documents,
gated on every push in CI inside the pinned measurement image, and
each milestone converts 95 frozen PDFs (those 16 and 79 more, most of them
public real-world documents), opens every DOCX in LibreOffice, Microsoft Word
and Google Docs, and compares it with the PDF page by page. In the release
measurement for 0.3.0b3 ([record](docs/evidence/release-measurement-2026-10-13-b3.json),
[scorecard](docs/evidence/beta-readiness-2026-10-13-b3.json); the Google Docs figures
are from the 11 October flight, and the DOCX made for Google Docs has not
changed since):

- all 41 promised documents of up to 20 pages kept exactly their page count in
  all three;
- of the 21 promised documents over 20 pages, all 21 in LibreOffice and Word,
  and 18 in Google Docs, kept their page count within 2% (or one page) with at
  least 85% of their words on the right page;
- across everything, including the kinds marked "Not yet", Word opened all 90
  DOCX files without asking to repair one, and in Google Docs
  66 of the 90 compared came back with exactly the right number of pages.
  The other five are PDFs exactdoc refuses on purpose.

These are the documents exactdoc was developed against, so they show how well
it does on PDFs it has seen. How the measurement works:
[docs/deep-dive/measured-state.md](docs/deep-dive/measured-state.md).

### Tested on documents it has never seen

Before the release, 36 public PDFs never used in development were sealed, then
converted once, on the release candidate, and opened in LibreOffice and Word.
32 were classed as promised before the run: 27 of up to 20 pages and 5 longer.
The bar for announcing was set in advance; Google Docs was not part of this
test ([results](docs/evidence/holdout4-2026-10-13.txt), [data](docs/evidence/holdout4-2026-10-13.json)).

- **R1, no crashes: pass.** Nothing crashed or was refused, and Word opened all 36 cleanly.
- **R2, short promised documents: pass.** 24 of 27 kept exactly their page count in LibreOffice and 22 of 27 in Word (the bar is 80%); 25 and 24 had at least 90% of their words on the right page.
- **R3, no unusable result: fail.** Two short arXiv LaTeX papers came out unusable: a 19-page statistics paper came out at twice its length (38 pages in LibreOffice, 37 in Word), and an 11-page paper lost 15% of its words. No long document was unusable.
- **R4, long promised documents (reported):** a median page-count error of 0%; 3 of 5 within 2% (or one page), and 3 of 5 in LibreOffice (4 in Word) with at least 85% of their words on the right page.
- **R5, Google Docs (reported):** not part of this test; the live Google Docs check of the 16 gated test documents stands.

So 0.3.0b3 met the page and word bar on short documents in both Word and
LibreOffice, but two LaTeX papers came out unusable, so it does not yet meet
the full bar we set. It is announced anyway, as decided before the test ran.
This release ends the loop of fixing against one sealed test after another:
from here on, each release carries a fresh report card on documents it has
never seen.

On a different set of never-seen PDFs, 0.3.0b2 kept 20 of 26 short promised
documents page-exact in LibreOffice and 18 in Word, with four unusable
([results](docs/evidence/holdout3-2026-10-13.txt)); 0.3.0b3 kept 24 of 27 and
22 of 27, with two unusable. Since 0.3.0b2 the "unusable" rule is stricter on
lost text (fewer than 90% of the words anywhere in the output, where it was
under half) and leaves text pushed onto the next page to the page test; under
it 0.3.0b2's test would have counted three short documents unusable, not four
([re-score](docs/evidence/holdout3-rescore-r3v2-2026-10-13.json)).

## Fonts

The DOCX names only fonts that a standard Windows 10 or 11 computer with
Microsoft Office has, with one exception: Chinese, Japanese, Korean, Arabic,
Hebrew, Persian and Thai text keeps the PDF's own font name, so a reader who
has that font sees it and one who does not gets Word's default for the script.
The fonts the test documents name this way are `Noto Sans CJK JP`,
`IPAPGothic`, `WenQuanYi Zen Hei`, `DFKai-SB`, `DejaVu Sans`,
`Noto Naskh Arabic`, `David`, `Narkisim`, `BNazanin` and `Thonburi`.

## Contributing

PRs welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for the one-command quality
check every PR runs. If a conversion goes wrong,
[report it](https://github.com/ebt55/exactdoc/issues/new?template=bad-conversion.yml)
with the output of `exactdoc --diagnose your.pdf` instead of the PDF itself.

## Learn more

| | |
|---|---|
| [docs/install.md](docs/install.md) | LibreOffice and its fonts, timing, the optional extras, what talks to the network |
| [docs/usage.md](docs/usage.md) | Every option, the Python API, batch mode, exit codes |
| [docs/deep-dive/limitations.md](docs/deep-dive/limitations.md) | What does not work yet, with numbers |
| [docs/examples.md](docs/examples.md) | More pages side by side, the good and the bad |
| [docs/deep-dive/measured-state.md](docs/deep-dive/measured-state.md) | How the numbers are measured |
| [CHANGELOG.md](CHANGELOG.md) | What changed, release by release |
| [SECURITY.md](SECURITY.md) | Reporting a security problem privately |
| [docs/README.md](docs/README.md) | Index of every deeper document |

## Licence

exactdoc is [Apache-2.0](LICENSE). A default install pulls in no copyleft code.
The optional `mupdf` extra (`pip install "exactdoc[mupdf]"`) adds PyMuPDF, which is
AGPL-3.0; it is only a reference for measurements and does not change the output.
Details: [docs/deep-dive/licensing.md](docs/deep-dive/licensing.md) and
[docs/license-audit.md](docs/license-audit.md).
