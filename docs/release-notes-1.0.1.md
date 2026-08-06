# exactdoc 1.0.1

**Convert a PDF into a Word document you can actually edit — and that still
looks like the original when you open it in Google Docs.**

This is the first public release announcement. 1.0.0 was tagged but never
announced, so this note introduces the project rather than listing a diff.

---

## What it is

Most PDF→Word converters make you choose. Some give you a pile of text boxes
pinned at absolute coordinates: it looks right and is miserable to edit, because
every paragraph is its own island. Others reflow everything into clean text and
throw the layout away: editable, wrong.

exactdoc goes after both. It reads the page, infers what the document *is* —
margins, paragraphs, headings, lists, tables, multi-column sections,
headers/footers, hyperlinks — and writes real, flowing Word constructs. Then it
checks its own work: the converted DOCX is rendered back to PDF, word positions
are compared against the source, and the remaining error is measured rather than
assumed.

That last part is the reason this project exists in the shape it does. Every
quality claim below is a number from a committed measurement, and every number
traces to the run and the environment that produced it.

## What it is good at

Ordinary, fixed-layout, digitally-generated documents — and specifically, those
documents **opened in Google Docs**, which is the surface it was tuned against.

- reports, whitepapers, memos, briefs, letters
- Word-native exports (a `.docx` printed to PDF, coming home)
- academic two-column papers, including inset abstracts
- code and monospace listings, indentation intact
- hyperlinks and internal table-of-contents navigation, still live
- CJK, Cyrillic, Greek and accented Latin text

The output is a real Word file. Retitle a cover, re-wrap a paragraph, edit a
table cell — it behaves like a document, because it is one.

Verification is not a claim about a local renderer standing in for Google Docs.
The release gate uploads the real converted files to Google Docs, converts them
there, exports the result and measures *that*, with consent, and deletes
everything afterwards.

## What it is not good at

Stated plainly, because finding out later is worse.

- **Long, dense, multi-column booklets inflate their page count.** An 80-page
  publication comes out at 106 pages, a 126-page one at 337. Everything after
  the first overflow lands on the wrong page. If your documents are long dense
  booklets, this release is not for them yet. This is the headline defect and
  the next thing being worked on.
- **Pages that are artwork stay artwork.** Gradients, rotated and vector-heavy
  designs are rasterised into the document so the rest of it stays editable.
  The text inside those regions is a picture, and the quality metric counts that
  against the conversion rather than hiding it.
- **Interactive forms are refused, deliberately.** A fillable form whose content
  lives in its field values converts into a convincing-looking non-form. That is
  worse than failing, so it fails: a typed error and exit code 19.
- **Scanned or image-only PDFs are refused.** No OCR engine is bundled — a
  confident wrong transcription is worse than an honest refusal. Exit code 17.
- **There is a 250-page cap**, and it is the one refusal you can answer:
  `--max-pages N` raises it, `--max-pages 0` removes it. Exit code 20.
- **Google Docs adds about 14.6pt of white above a page-one cover band**, and
  that cannot be removed. It was measured directly against Docs: requested top
  margins of 0/4/8/14.4/20pt render as 14.55/18.83/22.83/29.23/34.83 — an
  addition, not a limit. The converter compensates what is compensable.
- **Heavy mathematics and right-to-left scripts** are not reconstructed
  correctly today.

## Since 1.0.0

A résumé went through the converter and came out wrong in ways the test corpus
could not see, because the corpus contained no résumé. Adding one exposed six
defects at once, and 1.0.1 is those fixes:

- **links attached to characters, not to spans.** A hyperlink covering less than
  half of its text run used to be dropped entirely — exactly what happens to the
  email address in a contact header.
- **a role and a date on the same line stay on the same line**, as one paragraph
  with a right-aligned tab stop, instead of the date stacking underneath.
- **the document declares the fonts it uses.** An undeclared font is not an
  error in the format — it is an invitation, and Google Docs was accepting it by
  substituting its own.
- **letter-spaced headings no longer arrive with gaps in them**, and no longer
  weld themselves to the paragraph below.
- plus a byte-pinning fix for hashed artifacts, and CI now discovering the whole
  test suite instead of five files by name.

Measured across 31 documents: 25 unchanged, the résumé pair improved
(`dy_p50` 3.13 → 0.38pt, `mean_ssim` 0.8422 → 0.8733), and the remaining
movement was confirmed to be render noise against a control. Reviewed live in
Google Docs.

Still open on résumés: the error *tail*. The median word lands within half a
point; one word in ten is still around nine points out. Good, not perfect.

## Install

```bash
pip install exactdoc
exactdoc report.pdf -o report.docx

# Google-Docs-safe output, fully offline:
exactdoc --output-profile gdocs report.pdf -o report.docx
```

Conversion is local. Nothing is uploaded unless you explicitly run the Google
qualification tooling and consent to it.

Apache-2.0. A default install carries no copyleft dependency; the optional
`[mupdf]` extra does, and installing it changes your obligations for anything
you distribute. It exists only as the reference arm for parity measurement and
does not change the output.

## Honest footing

This is a 1.0.1, not a finished product. The known defects above are listed
because they are known, the numbers are measured rather than estimated, and the
things that are not measured are named as unmeasured. If it converts your
documents well, that is because documents like yours were tested. If it does
not, the limitations section is the place that should have told you first —
and if it did not, that is a bug worth reporting.
