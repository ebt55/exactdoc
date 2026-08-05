# exactdoc licence and provenance audit

**This is an engineering audit, not legal advice.** It records what the project
depends on, what it redistributes, and where each of those came from, so that a
qualified reviewer has facts to work from rather than recollections. Every
licence below was read from installed package metadata or from a licence file
shipped inside the package — not from memory, and not from a web search. Where
the basis for a claim is weaker than an explicit written grant, this document
says so rather than rounding up.

The relicensing question was narrow: exactdoc was AGPL-3.0-or-later **only**
because PyMuPDF was a core dependency. The target was Apache-2.0. This audit
asks one question of everything the project touches: *does this constrain that
change?*

> **STATUS, 2026-08-06: the change has been made.** PyMuPDF moved to an optional
> `mupdf` extra, pypdfium2 became the core parser and the default backend, and
> `LICENSE` is now Apache-2.0. §§1–6 below are preserved as the audit that was
> performed *before* the switch — they are the reasoning the decision rested on
> and are deliberately not rewritten into the past tense, because an audit
> edited to agree with its own conclusion is not evidence. What changed is
> recorded in §7 (gates), §8 (what the base-wheel proof now proves) and §9
> (which switch steps are done). **§10's open items are still open**, and two of
> them — the provenance of the source itself, and legal review — were never
> gates this work could close.

---

## 0. Method, and what "verified" means here

Dependency **licences** were read with `importlib.metadata` from the pinned
environment (`uv.lock`, resolved into `.venv`), taking `License-Expression`,
`License` and the `License ::` classifiers from each installed distribution.
Bundled native-library licences were read from the licence files inside the
installed wheel. Corpus provenance was read from
`testkit/corpus_manifest.json` and `testkit/corpus_expansion.json`.

**The dependency *relationships* — what is core and what is an extra — were read
from `pyproject.toml`, never from installed metadata, and that distinction is
load-bearing.** A third-party package's own `.dist-info` states its licence
accurately, because it was built from that project's own source. exactdoc's own
`.dist-info` is a different matter: it is frozen at install time, and an
editable install does not refresh it when the source tree changes. At the time
of writing, the development virtualenv's metadata reported `pypdfium2` as a core
requirement and `pymupdf` behind an `mupdf` extra — **the exact inverse of what
`pyproject.toml` declares**. An auditor reading dependency structure out of that
environment would have concluded the AGPL dependency was already optional, which
is the single most consequential thing it is possible to be wrong about in this
document, wrong in the reassuring direction. `tests/test_packaging_metadata.py`
now reports that divergence on every run.

Versions are named throughout, because a licence claim without a version is a
claim about a package that may not exist any more — iText is the standing
example, permissive at 2.1.7 and AGPL from 5.x, same name.

Two things this audit did **not** do: it did not consult upstream websites to
confirm that installed metadata matches the project's published licence, and it
did not examine the full text of every bundled licence beyond enough to
classify it. Both are appropriate at legal review.

---

## 1. Core runtime dependencies

From `[project].dependencies` in `pyproject.toml`. These install with a bare
`pip install exactdoc` and are therefore the licence surface of the shipped
product.

| package | version | licence (as installed) | role | Apache-2.0 compatible? |
|---|---|---|---|---|
| **pymupdf** | 1.28.0 | **Dual: GNU AFFERO GPL 3.0 or Artifex Commercial** | shipping parser (`exactdoc/parse.py`) | **NO — this is the blocker** |
| python-docx | 1.2.0 | MIT | DOCX writer | yes |
| numpy | 2.5.1 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | raster comparison, metrics | yes |
| pillow | 12.3.0 | MIT-CMU | image handling | yes |
| lxml | 6.1.1 | BSD-3-Clause | OOXML manipulation | yes |

**Verdict: one blocker, and it is the expected one.** PyMuPDF's AGPL arm is what
makes exactdoc AGPL; the alternative arm is a paid Artifex commercial licence,
which is a purchasing decision and not a path this audit assumes. Removing
PyMuPDF from the core dependency list is necessary and — on the evidence of
§§2–4 — very close to sufficient.

The code already models this as data rather than as prose:
`exactdoc/backend.py` carries `license = "AGPL-3.0"` on `PyMuPDFBackend` and
`license = "Apache-2.0"` on `PDFiumBackend`. The seam knows which side it is on.

