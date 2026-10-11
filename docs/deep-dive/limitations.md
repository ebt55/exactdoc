# Limitations, with numbers

> Moved from the README in October 2026: which PDFs exactdoc is for, the full
> table by kind of PDF, the notes for beta testers, the limitation tiers, the
> specific limitations with their measurements, and the queue of what is not
> done. The [README](../../README.md) keeps a short version;
> [examples.md](../examples.md) shows the cases side by side;
> [status.md](status.md) has the defect register, and the
> [CHANGELOG](../../CHANGELOG.md) records what has moved since.
>
> **Numbers refreshed on 2026-10-11** from the 0.3.0b1 release measurement
> (LibreOffice and Word with the default settings on 71af76e, and a live Google
> Docs sweep on 410d370), summarised in
> [docs/evidence/release-documents-2026-10-11.json](../evidence/release-documents-2026-10-11.json). A number below
> without a date is from that file; "never seen" numbers are from the sealed
> test of 32 unseen PDFs, [docs/evidence/holdout2-2026-10-11.json](../evidence/holdout2-2026-10-11.json).

## Which PDFs it is for

What exactdoc promises depends on the program that made the PDF
([beta bar, amendment 6](../beta-bar.md)):

- **Promised:** documents written as flowing text in **Word, Google Docs,
  LibreOffice or LaTeX**: reports, memos, letters, whitepapers, papers and
  résumés.
- **Not yet:** **designed reports** laid out in InDesign, Affinity Publisher,
  QuarkXPress or Microsoft Publisher (multi-column pages with full-bleed
  graphics), **annual reports**, and **multi-column booklets** in the style of
  the IRS, the GPO and the Federal Register. They convert and their text stays
  editable, but the layout does not hold: pages can be added and text can land
  on the wrong page.

To see which program made a PDF, open it in a PDF viewer and look at
**File → Properties** (in some viewers *Document Properties*): the
**PDF Producer** and **Application** (or *Creator*) fields usually name it, for
example `Microsoft® Word for Microsoft 365`, `LibreOffice` with `Writer`,
`pdfTeX` for LaTeX, `Skia/PDF … Google Docs Renderer` for Google Docs, or
`Adobe InDesign`. `exactdoc --diagnose your.pdf` prints the same two fields, as
its `producer` and `creator` lines, along with the page sizes, fonts and the
layout exactdoc found; it writes nothing and prints none of the document's text.
It does not say whether the PDF is in the promise; that is the list above. A
PDF made with a "print to PDF" driver may name the driver rather than the
program the document was written in.

## By kind of PDF

The README's table, with its numbers. Every figure is from the release
measurement ([measurement](../evidence/release-documents-2026-10-11.json)) unless it says "never seen"
([test](../evidence/holdout2-2026-10-11.json)).

