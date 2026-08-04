# exactdoc licence and provenance audit

**This is an engineering audit, not legal advice.** It records what the project
depends on, what it redistributes, and where each of those came from, so that a
qualified reviewer has facts to work from rather than recollections. Every
licence below was read from installed package metadata or from a licence file
shipped inside the package — not from memory, and not from a web search. Where
the basis for a claim is weaker than an explicit written grant, this document
says so rather than rounding up.

The relicensing question is narrow: exactdoc is AGPL-3.0-or-later **only**
because PyMuPDF is a core dependency. The target is Apache-2.0. This audit asks
one question of everything the project touches: *does this constrain that
change?*

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

**Generated (16).** `provenance.license` records `AGPL-3.0-or-later`, stamped
from `LICENSE` in `testkit/gen_expansion.py`. Sole authorship means these can be
relabelled at will, but the label is a mechanical switch step (§9) — an
AGPL-labelled corpus inside an Apache-2.0 repository is a contradiction a reader
will trip over long before a lawyer does.

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

ROADMAP names four gates. None is met; two have moved.

| # | Gate | Status | Evidence, and what is missing |
|---|---|---|---|
| **(a)** | Expanded same-profile parity with no unratified regressions | **PARTIAL** | **0 unwaived regressions.** 2 provisional findings remain — `c4_i18n` (D10, complex-script raster fallback) and `c5_graphics` (D10, designed-page rasterisation) — both bounded, attributed, and **unratified**, so `adjudicate()` cannot report a pass by construction. Ratification is an owner decision (DEC-D2). Separately, **"expanded" is not met**: parity runs over the gated 16 only; the 29 expansion fixtures are non-gating and parity cannot see them. |
| **(b)** | Two clean full-corpus Google Docs passes | **NOT MET — zero clean passes** | The 2026-08-04 run was **operationally** clean (16/16 attempted and succeeded, no orphaned Drive objects) and **failed quality**: 11 blocking findings across 8 of the 13 `ordinary_digital` fixtures. The draft policy is also unratified, so it cannot pass whatever the metrics say. A cause has been attributed (the 3pt boundary compensation) and retired, but that is a prediction until a consented pass confirms it. **Two consecutive clean passes means the counter is at zero, not at one.** |
| **(c)** | No-PyMuPDF / base-wheel proof | **PARTIAL** | See §8 — the isolation proof is real and now stronger; the *installability* proof does not exist and cannot exist while PyMuPDF is core. |
| **(d)** | Dependency, provenance and licence audit | **FIRST PASS — this document** | §§1–6 complete. Open items in §10. Not reviewed by anyone qualified to sign it off. |

---

## 8. What a true no-PyMuPDF proof still needs

`tests/test_no_pymupdf.py` is the current proof. It is a real test, not a
gesture: it installs a `sys.meta_path` blocker that makes `fitz` and `pymupdf`
raise `ImportError` and evicts anything already imported, which is *stricter*
than a clean virtualenv because it also catches a module some other import
already pulled in.

**What it proves today** (all passing, exit 0):

1. `fitz` and `pymupdf` are unimportable, under both spellings, before and after
   conversion.
2. **23 of the 24 package modules import with PyMuPDF unimportable.** The seam
   is exactly one module — `exactdoc/parse.py`, the shipping parser. Every other
   PyMuPDF reference in the package is lazy, inside a function, on the PyMuPDF
   backend's own path.
3. Eight capability fixtures (text, tables, inline image, rasterised vector
   region, multi-page/refinement, multi-column, CJK+RTL, cover band/callouts)
   convert end to end through `PDFIUM_GDOCS_CANDIDATE`, and the *count* is
   asserted, so a loop over an empty list cannot report success.
4. Refinement through the candidate where LibreOffice is present, and the
   Google-Docs-safe static writer profile.
5. Shipping defaults are unchanged by any of it.

The seam check is a **subset** rule, deliberately: the seam may shrink without a
test edit (that is progress), but it cannot grow by one module without going
red and naming the module. A stray top-level `import fitz` is how a
PyMuPDF-free wheel breaks *while importing the writer*, before any conversion —
which has happened here before, in `docxout.py`.

**What it still does not prove, in priority order:**

1. **Installability — the actual base-wheel claim.** The test blocks an import
   inside an interpreter that still has PyMuPDF on disk. It never installs
   anything. Today this gap **cannot** be closed, because `pymupdf>=1.23` sits in
   `[project].dependencies`, so `pip install exactdoc[pdfium]` necessarily
   installs AGPL PyMuPDF. The test now asserts that state explicitly and will go
   red with instructions if PyMuPDF leaves core without a real proof replacing
   it — so the gap is executable rather than a note in a document.
2. **The real proof, concretely.** Build the wheel; create a fresh virtualenv;
   `pip install dist/exactdoc-*.whl[pdfium]`; assert
   `importlib.util.find_spec("fitz") is None` *in that environment*; then
   convert all 16 gated fixtures and compare against the pinned candidate
   baseline. That needs PyMuPDF moved to an extra, a default path that does not
   route through `exactdoc/parse.py`, and CI running it in a clean container.