---

## 2. Optional extras

| extra | package | version | licence (as installed) | role | Apache-2.0 compatible? |
|---|---|---|---|---|---|
| `pdfium` | pypdfium2 | 5.12.1 | BSD-3-Clause, Apache-2.0 (+ bundled, see §3) | candidate parser | yes |
| `gdocs` | google-api-python-client | 2.198.0 | Apache-2.0 | Drive/Docs oracle | yes |
| `gdocs` | google-auth-httplib2 | 0.4.0 | Apache-2.0 | transport | yes |
| `gdocs` | google-auth-oauthlib | 1.4.0 | Apache-2.0 | OAuth flow | yes |
| `test` | reportlab | 5.0.0 | BSD | corpus generation | yes |
| `test` | **fpdf2** | 2.8.7 | **LGPL-3.0-only** | corpus generation | yes — see below |

### fpdf2, stated crisply

fpdf2 is **LGPL-3.0-only**, which is the strongest copyleft term in the extras,
and it is nonetheless a non-issue for the relicence. Four facts, each checkable:

1. It is in the `test` extra. It is never installed by `pip install exactdoc`,
   with or without `[pdfium]` or `[gdocs]`.
2. `import fpdf` appears **once** in the entire repository —
   `testkit/gen_corpus.py` — and never anywhere under `exactdoc/`. No shipped
   module imports it, directly or transitively.
3. Its role is to *generate corpus input*. The LGPL governs the library, not
   the documents the library produces; the two PDFs it made
   (`f1_fpdf_brief.pdf`, `x16_fpdf_bulletin.pdf`) are this project's content on
   the same basis as everything else it generated.
4. Even taken at its worst, the LGPL's linking terms attach to a work that
   links the library. Nothing exactdoc distributes does.

The same reasoning covers reportlab (BSD, so the question does not arise) and
is the general principle for §5: **the licence of the tool that made a file
does not attach to the file.**

---

## 3. The PDFium binary, and the 16 components inside it

This is the part of the audit that actually matters for Apache-2.0, because
`pypdfium2` is not pure Python — the wheel carries a compiled PDFium and its
vendored dependency tree. The wheel ships a licence manifest, and every entry
below was read from it (`pypdfium2-5.12.1.dist-info/licenses/`).

| component | licence as shipped | permissive? |
|---|---|---|
| pdfium | BSD-3-Clause (© 2014 The PDFium Authors) | yes |
| pdfium-binaries | MIT (© 2014–2025 Benoit Blanchon) | yes |
| abseil | Apache-2.0 | yes |
| **agg23** | **AGG 2.3 permissive grant** — "Permission to copy, use, modify, sell and distribute this software is granted provided this copyright notice appears in all copies" | **yes — verified, see note** |
| fast_float | MIT | yes |
| freetype | The FreeType Project License (FTL) | yes |
| icu | Unicode License v3 | yes |
| lcms | MIT (Little CMS) | yes |
| libjpeg_turbo | two BSD-style licences (IJG + BSD) | yes |
| libopenjpeg | BSD-2-Clause | yes |
| libpng | PNG Reference Library License v2 | yes |
| libtiff | libtiff licence (BSD-style, Leffler/SGI) | yes |
| llvm-libc | Apache-2.0 with LLVM Exception | yes |
| simdutf | MIT | yes |
| zlib | zlib licence | yes |

**The two worth having actually checked, rather than assumed:**

- **AGG.** Anti-Grain Geometry relicensed to GPL at version 2.4. PDFium vendors
  **2.3**, whose grant is the permissive one quoted above. Had it been 2.4 this
  audit would have a second blocker. This is precisely the class of fact that a
  licence audit exists to catch, and precisely the class that is wrong when
  recalled rather than read.
- **FreeType.** Dual-licensed upstream (FTL or GPLv2). The text bundled in this
  wheel is the FTL and contains no GPL reference at all, so the copy PDFium
  ships is the permissive arm.

**Verdict: PDFium is fully compatible with an Apache-2.0 exactdoc**, subject to
an attribution obligation. Several of these licences (BSD, MIT, FTL, libpng,
zlib) require the copyright notice to travel with binary redistribution. Apache
projects satisfy that with a `NOTICE` file; §9 lists it as a switch step.
Note the obligation belongs to whoever redistributes the PDFium binary — today
that is the pypdfium2 wheel, which carries its own manifest, not exactdoc,
which merely depends on it.

