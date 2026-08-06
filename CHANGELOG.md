# Changelog

Notable changes to exactdoc. Every quality number in this file is measured in
the canonical environment (`docker/gate.Dockerfile`, pinned by digest) and
traceable to a committed artifact under `docs/evidence/`.

## 1.0.1 — 2026-08-07

A résumé went through the converter and came out wrong in ways the 16-document
corpus could not see, because it contained no résumé. Adding one
(`x17_resume_twocol`, with `x18_resume_twocol_tnr` as the control that removes
the monospaced run) exposed six defects at once. This release is those fixes and
the fixture that found them.

### Fixed

- **a hyperlink is a property of characters, not of spans.** The writer asked
  whether a span was *mostly* inside an anchor and tagged the whole span on a
  50% majority, so a link covering less than half its span was dropped
  entirely — which is what a contact header does when one word of a longer run
  carries the mailto. Spans now split at anchor boundaries and each character
  carries its own link.
- **a role and a date on one baseline are one row.** Two runs sharing a baseline
  were emitted as two paragraphs, stacking a right-hand date under the role it
  belongs beside. They are now one paragraph with a right-aligned tab stop.
- **the fontTable declares every font emitted, plus an explicit Normal
  typeface.** An undeclared family is not an error in OOXML; it is an
  invitation, and Google Docs accepted it by substituting its theme face —
  Georgia arrived as something else.
- **tracking is not word spacing.** PDFium fabricates space characters inside
  letter-spaced runs, and those were kept as text, so a tracked heading arrived
  with gaps in it. `_drop_tracking_spaces` removes the fabricated ones and
  leaves real spaces alone.
- **a tracking change ends a paragraph.** A letter-spaced line among
  un-letter-spaced ones is a heading; without that boundary it welded to the
  body text beneath it.
- **hashed JSON is byte-pinned to LF in `.gitattributes`.** A checkout that
  normalised line endings produced a different digest from the one recorded,
  and it failed in both directions — a clean tree reading as modified, and a
  modified tree reading as clean.
- **CI discovers tests instead of naming five files.** The suite had grown to
  663 while CI still ran five script-style suites by name.

### Measured

Confirmation sweep over 31 expansion documents: 25 unchanged, the résumé pair
improved, and the four other movers shown to be render noise by an IR-identical
control on `x11` that establishes a 2.3% noise floor. `y13`'s tab-stop rows fire
but are invisible at its scale.

`x17`/`x18`, before → after: `dy_p50` 3.13 → **0.38pt**, `dy_p90` 25.43 →
**8.92pt**, `within2pt` 0.0590 → **0.1022**, `mean_ssim` 0.8422 → **0.8733**.
Reviewed live in Google Docs and approved. Both runs are committed:
[docs/evidence/sweep-1.0.1-expansion-2026-08-06.md](docs/evidence/sweep-1.0.1-expansion-2026-08-06.md)
indexes the two result sets and their logs, and records what they do and do not
authenticate.

`word_recall` reads 0.9443 → 0.8719 across the same change, and that is a
**reference artifact rather than a text regression**: the harness reference was
extracted with the same PDFium fragmentation this release fixes, so it holds no
whole heading tokens to match against. The converted document gained the
headings; the yardstick never had them.

### Known limitations, carried

- **#48 — ink-vs-advance space synthesis.** Space insertion measures ink extent
  rather than advance width, so a narrow glyph pair can lose its space
  (`A smaller` → `Asmaller`).
- **#47 — cross-platform byte deltas.** Same input on the same platform gives
  identical bytes; across platforms, 6 of 16 gated fixtures match exactly.
  Documents carrying a rasterised region differ by hundreds of bytes, because
  image encoders are not required to be reproducible across platforms, and four
  image-free documents differ by 2–11 bytes for a reason not yet chased.