| Kind of PDF | Today |
|---|---|
| Letters, memos, policies, syllabi and other documents of up to 20 pages written in Word, Google Docs, LibreOffice or LaTeX | Works well. Never seen: two letters, two policies and three syllabi (4–13 pages, from Word and Google Docs) all came back page for page with at least 97% of their words on the right page |
| Reports over 20 pages written in Word | Mixed. On the development documents the four NIST publications of 59–114 pages come back page for page in LibreOffice and Google Docs. Never seen: of four US government audit reports, one (30 pages) came back exact; the other three gained 2–4 pages (28 → 30, 44 → 46, 54 → 58) with 27–33% of their words on the right page, in LibreOffice and in Word |
| Long documents written in LaTeX | Mostly. Never seen: the hyperref manual (64 pages) and the LaTeX users' guide (27) came back page for page with at least 98% of their words on the right page; a 77-page arXiv technical report came back with 78 pages and 42% |
| Tables (merged cells, tables over several pages) | Works well |
| Simple two-column layouts | Works well |
| Résumés | Mostly. Never seen: 5 of 8 kept their page count with at least 90% of their words on the right page. A CMU sample résumé set came back with 9 pages for 8 (83% of words), a LaTeX AltaCV résumé kept its 2 pages with 88%, and a federal-style résumé from Word came back with 6 pages for 3 and about a third of its words on the right page |
| Headers, footers, page numbers, footnotes, links | Works well |
| Latin, Cyrillic and Greek text | Works well |
| Chinese, Japanese and Korean text | Partly. The text survives, but some runs become pictures |
| Long documents in Google Docs | Some long documents still gain pages. In the live Google Docs sweep, a 144-page EU regulation came back page for page, but IRS Publication 15 came back with 62 pages for 59, a World Bank report with 52 for 48, a 153-page LaTeX guide as 169, and a 40-slide deck as 54 |
| Designed reports (InDesign, Affinity Publisher, QuarkXPress, Microsoft Publisher: multi-column with full-bleed graphics) | Not yet. The text converts and mostly stays editable, but the layout does not hold in every reader: a designed Social Security Statement keeps its 2 pages in LibreOffice and Word, with 89% of its words on the right page, and becomes 3 in Google Docs, with 39% |
| Annual reports | Not yet. They are usually designed reports (above) |
| Multi-column booklets (IRS / GPO / Federal Register style) | Not yet. Narrow columns of small type re-wrap and grow. IRS Publication 501 (31 pages) became 45 pages in LibreOffice, 54 in Word and 57 in Google Docs, with under 30% of its words on the right page; the 126-page Form 1040 instructions became 135, 145 and 155 pages. The text survives as editable text (95–97% of it in LibreOffice) |
| Dense journal papers, equations | Not yet. A paper's flowing text converts, but equations are not rebuilt as editable math, and dense two-column journal layouts can gain a page: an 8-page arXiv paper became 9 pages in LibreOffice and Word and 10 in Google Docs, with 70% of its words on the right page in LibreOffice |
| Slide decks, brochures, posters | Not yet. Layouts break or become pictures: a 40-slide deck keeps its 40 pages in LibreOffice and Word, but about three quarters of its text sits in text boxes, and Google Docs makes 54 pages of it |
| Web pages printed from a browser | Not yet. Never seen: a 7-page Wikipedia article printed from Chrome came back with 8 pages and 33% of its words on the right page. (The sealed test had classed it, before it ran, as an ordinary promised document, and scored it so; the README now marks this kind "Not yet".) |
| Arabic, Hebrew and Persian (right-to-left) | Partly. Text arrives in reading order as right-to-left Word paragraphs; pages can grow where the reader lacks the source's fonts (an Arabic report 57 → 65 pages, a Hebrew paper 28 → 29, in LibreOffice). The Google Docs output is not yet right-to-left |
| Scanned pages with no text layer | Refused (exit code 17). No OCR is built in. Scans that already have an OCR text layer do convert |
| Fillable forms | Refused (exit code 19), because the result would look like the form without being one |
| Over 250 pages | Refused (exit code 20) unless you raise the limit with `--max-pages N` (`0` removes it) |