---

## 4. Copyleft sweep across the whole resolved environment

Direct dependencies are not the whole graph. All 35 distributions installed in
the pinned environment were scanned for any copyleft term.

| package | version | licence | reachable from |
|---|---|---|---|
| exactdoc | 0.1.0a1 | AGPL-3.0-or-later | *the thing being changed* |
| pymupdf | 1.28.0 | AGPL (dual) | **core** — §1 blocker |
| fpdf2 | 2.8.7 | LGPL-3.0-only | `test` extra only — §2 |
| certifi | 2026.7.22 | MPL-2.0 | transitive, `gdocs` extra |

**Nothing else in 35 packages carries any copyleft term.** certifi's MPL-2.0 is
file-level copyleft: it reaches modifications to certifi's own files, and
redistributing it unmodified as a separate installed component — which is all
that happens here — is not a constraint on exactdoc's licence.

**This is the audit's headline.** Removing PyMuPDF from the core dependency
list is the *only* code-licence blocker in the entire dependency graph.

---

## 5. Distributed content: the committed corpus

47 PDFs are tracked in git and therefore **redistributed by this repository**.
Unlike dependencies, these are content, and each needs a basis to be shipped.

| location | count | pinned by | gating |
|---|---:|---|---|
| `testkit/fixtures/` | 16 | `testkit/corpus_manifest.json` | yes |
| `testkit/fixtures_expansion/` | 29 | `testkit/corpus_expansion.json` | no (`gating: false`) |
| ~~`tmp/pdfs/`~~ | ~~2~~ | **nothing** | removed — see §5.3 |

45 of the 47 were manifested. Finding the other two is why this section counts
the tree instead of reading the manifests.

### 5.1 The gated 16 — sound basis, unrecorded

Every one of the 16 was generated by a script in this repository:
`testkit/gen_corpus.py` (11) and `corpus/make_corpus.py` (5), per each entry's
`generator` field. The redistribution basis is therefore authorship, and in a
sole-author repository that is as clean as it gets.

**Finding: the basis is inferred, not recorded.** `corpus_manifest.json` entries
carry `sha256`, `bytes`, `content`, `dialect`, `generator`, `src_pages` and
`why` — and **no provenance or licence field at all**. The expansion manifest
does this properly; the older, gating one does not. Nothing is wrong today; what
is missing is the record that says so.

**This is not a free fix, and the coupling is worth stating.** Adding a
provenance block changes `corpus_manifest.json`'s own SHA-256, which is pinned
by `testkit/gdocs_quality_policy.json` and — since the fail-closed fix — now
*raises* rather than silently skipping quality evaluation. Per
`docs/corpus-expansion.md` §7 it must land as one commit carrying the manifest,
the re-pinned quality policy and the re-pinned parity policy together.

### 5.2 The 29 expansion fixtures

16 generated, 13 downloaded, none gating.

**Generated (16).** `provenance.license` recorded `AGPL-3.0-or-later`, stamped
from `LICENSE` in `testkit/gen_expansion.py`. Sole authorship means these can be
relabelled at will, but the label is a mechanical switch step (§9) — an
AGPL-labelled corpus inside an Apache-2.0 repository is a contradiction a reader
will trip over long before a lawyer does.

> *Done 2026-08-06: all 16 now record `Apache-2.0`, and
> `expansion_parity_policy.json`'s content pin was moved in the same commit. The
> policy's rule that re-pinning means re-checking every entry was discharged by
> proof rather than re-measurement — the manifest diff is exactly 16
> `provenance/license` leaves and every per-document `sha256` and `bytes` is
> identical, so no floor can describe different bytes than it did.*

**Downloaded (13).** The corpus agent recorded, per document, both the licence
claimed *and* whether the document itself says so — a distinction this audit
did not have to reconstruct because it was captured at acquisition. That is the
right practice and it is what makes the table below possible.

| basis | count | documents |
|---|---:|---|
| **Explicit statement inside the document** | 8 | `y01`, `y02`, `y08`, `y09`, `y11`, `y12`, `y13`, `y17` |
| **Publisher identity only — no notice in the document** | 5 | `y03`, `y06`, `y07`, `y10`, `y14` |

