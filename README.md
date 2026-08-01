# exactdoc

**PDF → DOCX that still looks right after you open it in Google Docs.**

Most converters optimise for Word or LibreOffice and treat Google Docs as
"close enough". It is not close enough: on a document where LibreOffice places
99% of words within 2pt of the source, Google Docs places 1% — because Docs adds
a one-off gap after the first heading, roughly 3pt at every paragraph boundary,
and has no "exact" line spacing at all. A layout tuned for one is measurably not
tuned for the other.

So the target is a decision this project makes explicitly, and the output stays
**editable** — live text, real paragraphs, real tables — rather than a page of
images that happens to look correct.

> ### Status: alpha, not published, and honest about it
>
> `0.1.0a1` · **AGPL-3.0-or-later today, Apache-2.0 next** (see
> [Licensing](#licensing)) · install from git only.
>
> The number that matters most has **not been measured yet**. Every fidelity
> figure below comes from LibreOffice standing in for Google Docs, because the
> Docs measurement harness is still being built. Google Docs is the target and
> the least-measured surface — including the full-bleed cover band, the
> headline layout feature, which has never been verified in Docs at all.
>
> Do not use this in production. Do use it on your own documents and
> [tell us what broke](#contributing).

---

## Install

```bash
git clone https://github.com/ebt55/exactdoc && cd exactdoc
pip install -e ".[test,pdfium]"
```

LibreOffice is needed only for the optional closed-loop correction and for the
measurement harness. Conversion itself is offline and needs neither it nor a
network.

## Usage

```bash
exactdoc report.pdf -o report.docx
```

Two settings decide almost everything, and they are **independent** — which is
the design point, not a detail:

```bash
exactdoc report.pdf --output-profile gdocs --oracle none --refine 0
```

| Setting | What it decides | Cost |
|---|---|---|
| `--output-profile` | how the OOXML is *written*. `gdocs` emits line heights Docs does not mistranslate | none — offline, deterministic, no network, no credentials |
| `--oracle` | what *renders* the result during closed-loop correction. `none`, `libreoffice`, `gdocs` | a subprocess, or a network round trip |

These used to be one field called `--target`, and the consequence was not
cosmetic: **there was no way to ask for Google-Docs-safe output produced
offline** — wanting Docs-shaped formatting implied uploading your document to
Google. Now it does not. `--oracle gdocs` requires `--allow-cloud-upload` per
invocation, and no environment variable can grant it.

```python
from exactdoc import convert

convert("report.pdf", "report.docx",
        output_profile="gdocs", oracle="none", refine_rounds=0)
```

`target=` still works for one alpha cycle and warns.

### Closed-loop correction

With `--refine N` and an oracle, the converter renders its own output back to
PDF, measures per-page drift against the source, and corrects. It is off the
critical path by design: `--oracle none` is a first-class answer, and a
requested oracle that is missing is now an **error** rather than a silent
downgrade to open-loop.

---

## What is actually measured

Two things are true at once and the distinction is the whole point of this
section.

### LibreOffice — the numbers of record

16 frozen fixture PDFs, pinned by SHA-256, measured in a digest-pinned container
so the renderer's fonts cannot drift. `product` is the shipped profile;
`raw` is the same converter with the feedback loop off, kept as a control
because a refined-only figure can improve by memorising the oracle.

| Lane | Page match | Mean within-2pt | Live text | Median vertical drift |
|---|---:|---:|---:|---:|
| product | 15/16 | 0.4981 | 0.9652 | 0.675 pt |
| raw | 13/16 | 0.3349 | 0.9652 | 2.2 pt |

### Google Docs — the actual target, barely measured

| | LibreOffice | Google Docs |
|---|---:|---:|
| mean within-2pt | 0.404 | ~0.20 |
| page match | 17/18 | 11/16 |

**Treat that column as exploratory, not as a baseline.** The two figures come
from different corpora and were not produced by a manifest-bound, same-run gate.
They are enough to establish the *direction* — Docs is the harder target — and
nothing more. Building the gate that can make a real claim here is the current
work.

### Generalisation: 0 out of 4

Four wild PDFs the converter has never been tuned against: **0/4 exact page
counts.** That number is published deliberately. Corpus figures measure a corpus;
this measures whether any of it generalises, and today it does not.

---

## Licensing

**[AGPL-3.0-or-later](LICENSE) today. Apache-2.0 planned, and not yet done.**

The copyleft is inherited, not chosen. exactdoc parses PDFs with PyMuPDF, which
is AGPL-3.0, so exactdoc must be too — and that single dependency blocks adoption
by everyone who cannot accept AGPL, which is most companies.

The fix is a permissive parser, and it is built: `pypdfium2` (PDFium, BSD-3).
Every code path already runs with PyMuPDF **physically absent** — proved by a
test that makes `fitz` unimportable and then converts real documents — so the
relicence is now a dependency-and-default change rather than a rewrite.

What is left is not code:

1. the permissive parser must show no unwaived fidelity regression against the
   incumbent (currently **2 unwaived**, both attributed to one font-metric cause,
   plus 4 more shortfalls held as explicitly *provisional*);
2. that decision should be made on **Google Docs** evidence rather than
   LibreOffice's, because Docs is the target;
3. a provenance and dependency review, which is a legal question and not a
   measurement.

**No AGPL wheel will ever be published.** The flip lands before the first
release, not after it. Until then this is a git-install project.

---

## Known limits

Three different kinds of problem, deliberately separated — because "we will fix
this", "this is physically impossible" and "this is possible but not worth it"
deserve different answers.

### 1. Open defects, on the roadmap

Measured, attributed, and expected to improve. Full register with severity and
reproduction commands in [STATUS.md](STATUS.md).

- **LaTeX/pdfTeX pagination** — the largest open defect. Text survives (94–97%
  live) but page counts inflate 25–90%. It is the reason the holdout is 0/4.
- **Nested tables** flatten and borders misplace.
- **Letter-spaced headings** lose their spaces: `TECHNICAL SKILLS` →
  `TECHNICALSKILLS`.
- **Mixed page geometry** is discarded — size and orientation come from page 1.
- **Rounded-corner stat cards** stack diagonally; the detector requires a rect.

### 2. Hard limits — these will not be fixed, because they cannot be

- **Pixel-perfect and editable is a contradiction.** Text reflowed by a
  different engine will sometimes break a line differently, and everything below
  a changed break moves. You can make it rare. You cannot make it impossible.
- **OOXML quantises font size to 0.5pt.** A 10.1pt source font cannot be emitted
  at 10.1pt. Compensable via wrap width; not removable.
- **Google Docs ignores embedded fonts.** Metric-compatible substitution is the
  ceiling, so exotic type will never land exactly.
- **Google Docs flattens per-section page geometry**, which puts full-bleed
  cover bands permanently at risk.
- **Gradients, rounded corners and rotated text** have no paragraph-flow
  equivalent in OOXML.

### 3. Dialects that will stay hard — where a fallback beats a fix

This is the honest one, and it is a scoping decision rather than a defect.

Some document classes are not "not yet supported" — they are structurally
expensive to support, and the effort is better spent elsewhere. Chiefly:

- **Heavy LaTeX/pdfTeX**, where the vertical model is built on TeX's glue and
  penalties rather than on anything OOXML can express, and small per-element
  errors accumulate into whole-page drift;
- **Highly designed pages** — magazine-style layouts, overlapping decorative
  elements, text on curves, dense infographics — where the source was never a
  flow document to begin with.

Chasing these to pixel fidelity means reimplementing a typesetting engine, and
the return curve is bad: three separate attribution attempts on the LaTeX
pagination defect each produced a partly-wrong answer.

**The pragmatic answer is a fallback, not a fix: rasterise the problematic
region and keep the surrounding text live.** A page that is 90% editable text
with one faithful image of an un-modellable figure is far more useful than a
page that is 100% "editable" and visibly wrong — and it is much more useful than
a whole page rasterised, which is what most converters do when they give up.

The converter already does this for gradients and vector artwork. Extending it
to *choose* rasterisation deliberately for these dialects — with a reported
budget, so you can see exactly how much of a page went to images and why — is
the intended treatment. Tracked as D10 in [STATUS.md](STATUS.md).

If your documents are mostly LaTeX papers or design-led pages, this tool is
probably the wrong choice today, and saying so is cheaper for both of us than
letting you find out.

### Also out of scope

- **Scanned/OCR-only PDFs** — no OCR pass, and none planned.
- **Encrypted and form/annotation-heavy PDFs.**
- Chart labels live inside the rasterised figure image, by design.

---

## How it works

1. **Parse** — glyphs, spans, lines, drawings, images, with positions.
   Two interchangeable backends: PyMuPDF (default today) and PDFium (permissive,
   the future default).
2. **Normalise** — detect the producer dialect and repair its known quirks
   before any layout decision is made.
3. **Infer** — reconstruct the page model: columns, headings, lists, tables,
   figure regions, headers/footers, cover bands.
4. **Write** — emit OOXML using only constructs Google Docs imports faithfully,
   with the line-height encoding chosen by the output profile.
5. **Refine** *(optional)* — render back, measure drift, correct, repeat.

The reasoning behind each stage, including the approaches that were tried and
measured worse, is in [THEORY.md](THEORY.md).

## Versions

| Version | What it means |
|---|---|
| `0.1.0a1` | today — alpha, AGPL (inherited from PyMuPDF), git install only |
| `0.2.0a1` | first *published* release: Apache-2.0, after the permissive parser is qualified against Google Docs |
| `0.x` betas | gated on the holdout number improving, not on the corpus number |
| `1.0` | not before wild PDFs stop failing on pagination |

## Documentation

- [ROADMAP.md](ROADMAP.md) — what is done, what is left, how far. Start here.
- [STATUS.md](STATUS.md) — the authority on every number, plus the defect
  register and the measurement mistakes that produced confident wrong answers.
- [THEORY.md](THEORY.md) — the fidelity model: what worked, what didn't, why.
- [testkit/README.md](testkit/README.md) — the measurement harness and its metrics.
- [docs/evidence/](docs/evidence/) — execution log and transition records.

## Contributing

**The most useful contribution is a PDF that breaks it.** Producer dialects
differ far more than content does, and the corpus is thin on LaTeX, Typst,
InDesign and Quartz.

```bash
python tests/test_gate_mutations.py
```

That checks the gate itself in about a second, with no corpus and no renderer.
For the full fidelity run — which needs the container — see
[testkit/README.md](testkit/README.md).

## License

[AGPL-3.0-or-later](LICENSE), inherited from PyMuPDF. See
[Licensing](#licensing) for why, and what replaces it.
