# How exactdoc works, and how it got here

> Moved from the README in October 2026 so the front page could stay short.
> Nothing here was rewritten: the numbers are as they stood when each paragraph
> was written. [status.md](status.md) and the [CHANGELOG](../../CHANGELOG.md) are
> the authority on current figures.

## The idea

Most PDF→Word converters give you either a pile of text boxes frozen at absolute
positions (looks right, unusable to edit) or reflowed text that has lost the
layout (editable, looks wrong). exactdoc aims at both at once for ordinary
digital documents: it infers the *semantic* structure — margins, paragraphs,
headings, lists, tables, multi-column sections, headers/footers, hyperlinks —
and writes real flowing Word constructs whose rendered geometry matches the
source page to within points, verified by measurement.

## What it does

- **Editable output, not text boxes.** Paragraphs are real paragraphs with
  correct spacing, indents, alignment and line leading; tables are real DOCX
  tables; lists keep their markers; hyperlinks and internal TOC links stay live.
- **Measured fidelity.** A closed refinement loop renders the produced DOCX
  back to PDF (LibreOffice headless by default), compares word positions
  against the source, and corrects page overflow and per-page offsets. The
  test harness reports word recall, horizontal/vertical drift percentiles,
  SSIM and ink IoU per document.
- **Honest degradation.** Designed regions it cannot represent as flowing text
  (gradient graphics, rotated art) are rasterised so the rest of the document
  stays editable — and the live-text metric counts that trade-off instead of
  hiding it. Image-only scans are rejected with an explicit OCR-required error
  rather than silently converted to blank output.
- **Two parser backends.** PDFium via pypdfium2 (core, shipping) and PyMuPDF
  (optional `[mupdf]`, the reference arm every parity record is measured
  against). Shared inference contains no backend conditionals; a parity harness
  compares the two. A default install contains no AGPL code.
- **A Google Docs output profile.** `output_profile="gdocs"` writes OOXML that
  survives Google Docs' importer (which mistranslates exact line heights,
  ignores cell margins in places, and inserts extra paragraph spacing) using a
  static, offline translation layer — no upload required.

## How it got here

The hard part of PDF→DOCX is not parsing. It is that a PDF says *where ink went*
and a DOCX says *what the document is*, and the second cannot be derived from the
first without guessing. Everything below is about making those guesses
falsifiable.

**Measurement came before the converter.** The harness renders the produced DOCX
back to PDF, matches words to the source, and reports word recall, drift
percentiles, SSIM and ink IoU per document. That loop is not a test suite bolted
on afterwards — it is the thing the converter is written against, and it is also
a *closed* loop at runtime: the refinement pass reads its own rendered output and
corrects page overflow and per-page offsets before publishing.

**The corpus is frozen, and freezing it was the point.** Sixteen documents pinned
by SHA-256, because a corpus that regenerates is a corpus whose numbers mean
nothing across commits. That is not theoretical: a Chromium update once changed
`c4_i18n` into a different document and moved its drift fivefold with nothing in
the repository changing. Fixtures are bytes, not recipes
([docs/corpus-expansion.md](../corpus-expansion.md)).

**The environment is an artifact with a digest.** Fidelity is a property of a
renderer as much as a converter, so "canonical" cannot mean "our CI runner" —
`ubuntu-24.04` moves its LibreOffice build, its fonts and its Python underneath
you. `docker/gate.Dockerfile` pins the base image by digest and the five font
packages `scripts/fonts.conf` makes visible; an unpinned font set once moved
`c4_i18n`'s drift 0.15pt → 2.1pt. A new digest is a new environment and a
deliberate baseline migration, never a side effect of a rebuild.

**LibreOffice is a proxy, and proxies lie.** The product targets Google Docs, so
the project built a consented, two-step, offline-preparable oracle that uploads
the real DOCX, converts it in Docs, exports the result and measures *that*. It
found things no local renderer could. Docs adds ~14.6pt above a page-leading
cover band unconditionally — probe-measured as an addition, not a clamp
(requested 0/4/8/14.4/20pt render as 14.55/18.83/22.83/29.23/34.83). A 3pt
per-boundary compensation that looked right against LibreOffice was, measured
against Google's own exports across 187 boundaries, subtracting space Docs never
added — its real contribution is about +0.1pt. Seven live passes took blocking
findings from eleven to zero.

**Acceptance is data the gate executes, not prose someone is trusted to apply.**
Every known shortfall lives in a policy file with numeric floors in *both*
directions: worsening past a floor fails, and so does clearing the divergence
entirely, because a waiver describing nothing still excuses a document and hides
the next regression on it. Waivers separate `provisional` (visible, bounded,
authorises nothing) from `ratified` (a named owner, a date, an issue and a review
condition — all four required and checked). Policies bind to one full profile and
one corpus and refuse to adjudicate anything else, which is why there are three of
them; a finding measured at the shipping settings says nothing about the
candidate profile, and the readers refuse to borrow across that line.

**The parser swap was gated on proofs, not confidence.** PyMuPDF is AGPL, which
made the whole project AGPL, so the target was PDFium — but PDFium hands you
glyphs, not lines and blocks, so that clustering had to be written here
(`exactdoc/parse_pdfium.py`). Parity was measured document by document and
dimension by dimension, and the four findings at the shipping profile were
ratified *before* the swap, against Google's evidence rather than the proxy.
A control run confirmed the old parser still reproduces the old record exactly
from the same tree, so the baseline movement is the parser and nothing else
([parity](../evidence/parity-expanded-2026-08-05f.json) ·
[flip](../evidence/parser-default-flip-2026-08-06.json)).

**The last AGPL thread was a text metric.** The quality ladder shapes text, the
only shaper was MuPDF's base-14 width tables, and that quietly made an optional
extra a quality axis: a default install produced worse output on three fixtures.
Those tables are published Adobe AFM data, so they now ship
(`exactdoc/_base14_widths.py`), and both installs produce byte-identical DOCX on
all 16 fixtures — verified by content hash from a virtualenv that never had
PyMuPDF ([proof](../evidence/base-wheel-proof-2026-08-06.json) ·
[shaper](../evidence/permissive-shaper-2026-08-06.json)).

**What refuses is as designed as what converts.** An interactive form whose
content lives in field values converts into a convincing-looking non-form; it was
measured at 0.085 SSIM *while exiting zero*, which is worse than failing. Scans,
forms and over-cap documents now raise typed errors with stable exit codes (17,
19, 20). A wrong-but-confident answer is the one outcome the project treats as
unacceptable.