The five publisher-identity documents record their silence *as* silence — e.g.
`y03_nist_fips197`: "none found in front or back matter; no copyright or
trademark notice appears anywhere in the document. It is a NIST Federal
Information Processing Standard, a US Government work by publisher identity."
The reasoning (US Government works, 17 U.S.C. 105) is sound and the evidence URL
is recorded, but the basis is weaker than a written grant and is flagged here as
the corpus agent flagged it. **A reviewer should look at these five first.**

**`y17_rfc9110.pdf` is the one exception, and it is not public domain.** 12 of
the 13 claim US Government public domain; y17 is under the **IETF Trust Legal
Provisions**: verbatim redistribution of unmodified copies is permitted, and
modification or derivative works outside the IETF Standards Process are **not**.
The corpus stores an unmodified, byte-identical copy, which is exactly the use
the TLP permits — and the corpus's existing freeze discipline ("never regenerate
in place", `docs/corpus-expansion.md` §6) is what keeps it that way. It must
never be edited, trimmed or re-rendered. Worth noting the compliance here is
currently a *consequence* of a rule adopted for measurement reasons, not a rule
adopted for licence reasons.

**On producer strings.** Three IRS fixtures (`y06`, `y12`, `y13`) record
`modified using iText 2.1.7 by 1T3XT`. That is provenance metadata about the
toolchain, not a licence input — the principle from §2 applies unchanged. It is
worth reading anyway, for the reason §0 gives: iText 2.1.7 predates iText 5's
move to AGPL, so the version in the string is the load-bearing part. *(The
coordinator referenced a discarded GAO document stamped by an AGPL iText build
as the concrete example; that specific note is not in the tree — `y05_gao_report`
is documented in `docs/corpus-expansion.md` as discarded on page-count and size
grounds, with a qualification about embedded images — so it is not cited as
evidence here.)*

### 5.3 Finding, now resolved: five tracked files with no basis at all

`tmp/pdfs/` contained five committed files — `l1_word_native.pdf`,
`l1_symbol_fix.pdf`, `l1_symbol_fix.docx`, `l1_source.png`, `l1_symbol_fix.png`
— added incidentally by commit `0d3d03e` ("Updating .md files."). They appeared
in neither manifest, and `.gitignore` had no `tmp` entry. **This is how the
count reached 47 against 45 manifested.**

They derive from this project's own `l1` fixture, so the redistribution basis
was the same as §5.1 — but nothing recorded it, and there was a sharper problem
than tidiness:

| | bytes | sha256 | content fingerprint |
|---|---:|---|---|
| `testkit/fixtures/l1_word_native.pdf` (pinned) | 44,035 | `fa9e0742…` | `28c27dbb…` |
| `tmp/pdfs/l1_word_native.pdf` (shadow) | 81,769 | `dddef295…` | `28c27dbb…` |

**Same name, same document, different bytes.** The content fingerprint — page
geometry plus whitespace-normalised text, carrying no timestamp — is identical,
so nothing a reader could see distinguished the two files. Only the manifest's
sha256 did, and only for the copy the manifest described.

**Resolved:** nothing referenced them (verified by grep across the tree), so
they were removed from tracking and from disk, and `tmp/` was added to
`.gitignore`. The bytes remain recoverable from `0d3d03e`. Recorded in
`docs/evidence/execution-log.md`.

### 5.4 Embedded font metrics — `exactdoc/_base14_widths.py` *(added 2026-08-06)*

The corpus is no longer the only data this repository redistributes. The
permissive text shaper embeds the advance widths of the 14 standard PostScript
faces — roughly 1,300 integers across six tables — and they ship inside the
wheel, so they need a basis like anything else.

| | |
|---|---|
| **What** | Adobe Font Metrics advance widths, 1/1000 em, WinAnsi repertoire, for Helvetica/Times/Courier and their bold and italic variants |
| **Taken from** | `reportlab.pdfbase._fontdata` (reportlab 5.0.0, **BSD-3-Clause**), a `test`-extra dependency |
| **Also published in** | ISO 32000 (the PDF specification) Annex D, and Adobe's own AFM files; carried by essentially every PDF toolkit |
| **Generated by** | `testkit/gen_base14_widths.py`, with `--check` for staleness |
| **Verified against** | PyMuPDF, glyph by glyph — 2,190 Latin-1 cells identical across all ten faces |