A refusal writes nothing and says why; [usage.md](../usage.md#exit-codes)
shows what it prints.

## Notes for beta testers

- **Long documents can still gain pages, most of all in Google Docs.** The
  beta needs 17 of the 21 promised test documents over 20 pages to keep their
  page count (within 2%, or one page) with at least 85% of their words on the
  right page. In the final measurement all 21 did in LibreOffice and in Word,
  and 18 in Google Docs. The three that did not, all in Google Docs: IRS
  Publication 15 came back with 62 pages for 59, a World Bank report with 52
  for 48, and a LaTeX guide with 169 for 153
  ([scorecard](../evidence/beta-readiness-2026-10-11.json)).
- **Word is measured too, and mostly agrees with LibreOffice.** The same DOCX
  files rendered by Word 16 (Office 2024): with the default settings 69 of 90
  test documents come back with exactly the right number of pages in Word,
  against 71 in LibreOffice, and Word opened all 90 without asking to repair
  one ([measurement](../evidence/release-documents-2026-10-11.json)). Word differs most on long reports, where a page it
  sets slightly taller spills onto the next, and on Japanese and Chinese text.
  The files open in Word's Compatibility Mode on purpose: Word's newer layout
  rules re-wrap justified paragraphs away from the PDF's own line breaks.
- **The LibreOffice layout check is slow on long documents**; see
  [install.md](../install.md#how-long-it-takes).
- **Reporting a bad conversion:** `exactdoc --diagnose your.pdf` prints a
  summary with none of the document's text, which you can paste into a
  [report](https://github.com/ebt55/exactdoc/issues/new?template=bad-conversion.yml)
  instead of attaching a private PDF.

## Limitations, in tiers

**Tier 1 — works today (the target class).** Ordinary digital documents:
reports, memos, letters, whitepapers, simple papers and résumés, simple
two-column pages, common (striped/ruled) tables, code listings,
headers/footers, footnotes, hyperlinks and TOC links, Latin, Cyrillic and
Greek text. Long single-column reports keep their page count: the four NIST
publications of 59–114 pages come back page for page in LibreOffice and Google
Docs (Word sets the 114-page one at 115). This is what the corpus measures and
the numbers below describe.

**Tier 2 — partially supported, measured limitations.**

- *Dense journal papers*: an 8-page two-column arXiv paper (`y41`) comes back
  as 9 pages in LibreOffice and Word and 10 in Google Docs, with 70% of its
  words on the right page in LibreOffice; equations come apart (Tier 3).
- *Chinese, Japanese and Korean text*: the text survives, but some runs
  become pictures.
- *Slide decks*: a 40-slide deck (`y34`) keeps its 40 pages in LibreOffice and
  Word, but 73% of its text sits in text boxes, and Google Docs makes 54 pages
  of it.

- *Complex and nested tables*: regional/nested table layouts are deferred;
  only conservative, strongly-evidenced striped tables are assembled.
- *Designed/vector-heavy pages*: gradients, rounded and rotated artwork are
  rasterised regions inside an otherwise-editable document, not recreated
  vector art (`c5_graphics`, parts of `04_exec_brief`).
- *Google Docs as the renderer*: the offline `gdocs` profile compensates for
  measured importer quirks (line-height mistranslation, ignored cell margins,
  whole-point row rounding, border-against-text-area charging, `pBdr` schema
  order, sub-minimum column merging). **The gdocs profile's confirmation is
  the Google Docs live test itself**: upload through the Drive API, export
  Google's own PDF, align page-by-page against the source, and inspect the
  renders — the local LibreOffice proxy is known to mispredict Docs, so no
  offline number is quoted for this profile without a live artifact behind
  it. The 2026-09-11 campaign on that protocol took a real 32-page report
  (tables, quote bars, a callout box, inline code) from 58 export pages to
  **CLEAN 1:1 at 32** — every source page mapping to exactly one export page
  — with named Heading styles so Docs' outline sidebar populates, quote bars
  and the callout box as real borders, tables partitioned cell-for-cell at
  the source's own column pitch, and hyphens kept where the source drew them.

**Tier 3 — explicitly out of scope for now.**

- *Heavy LaTeX/mathematics*: stacked scripts and equation layout are not
  reconstructed as editable math.
- *Highly designed pages* (magazine spreads, posters): not representable as
  flowing Word constructs; expect rasterised regions at best.
- *RTL scripts* (Arabic, Hebrew, Persian): partly supported since WP14. The
  parser hands over logical order (an inverse of the Unicode bidi algorithm at
  each line's base direction), and the standard profile writes right-to-left
  paragraphs (`w:bidi`, start/end alignment, `w:rtl` runs with complex-script
  size and font). The Google Docs profile still writes a visually equivalent
  left-to-right paragraph until `testkit/gdocs_probe_rtl.py` is graded live.
  Page fidelity depends on the reader having a face as narrow as the source's:
  the pinned renderer's Arabic faces (FreeSerif, DejaVu Sans) set Arabic
  27-45% wider than Arial or Noto Naskh, which is most of what still inflates
  y47 and y48. RTL tables keep visual column order (no `w:bidiVisual`).
- *Scanned / image-only PDFs*: rejected with an explicit OCR-required error.
  No OCR engine is bundled — by design, a wrong-but-confident transcription is
  worse than an honest refusal. A scan that already carries an OCR text layer
  (invisible text over the page image, as every scan-to-PDF workflow writes) is
  converted: the layer becomes editable text and the page image it duplicates
  is left out; `--ocr-layer image` keeps the scan as a picture instead.

### The specific ones, with numbers

Generated from the ratified quality policy and the live pass-7 evidence rather
than from recollection. Where a number is quoted it is measured.

**Multi-column booklets still inflate their page count; single-column
reports no longer do.** On the non-gating expansion corpus, single-column
NIST-class publications now come back page for page: the 80-page one at 80
and the 114-page one at 114 in LibreOffice (they were 96 and 136 in the
2026-09 measurement, and 1.98× and 2.75× before the inflation campaign). The
IRS booklets in narrow columns (the Antenna House dialect) are where the
remaining work lives:

| Document | Source pages | LibreOffice | Word | Google Docs | Words on the right page (LO / Word / Docs) |
|---|---:|---:|---:|---:|---|
| IRS Publication 501 (`y13`) | 31 | 45 | 54 | 57 | 0.29 / 0.29 / 0.26 |
| Form 1040 instructions (`y06`) | 126 | 135 | 145 | 155 | 0.28 / 0.20 / 0.21 |

(The 1040 instructions were 294 pages in the 2026-09 measurement.) The text
survives: 95–97% of it is live, editable text in LibreOffice. Pagination is
what moves, and once a page overflows everything after it lands on the wrong
page, which is why word recall is so low. The gated corpus is 1–7 pages and
cannot compound a per-page error into a page-count error, which is exactly
why this class is measured separately. **If your documents are multi-column
booklets, they are not ready.** Tracked as the headline post-release item
(n-column reconstruction).

**Interactive forms are refused, by contract.** A fillable AcroForm whose
content lives in its field values converts to a convincing-looking non-form —
measured at 0.085 SSIM on IRS Form 1040 while exiting zero, which is worse than
failing. `InteractiveFormError`, **exit code 19**. The threshold is a per-page
widget census: a page is a form page at 12+ widgets and the document is a form
when form pages are a tenth of it.

**There is a page cap, and it is a decision you can make.** 250 pages by
default. Over it, `PageLimitError`, **exit code 20** — the one resource refusal
you can answer: `--max-pages N` raises it, `--max-pages 0` removes it. Its own
exit code rather than a generic resource error precisely because it is
answerable.

**Image-only scans are refused.** `OcrRequiredError`, **exit code 17**. No OCR
engine is bundled.

**Google Docs adds about 14.6pt of white above a page-one cover band, and we
cannot remove it.** Probe-measured on Docs itself: requested top margins of
0/4/8/14.4/20pt render as 14.55/18.83/22.83/29.23/34.83 — an *addition*, not a
clamp, so no requested value reaches the paper edge. The writer compensates what
is compensable and accepts the floor. It costs `01_whitepaper_market` structural
similarity (mean_ssim 0.6909 against a 0.70 bar) and that document carries a
bounded, self-retiring waiver in the ratified policy. Side margins, by contrast,
Docs honours exactly, so a true side bleed is reachable and is used.

**Small residual drift on cover-heavy pages.** After the band itself is placed
correctly, a rasterised figure region can render a few points taller than its
source (measured +5.91pt on `c1_whitepaper`'s merged stat-card row), and the
error accumulates gently down a dense page. `c1_whitepaper` lands at dy_p50
5.56pt live against a 10.0pt bound — inside, and not zero.

**Page-top spacing after a hard break.** Renderers drop `w:spacing w:before` at
the top of a page following a hard break, so a paragraph that should start low
on a fresh page starts flush. Measured at −53pt on one gated document's page 2.
Emitting an explicit spacer paragraph is the shape of the fix; it is not done.

**Designed/vector pages score poorly and that is the honest outcome.**
`c5_graphics` is a page out and recalls 17% of its words, because the page *is*
artwork: the text is inside rasterised regions and counted as non-live by
design. It sits in the policy's non-blocking `designed_stress` tier for that
reason, not as an excuse.

**The `[mupdf]` extra changes nothing about output.** Both installs produce
identical DOCX content on all 16 gated fixtures, proven by content hash. It
exists only for the legacy PyMuPDF parser path and as the reference arm for
parity measurement — and it is AGPL-3.0-or-later, so installing it changes your
obligations for anything you distribute.

## What is not done

Honest queue, post-release. None of this is hidden in an issue tracker; the
numbers are measured.

**Headline defect — the multi-column booklet dialect (#38).** Booklets in
narrow columns under-pack them and inflate page counts. Single-column
NIST-class documents now keep theirs (80 → 80, 114 → 114 in LibreOffice), while
the IRS/Antenna House booklets still grow: 31 → 45 and 126 → 135 pages in
LibreOffice, more in Word and Google Docs (the table above). Everything after
the first overflow lands on the wrong page, so word recall collapses (0.20–0.29)
even though 95–97% of the text survives as live text. If your documents are
that dialect, this release is not for them yet.

| # | Item | Measured |
|---|---|---|
| **#38** | n-column under-packing | the page-inflation numbers above |
| #20 | `c2_paper2col` paragraph-box residual | 2.3pt |
| #23 | `assess` evidence-stamp schema | archived runs carry a `git` key the strict validator rejects, so a committed run cannot be re-assessed without de-stamping |
| #37 | gutter accumulation | drift compounds down multi-column pages |
| #42 | page-top spacing after a hard break | renderers drop `w:spacing w:before`; measured −53pt on one gated page 2 |
| #43 | `05_memo` shared displacement | +4.64pt on both arms — explicitly *not* excused by the ratified within2pt entry |
| #44 | `y10` discriminator | the metric moved because the reference degraded; the trade is adjudicated, the discriminator is not fixed |
| #47 | cross-platform byte deltas | 6 of 16 gated fixtures byte-identical across platforms; rasterised regions differ by hundreds of bytes, four image-free documents by 2–11 |

**Résumés got a fixture in 1.0.1, and it found six defects.** The corpus had no
résumé, so nothing had ever exercised role/date pairs sharing a baseline,
contact anchors covering less than half their span, or letter-spaced headings.
All six are fixed (see [CHANGELOG.md](../../CHANGELOG.md)); what remains is the tail.
Two-column résumés now land at `dy_p50` 0.38pt with `dy_p90` still 8.92pt — the
median is excellent and one word in ten is around nine points out. Reviewed live
in Google Docs and judged good enough to ship, not perfect. Single-column
résumés have no fixture and are therefore unmeasured, not implied.

**Font-style substitution is parked, by decision rather than by oversight.**
The fontTable now declares every family the document emits and an explicit
Normal typeface, so Docs is no longer guessing. What Docs then does with a style
it does not have — substituting a face of its own — is Docs' behaviour, and this
project does not chase it.

**The `01_whitepaper_market` waiver is live and nearly retired.** It sits at
mean_ssim 0.6909 against a 0.70 bar — **0.0091 away**. It is bounded, cites its
cause (Google's cover-band addition), and retires itself: if `01` reaches the bar
unaided the waiver goes stale and *blocks* every assess until it is deleted.

**Two items belong to the owner and cannot be closed by engineering.** LIC-01,
the provenance of the initial source and the right to relicense it, which
[docs/license-audit.md](../license-audit.md) explicitly does *not* cover; and
legal review of that audit, in particular the five corpus fixtures whose
public-domain basis is publisher identity rather than an explicit written grant.
Sole authorship removes no third-party obligation, and this is engineering work
rather than legal advice.