- **font-style substitution.** Google Docs renders substitute faces for styles
  it does not have. Parked by owner decision: the fontTable now declares what
  the document uses, and what Docs does with that declaration is Docs'.

## 1.0.0 — 2026-08-06

**High-fidelity PDF → DOCX, tuned for documents that have to survive Google
Docs' importer. Apache-2.0. PDFium (pypdfium2) is the core parser; nothing in a
default install carries a copyleft term.**

The version is 1.0.0 because the release bar is met *and live-validated*: the
converter qualifies against the ratified quality policy in Google Docs itself,
not against a local renderer standing in for it.

### The release gate

Live pass 7, consented, against Google Docs —
[qualification](docs/evidence/gdocs-2026-08-06-pass7-qualification.json) ·
[assessment](docs/evidence/gdocs-2026-08-06-pass7-assessment.json):

- `overall_pass: true`, **zero blocking findings** across the 13 blocking
  documents of the ratified policy
- 16/16 documents uploaded, converted, exported and deleted; zero orphaned
  Drive objects
- the uploaded DOCX were verified byte-identical to what a PyMuPDF-free install
  produces, so the run qualified the product a user gets

Regression gate at the bound baseline, both lanes PASS
([re-record](docs/evidence/cover-band-seed-rerecord-2026-08-06.json)):

| lane | page match | mean within-2pt | mean live text | median dy50 |
|---|---:|---:|---:|---:|
| product | 16/16 | 0.5274 | 0.9588 | 1.045pt |
| raw | 15/16 | 0.3615 | 0.9588 | 1.6pt |

### Licence

Relicensed from AGPL-3.0-or-later to **Apache-2.0**. The migration was gated on
four proofs, all recorded: parser parity ratified, two clean consented Google
Docs passes, the [base-wheel proof](docs/evidence/base-wheel-proof-2026-08-06.json),
and the [licence audit](docs/license-audit.md).

PyMuPDF moved out of the core dependency set into an optional `mupdf` extra.
**Installing that extra does not change output** — both installs produce
identical DOCX content on all 16 gated fixtures, proven by content hash. It
exists only for the legacy parser path and for the parity reference arm, and it
is AGPL-3.0-or-later: adding it changes your obligations for anything you
distribute.

### What changed to get here

- **PDFium replaces PyMuPDF as the shipping parser.** The line and block
  clustering PDFium does not provide is written here (`exactdoc/parse_pdfium.py`).
  Four parity findings at the shipping profile were measured and ratified before
  the swap, not after.
- **Permissive text metrics.** The quality ladder shapes text from the published
  Adobe AFM widths (`exactdoc/_base14_widths.py`, generated by
  `testkit/gen_base14_widths.py`), so it works with no optional extra. It is
  deliberately *not* bug-compatible with MuPDF, whose base-14 lookup is Latin-1
  only and charges the space width for em dashes, curly quotes and 25 other
  WinAnsi codepoints.
- **Cover bands inset from the paper edge are recognised.** A band starting
  7.16pt down was treated as ordinary body content, losing both the full-bleed
  side treatment and the Docs vertical compensation; in Google's own export it
  landed 54.5pt right of source and overflowed the page. See
  [the attribution](docs/evidence/c1-live-attribution-2026-08-06.json).
- **Refusals are typed and have stable exit codes**: interactive forms (19),
  page cap (20), OCR-required (17), and the rest of `exactdoc/errors.py`.
- `--verify` compares one page pair at a time; peak RSS on a 259-page comparison
  fell from 5,340 MB to 237 MB.

### Known limitations

Stated in the README's "Limitations" section, generated from the ratified policy
rather than from recollection. The short version: dense multi-column booklets
inflate their page count, interactive forms and image-only scans are refused
rather than mangled, and roughly 14.6pt of white above a page-one cover band is
Google's own and cannot be removed.

## 0.1.0a1

Pre-release development. See the git history and `docs/evidence/` — the
measurement trail starts well before this changelog does.