**Why this is not a licence problem, stated rather than assumed.** Three
independent points, and the first is the one that matters:

1. **These are measurements of a typeface, not a creative work, and they are
   published.** The same integers appear in the PDF specification. reportlab is
   the convenient BSD-3 source, not the origin.
2. **They are deliberately not taken from MuPDF.** exactdoc is Apache-2.0
   *because* PyMuPDF left the dependency graph; copying its tables back in as
   literals would have undone that in the least visible way possible. The
   generator's docstring says so, the data file's header says so, and
   `tests/test_base14_metrics.py` re-derives the reportlab comparison as an
   assertion so a future hand-edit fails the suite.
3. **BSD-3 attribution.** reportlab's own licence travels with reportlab, which
   this repository does not vendor — only the published values it exposes. If a
   reviewer prefers belt and braces here, the remedy is a line in a `NOTICE`
   file, and §9 item 1 records why there is not one yet.

**For a reviewer:** this is the one place where a licence question turns on
"are these numbers copyrightable at all", and this audit does not pretend to
answer that. It records what was copied, from where, under what terms, and what
was deliberately not copied. §10 item 2 (legal review) covers it.

---

## 6. Measurement infrastructure — used, not distributed

`docker/gate.Dockerfile` builds the canonical measurement environment:
`ubuntu:24.04` pinned by digest, `libreoffice-writer` (MPL-2.0), Playwright's
`chrome-headless-shell`, and five font packages — `fonts-liberation` (SIL OFL),
`fonts-dejavu-core`, `fonts-freefont-ttf` (GPL with font exception),
`fonts-wqy-zenhei` (GPL with font exception), `fonts-ipafont-gothic` (IPA Font
License).

**None of this constrains exactdoc's code licence, for three reasons.** It is
not distributed with exactdoc — it is a container the project builds to measure
in, and the published artifact is an image, not part of any wheel. It is not
imported by exactdoc — no shipped module calls LibreOffice or Chrome as a
library; `exactdoc/verify.py` invokes `soffice` as an external process, which is
use, not linking. And it is not committed — **zero** font, shared-object or
other binary files are tracked in this repository (verified across every tracked
path). What the repository *records* from this environment is hashes and version
strings, in `testkit/canonical_env.json` and the evidence files; recording a
digest of a file is not conveying the file.

The relationship is the ordinary one between a program and the instrument used
to measure it: exactdoc converts PDF to DOCX, and LibreOffice renders the result
afterwards so it can be scored. A GPL font renders a page; it does not thereby
govern the converter.

**One item does need a reviewer's eye, and it is the only place an
infrastructure licence can reach distributed bytes.** The corpus fixtures are
*generated inside this image*, and generated PDFs embed font subsets. So font
licences touch files this repository does redistribute. Every one of the five
packages is either OFL/permissive or carries an explicit font-embedding
exception — which is the clause that exists for exactly this situation — so the
expected answer is that embedding is permitted. This audit flags it rather than
concluding it: confirm at legal review which fonts are actually embedded in the
45 fixtures and that each licence permits it.

---

## 7. Relicense gate status

ROADMAP names four gates. **All four are met, and the switch has landed.**

| # | Gate | Status | Evidence |
|---|---|---|---|
| **(a)** | Expanded same-profile parity with no unratified regressions | **MET** (commit `a3dd2ef`) | Zero unratified findings across all four adjudication paths. `docs/evidence/parity-expanded-2026-08-05f.json` is the binding measurement; the two formerly-provisional D10 findings — `c4_i18n` complex-script raster fallback and `c5_graphics` designed-page rasterisation — were **ratified** on 2026-08-04 under DEC-D2, on Google's own exports rather than the LibreOffice proxy. "Expanded" is met: the 29 expansion fixtures are measured through `parity_expansion.py` against `expansion_parity_policy.json`, which annotates and never adjudicates. Ratified is not fixed: every finding stays floored in both directions and clearing one entirely still fails as a stale record. |
| **(b)** | Two clean full-corpus Google Docs passes | **MET** | Pass 4 of 2026-08-04 assessed clean against the ratified policy (schema v3, one bounded waiver: `01_whitepaper_market` `mean_ssim` floored at 0.65 against a measured 0.6589), and a second fresh consented run followed. The caveat that belonged on this row still belongs in the record: the first pass became clean partly *because* a waiver was ratified after it was measured, and that waiver retires itself by mechanism — a `stale-waiver` blocks once `01` clears 0.70 unaided. |
| **(c)** | No-PyMuPDF / base-wheel proof | **MET** | `docs/evidence/base-wheel-proof-2026-08-06.json`. The gap this row used to describe — "cannot exist while PyMuPDF is core" — is closed: a wheel built from the flipped tree, installed into a virtualenv that never had PyMuPDF, 8 packages with no third-party copyleft term, 25/25 modules importing, 16/16 gated fixtures converting to valid DOCX, and the test suite green. See §8 for what it does and does not prove. |
| **(d)** | Dependency, provenance and licence audit | **FIRST PASS — this document** | §§1–6 complete and unrevised. Open items in §10 remain open, including the two that were never closable by engineering. **Still not reviewed by anyone qualified to sign it off**, and the switch landed on the repository owner's standing authorization rather than on legal review. |