3. **The built artifact's own metadata — partially closed.**
   `tests/test_packaging_metadata.py` now turns §1 and §2 into executable
   comparisons: the declared core set and every extra must match the audited
   sets, no package may be declared in both core and an extra, PyMuPDF must
   still be core, and the project licence must still say AGPL while it is.
   Verified to bite — seven mutations of the declaration (a dependency added,
   one removed, PyMuPDF moved to an extra, an extra gaining a package, an extra
   renamed, a package declared twice, the licence flipped) are each caught.
   **What remains open is the wheel itself.** The strongest check reads
   `Requires-Dist` from a freshly built wheel, because that is the artifact a
   user installs and the only one whose metadata is guaranteed to have been
   generated from the current `pyproject.toml`. `build`, `setuptools` and
   `wheel` are all absent from the pinned virtualenv, and installing them into
   a shared environment to satisfy a test is not a change to make silently.
   What is asserted today therefore catches every edit to the declaration and
   would not catch a build backend that mistranslates it. Closing it needs
   build tooling in the environment.
4. **Runtime failure mode.** Even with the seam at zero modules,
   `backend.py`'s `PyMuPDFBackend` lazily imports `fitz` in its methods. A base
   wheel must make `backend="pymupdf"` fail with a clear typed error rather than
   an `ImportError` traceback from four frames down. Nothing tests that.
5. **Platform coverage.** The proof runs on Linux CI only; pypdfium2 ships
   per-platform binaries, so a Windows or macOS wheel is unproven.

---

## 9. Mechanical switch steps

For the day gates (a)–(d) pass. Listed so the change is a checklist rather than
an archaeology exercise. **Every item is mechanical; none of them is the
decision.**

1. **`LICENSE`** — replace the AGPL-3.0 text with Apache-2.0, and add a
   `NOTICE` file carrying the attribution set §3 describes.
2. **`pyproject.toml`** — `license = { text = "AGPL-3.0-or-later" }` →
   `Apache-2.0`; drop the classifier `"License :: OSI Approved :: GNU Affero
   General Public License v3 or later (AGPLv3+)"` and add `"License :: OSI
   Approved :: Apache Software License"`; move `pymupdf>=1.23` out of
   `dependencies` into its own extra; decide the default backend.
3. **Per-file headers — none exist.** Verified: there is no
   `SPDX-License-Identifier` and no copyright header in any file under
   `exactdoc/`. Nothing to rewrite. If headers are introduced, use
   `SPDX-License-Identifier: Apache-2.0`.
4. **Licence strings in code** (these are data and prose, not decoration):
   `exactdoc/backend.py` — the module docstring's AGPL statement and
   `PyMuPDFBackend.license`; `exactdoc/metrics.py` — two docstring passages on
   why MuPDF's tables are not copied; `exactdoc/parse_pdfium.py` — the docstring
   that names AGPL as the reason it exists.
5. **`testkit/gen_expansion.py`** — the `LICENSE = "AGPL-3.0-or-later"` constant
   that stamps generated fixture provenance, and then
   `testkit/corpus_expansion.json`'s 16 generated entries.
6. **`testkit/corpus_manifest.json`** — add the provenance the gated 16 lack
   (§5.1), together with re-pinned `gdocs_quality_policy.json` and
   `parity_policy.json`, in one commit.
7. **`docker/gate.Dockerfile`** — the
   `org.opencontainers.image.licenses="AGPL-3.0-or-later"` label.
8. **Prose** — `README.md` "Licensing", `ROADMAP.md` "Licensing strategy",
   `STATUS.md` "Licensing and release strategy", and
   `testkit/backend_probe.py` / `testkit/exp_regroup.py` docstrings.
9. **`tests/test_no_pymupdf.py`** — replace the "PyMuPDF is still core" check
   with the real base-wheel proof from §8.

---

## 10. Open items

| # | Item | Owner |
|---|---|---|
| 1 | **LIC-01 provenance ledger** — where the *initial code* came from and the right to relicense it. This audit covers dependencies and corpus; it does **not** establish the provenance of the source itself, which the execution log lists as blocker B2 and calls a hard blocker. Nothing here substitutes for it. | owner |
| 2 | Legal review of §§1–6, particularly the five publisher-identity fixtures (§5.2) and font embedding in generated fixtures (§6). | owner / counsel |
| 3 | ~~Remove or record `tmp/pdfs/` (§5.3)~~ — **done**: removed from tracking and disk, `tmp/` ignored, recorded in the execution log. | *closed* |
| 4 | Record provenance for the gated 16 (§5.1), as a single re-pinning commit. | engineering |
| 5 | Confirm installed metadata matches each project's published licence (§0). | legal review |
| 6 | Add build tooling to the pinned environment so the wheel-level `Requires-Dist` check in §8 item 3 can be written. | engineering |
| 7 | Re-run `uv sync` in the development virtualenv: its `exactdoc` metadata is stale and inverts the core/extra position of PyMuPDF (§0). Harmless to the tests, misleading to a human. | engineering |

---

*Audit performed 2026-08-04 against the pinned environment (fingerprint
`3ca438f1…`) at branch `claude/exactdoc-pdf-docx-6d7759`. Dependency versions
move; re-run §§1–4 before relying on them.*