### What the switch did *not* settle

Three things, stated here because a green gate table is exactly where they would
otherwise disappear:

1. **§10 item 1 (LIC-01, provenance of the source itself) is untouched.** This
   audit covers dependencies and corpus. It does not establish where the initial
   code came from or the right to relicense it, and the execution log calls that
   a hard blocker. Nothing in §§7–9 substitutes for it.
2. **No legal review has happened.** §10 item 2.
3. **The default install is measurably worse than a `[mupdf]` one** on three of
   the sixteen gated documents, because the quality ladder needs base-14 metrics
   only MuPDF supplies here. That is a product consequence of the licence work,
   quantified in the base-wheel proof, and it is release work rather than
   migration work — but it is the honest price of the change and is not filed as
   a footnote.

---

## 8. What a true no-PyMuPDF proof still needs

`tests/test_no_pymupdf.py` is the *isolation* proof, and
`docs/evidence/base-wheel-proof-2026-08-06.json` is the *installability* one.
They are different claims and the distinction is the whole of this section.

The test is real, not a gesture: it installs a `sys.meta_path` blocker that
makes `fitz` and `pymupdf` raise `ImportError` and evicts anything already
imported, which is *stricter* than a clean virtualenv in one specific way — it
also catches PyMuPDF arriving transitively through some other package in an
environment that never asked for it. It is *weaker* in the way that matters
most: it proves nothing about what `pip install` resolves.

**What the test proves today** (all passing, exit 0):

1. `fitz` and `pymupdf` are unimportable, under both spellings, before and after
   conversion.
2. **25 of 25 package modules import with PyMuPDF unimportable — the seam is
   EMPTY.** It was one module, `exactdoc/parse.py`, whose top-level `import
   fitz` was the entire declared seam; it is now `parse.require_fitz()`, called
   at parse time. Every PyMuPDF reference in the package is lazy, inside a
   function, on the PyMuPDF backend's own path.
3. Eight capability fixtures (text, tables, inline image, rasterised vector
   region, multi-page/refinement, multi-column, CJK+RTL, cover band/callouts)
   convert end to end through the **shipping** profile — not the Google-safe
   diagnostic one, which is what it used to exercise — and the *count* is
   asserted, so a loop over an empty list cannot report success.
4. Asking for `backend="pymupdf"` anyway raises `BackendUnavailableError` naming
   the extra, across four surfaces.
5. Refinement where LibreOffice is present, and the Google-Docs-safe static
   writer profile.
6. The shipping defaults are the permissive ones: `PRODUCT.backend` is `pdfium`
   and `get_backend(PRODUCT.backend).license` is `Apache-2.0`.

The seam check is a **subset** rule, deliberately: the seam may shrink without a
test edit (that is progress), but it cannot grow by one module without going
red and naming the module. A stray top-level `import fitz` is how a
PyMuPDF-free wheel breaks *while importing the writer*, before any conversion —
which has happened here before, in `docxout.py`.

**Four of the five items below are now closed. Each is left in place with its
resolution, because the list is more useful as a record of what had to be true
than as a list of things that happen to be done.**

1. **Installability — the actual base-wheel claim. CLOSED.** The test blocks an
   import inside an interpreter that still has PyMuPDF on disk; it never
   installs anything. That gap could not be closed while `pymupdf>=1.23` sat in
   `[project].dependencies`, and the test asserted that state explicitly so it
   would go red with instructions the moment PyMuPDF left core without a real
   proof replacing it. **It went red exactly as designed, and the proof
   replacing it is `docs/evidence/base-wheel-proof-2026-08-06.json`.**
2. **The real proof, concretely. CLOSED, and done more strictly than specified.**
   The wheel was built in a throwaway venv (so no build tooling entered the
   pinned environment), installed into a fresh virtualenv with **no extras at
   all** rather than `[pdfium]`, `find_spec("fitz")` is `None` there, and all 16
   gated fixtures convert end to end at the shipping RAW profile. The check the
   original item asked for — comparing against a pinned candidate baseline — was
   replaced by something better: a controlled comparison of the same commit
   installed two ways, which isolates the extra rather than confounding it with
   parser differences.
3. **The built artifact's own metadata. CLOSED.** `Requires-Dist` was read out
   of the built wheel and says `pypdfium2>=4.25` core,
   `pymupdf>=1.23; extra == "mupdf"`. The build backend did not mistranslate the
   declaration. The objection that stopped this being written as a test —
   installing `build`/`setuptools`/`wheel` into a shared environment to satisfy
   it — was answered by building in a disposable venv instead. Note what is
   still true: `tests/test_packaging_metadata.py` asserts the *declaration*, and
   the wheel-level check lives in the evidence file rather than in CI. Making it
   a test still needs build tooling somewhere CI can reach.
4. **Runtime failure mode. CLOSED.** All five `PyMuPDFBackend` operations now go
   through `parse.require_fitz()` and raise `BackendUnavailableError` naming the
   `mupdf` extra. Asserted in the clean environment for `parse_pdf`,
   `form_widgets`, `render_page`, `page_lines` and `render_clip`, and in
   `tests/test_no_pymupdf.py` for those plus `convert(backend="pymupdf")`.
5. **Platform coverage. STILL OPEN.** The proof runs on Linux only; pypdfium2
   ships per-platform binaries, so a Windows or macOS wheel is unproven. This is
   the one item on this list the migration did not touch, and it belongs on the
   release checklist.

6. **Capability parity between the two installs. CLOSED 2026-08-06**, and it was
   not on this list when it should have been. The base-wheel proof established
   that a PyMuPDF-free install *works*; it also measured that it works *worse*,
   because the quality ladder's only text shaper was MuPDF's. An installability
   proof that stops at "it runs" is half a proof when an optional extra changes
   the output. `exactdoc/metrics.py` now ships the published AFM widths (§5.4),
   both installs produce identical DOCX content on all 16 gated fixtures, and
   the check that would catch a regression is a content hash rather than a
   promise: `docs/evidence/permissive-shaper-2026-08-06.json`.

---

## 9. Mechanical switch steps — done 2026-08-06

Listed so the change was a checklist rather than an archaeology exercise. **Every
item was mechanical; none of them was the decision.** The decision was the
repository owner's standing authorization to switch once the code satisfied
gates (a)–(d), exercised across commits `900f0ab` (dependency flip), `f457567`
(base-wheel proof), `017c1e1` (baseline re-record) and the LICENSE commit.

1. ✅ **`LICENSE`** — Apache-2.0, copyright line "Copyright 2026 Ebin Babu
   Thomas". **`NOTICE` deliberately not added**, and this item is where the
   audit corrects itself: §3 establishes that the attribution obligation for the
   PDFium binary belongs to whoever redistributes it, which is the pypdfium2
   wheel and its own bundled manifest — not exactdoc, which merely depends on
   it. A `NOTICE` reproducing attributions for binaries this repository does not
   ship would assert an obligation it does not have and invite a reader to
   believe the list is maintained. If exactdoc ever vendors a binary, this
   becomes required immediately.
2. ✅ **`pyproject.toml`** — licence and classifier switched; `pymupdf>=1.23`
   moved into a new `mupdf` extra and `pypdfium2` into core; default backend
   decided as `pdfium`. `uv.lock` edited surgically rather than regenerated (the
   container's uv rewrites 1192 lines of unrelated metadata, and the lock is the
   pinned truth for parser versions that goldens and parity evidence are
   recorded against).
3. ✅ **Per-file headers — none exist, and none were added.** Verified again: no
   `SPDX-License-Identifier` and no copyright header in any file under
   `exactdoc/`. If headers are ever introduced, use
   `SPDX-License-Identifier: Apache-2.0`.
4. ✅ **Licence strings in code** — `exactdoc/backend.py` module docstring and
   both backend classes; `exactdoc/metrics.py`; `exactdoc/parse_pdfium.py`.
   `PyMuPDFBackend.license` **stays `"AGPL-3.0"`**: it is a true statement about
   PyMuPDF, not about exactdoc, and the seam knowing which side it is on is the
   point.
5. ✅ **`testkit/gen_expansion.py`** and `testkit/corpus_expansion.json`'s 16
   generated entries relabelled to `Apache-2.0`; the 13 acquired documents keep
   their publishers' bases untouched. `expansion_parity_policy.json`'s corpus
   pin was re-pinned in the same commit, and its "re-pinning means re-checking
   every entry" rule was **discharged by proof rather than re-measurement**: the
   manifest diff is exactly 16 `provenance/license` leaves, and every
   per-document `sha256` and `bytes` field is identical, so no floor can describe
   different bytes than it did.
6. ⬜ **`testkit/corpus_manifest.json`** — still open. Adding the provenance the
   gated 16 lack (§5.1) requires the re-pinned `gdocs_quality_policy.json` and
   `parity_policy.json` in the same commit, and that coupling makes it a
   deliberate change rather than a mechanical one. Carried to §10 item 4.
7. ✅ **`docker/gate.Dockerfile`** — the
   `org.opencontainers.image.licenses` label.
8. ✅ **Prose** — `README.md`, `ROADMAP.md`, `STATUS.md`, and the
   `testkit/backend_probe.py` / `testkit/exp_regroup.py` docstrings.
9. ✅ **`tests/test_no_pymupdf.py`** — the "PyMuPDF is still core" check is now
   its inverse, plus the typed-error assertions, and the file points at the real
   base-wheel proof for the claim it cannot make itself.

---

## 10. Open items

**The relicence landed with these open. That is a deliberate statement, not an
oversight**: items 1 and 2 were never engineering gates, and the switch rests on
the repository owner's standing authorization rather than on their resolution.

| # | Item | Owner |
|---|---|---|
| 1 | **LIC-01 provenance ledger** — where the *initial code* came from and the right to relicense it. This audit covers dependencies and corpus; it does **not** establish the provenance of the source itself, which the execution log lists as blocker B2 and calls a hard blocker. Nothing here substitutes for it, and the Apache-2.0 switch does not close it. | owner |
| 2 | Legal review of §§1–6, particularly the five publisher-identity fixtures (§5.2) and font embedding in generated fixtures (§6). | owner / counsel |
| 3 | ~~Remove or record `tmp/pdfs/` (§5.3)~~ — **done**: removed from tracking and disk, `tmp/` ignored, recorded in the execution log. | *closed* |
| 4 | Record provenance for the gated 16 (§5.1), as a single re-pinning commit carrying `corpus_manifest.json`, `gdocs_quality_policy.json` and `parity_policy.json` together. §9 item 6. **The expansion corpus got its relabel; the gated 16 still have no provenance field at all.** | engineering |
| 5 | Confirm installed metadata matches each project's published licence (§0). | legal review |
| 6 | ~~Add build tooling to the pinned environment so the wheel-level `Requires-Dist` check can be written~~ — **partly closed**: the check was *performed* against a wheel built in a disposable venv, so the pinned environment was never modified (see §8 item 3). What remains is making it a CI test rather than an evidence file. | engineering |
| 7 | ~~Re-run `uv sync` in the development virtualenv~~ — **closed by the migration, and for an uncomfortable reason.** The stale metadata inverted core and extra; the source then moved to match it. `tests/test_packaging_metadata.py` now reports agreement. The rule it taught survives its own resolution: read the declaration, never the `.dist-info`. | *closed* |
| 8 | **Platform coverage** (§8 item 5) — the base-wheel proof is Linux-only and pypdfium2 ships per-platform binaries. Release checklist. | engineering |

---

*Audit performed 2026-08-04 against the pinned environment (fingerprint
`3ca438f1…`) at branch `claude/exactdoc-pdf-docx-6d7759`; §§7–10 updated
2026-08-06 when the switch landed, against the same fingerprint. Dependency
versions move; re-run §§1–4 before relying on them.*
