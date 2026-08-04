# Download candidates for corpus tranche 2

**Nothing in this list has been downloaded.** It is a proposal requiring explicit
approval before a single byte is fetched. No URL here has been contacted, so
every producer string, page count and file size below is an **expectation from
prior knowledge, not a measurement** — the columns are marked accordingly, and
all three are recorded for real at acquisition time.

Why downloads at all, when tranche 1 generated 16 documents perfectly well: all
32 fixtures the corpus would then hold were produced by scripts in this
repository, and therefore inherit this repository's assumptions about margins,
fonts, structure and what a "table" is. A producer we have never seen is the
only honest test of a general rule. `docs/corpus-expansion.md` §3 sizes this
tranche at roughly 16 documents to reach the 40–60 target, weighted to the two
classes that cannot be generated here at all: LaTeX and real-world strangers.

---

## Acquisition protocol (binding, if this list is approved)

1. **Approval is per document, not per list.** Approving the list approves
   nothing; the operator names which IDs to fetch.
2. **Licence is verified at fetch time, from the document or its landing page** —
   never from this table. A document whose licence cannot be established is
   discarded, not filed as `unknown`. `corpus_manifest.verify_expansion()`
   rejects `unknown` as a licence for exactly this reason.
3. **arXiv is the sharpest trap here.** The default arXiv submission licence is a
   non-exclusive licence to arXiv to distribute — it does **not** grant onward
   redistribution. Only papers whose abstract page states CC-BY, CC-BY-SA or
   CC0 may be committed. This must be checked per paper; it cannot be assumed
   from the archive.
4. Fetch politely: honour `robots.txt`, one request at a time, a real
   `User-Agent`, no bulk crawling. Several hosts below (govinfo, NTRS) rate-limit.
5. Record actual bytes, SHA-256, page count, producer string (`pdfinfo` or
   PyMuPDF `metadata["producer"]`) and the retrieval date into the provenance
   block, with `origin: "downloaded"` and the resolved `source_url`.
6. **Freeze on arrival.** The bytes are committed as fetched and never
   re-downloaded — a URL is not a stable identity, and a document silently
   revised upstream is the same failure as a regenerated fixture.
7. Tier per `docs/corpus-expansion.md` §4, assigned after inspecting the
   document, not from this table's guess.
8. Non-gating on arrival, without exception. Promotion is §7 of the design doc.

---

## A. LaTeX-light — the class that cannot be generated here

The canonical image has no TeX distribution and adding one is a ~2 GB change to
the environment of record. These are the only route to pdfTeX/XeTeX/LuaTeX
output, which is a large share of technical PDFs in the wild and currently 0/16
of the corpus.

| ID | Source | Producer (expected) | Licence (verify) | Size (est.) | Tier (est.) |
|---|---|---|---|---|---|
| D01 | arXiv paper, CC-BY, single-column maths — search `arxiv.org` filtered to CC-BY | pdfTeX | CC-BY 4.0 | 0.5–2 MB, 10–20 pp | ordinary_digital |
| D02 | arXiv paper, CC-BY, two-column (IEEE/ACM style) | pdfTeX | CC-BY 4.0 | 0.5–2 MB, 8–14 pp | ordinary_digital |
| D03 | arXiv paper, CC-BY, XeLaTeX with non-Latin author names | XeTeX | CC-BY 4.0 | 0.5–2 MB | designed_stress |
| D04 | arXiv paper, CC-BY, heavy tabular/booktabs results | pdfTeX | CC-BY 4.0 | ~1 MB | ordinary_digital |
| D05 | PLOS ONE article — `journals.plos.org/plosone` | Acrobat Distiller / PDFlib | CC-BY 4.0 | 1–3 MB, 15–25 pp | ordinary_digital |
| D06 | eLife article — `elifesciences.org` | LuaTeX / Acrobat | CC-BY 4.0 | 1–3 MB | ordinary_digital |
| D07 | JMLR paper — `jmlr.org/papers` | pdfTeX | CC-BY (per paper) | 0.3–1 MB | ordinary_digital |
| D08 | LIPIcs / Dagstuhl proceedings — `drops.dagstuhl.de` | pdfTeX | CC-BY 4.0 | 0.3–1 MB | ordinary_digital |

## B. United States Government works — public domain by 17 U.S.C. §105

The cleanest licence position available, and a genuinely diverse producer set:
these agencies use Word, Acrobat Distiller, XPP and in-house report generators.

| ID | Source | Producer (expected) | Licence | Size (est.) | Tier (est.) |
|---|---|---|---|---|---|
| D09 | NIST Special Publication 800-series — `csrc.nist.gov/publications` | MS Word → Acrobat | Public domain (US Gov) | 1–4 MB, 40–80 pp | ordinary_digital |
| D10 | GAO report — `gao.gov/reports-testimonies` | MS Word → Acrobat Distiller | Public domain | 1–3 MB, 30–60 pp | ordinary_digital |
| D11 | Congressional Research Service report — `crsreports.congress.gov` | MS Word → Acrobat | Public domain | 0.5–2 MB, 10–40 pp | ordinary_digital |
| D12 | NASA Technical Reports Server item — `ntrs.nasa.gov` | varies incl. LaTeX, Word | Public domain | 1–10 MB | ordinary_digital |
| D13 | USGS publication — `pubs.usgs.gov` | Adobe InDesign | Public domain | 2–10 MB | designed_stress |
| D14 | CDC MMWR weekly report — `cdc.gov/mmwr` | Adobe InDesign / Distiller | Public domain | 0.5–2 MB | ordinary_digital |
| D15 | IRS instructions, e.g. Form 1040 — `irs.gov/forms-instructions` | in-house composition engine | Public domain | 1–3 MB, 100+ pp | designed_stress |
| D16 | Federal Register issue — `govinfo.gov` | XPP / Ghostscript | Public domain | 1–5 MB, dense 3-col | designed_stress |
| D17 | Congressional bill text — `govinfo.gov/app/collection/bills` | XPP | Public domain | 0.1–1 MB | ordinary_digital |
| D18 | NTSB accident report — `ntsb.gov` | MS Word → Acrobat | Public domain | 2–8 MB | ordinary_digital |

## C. Standards bodies

| ID | Source | Producer (expected) | Licence (verify) | Size (est.) | Tier (est.) |
|---|---|---|---|---|---|
| D19 | RFC in PDF form — `rfc-editor.org/rfc/rfcNNNN.pdf` | in-house `xml2rfc` toolchain | IETF Trust Legal Provisions — redistribution of unmodified copies permitted | 0.2–1 MB | ordinary_digital |
| D20 | Older RFC, fixed-pitch ASCII-art layout | xml2rfc / enscript | IETF TLP | 0.1–0.5 MB | designed_stress |
| D21 | W3C Recommendation, PDF rendition where published — `w3.org/TR` | Prince / WeasyPrint | W3C Document Licence — unmodified redistribution permitted | 0.5–3 MB | ordinary_digital |
| D22 | ETSI openly-published specification — `etsi.org/standards` | MS Word → Acrobat | ETSI terms — **verify redistribution before use** | 1–5 MB | ordinary_digital |
| D23 | Unicode Technical Report — `unicode.org/reports` | varies | Unicode Licence | 0.3–2 MB | designed_stress |

## D. Openly licensed reports, books and institutional publications

The word-processor and desktop-publishing dialects, from producers with no
connection to this project.

| ID | Source | Producer (expected) | Licence (verify) | Size (est.) | Tier (est.) |
|---|---|---|---|---|---|
| D24 | OpenStax textbook chapter — `openstax.org` | Adobe InDesign / PDF Library | CC-BY 4.0 | 5–30 MB full, extract a chapter | designed_stress |
| D25 | World Bank Open Knowledge Repository report — `openknowledge.worldbank.org` | InDesign / Distiller | CC-BY 3.0 IGO | 2–10 MB | ordinary_digital |
| D26 | European Union publication — `op.europa.eu` | MS Word / InDesign | CC-BY 4.0 (2019 reuse decision) | 1–5 MB | ordinary_digital |
| D27 | UK Government publication — `gov.uk/government/publications` | MS Word → Acrobat | Open Government Licence v3 | 0.5–3 MB | ordinary_digital |
| D28 | Government of Canada publication — `canada.ca` | MS Word / LibreOffice | Open Government Licence — Canada | 0.5–3 MB | ordinary_digital |
| D29 | UNESCO open-access publication — `unesdoc.unesco.org` | InDesign | CC-BY-SA 3.0 IGO | 2–8 MB | ordinary_digital |
| D30 | OECD open-access report — `oecd-ilibrary.org` (CC-BY items only) | InDesign / Distiller | CC-BY 4.0 (per item) | 2–8 MB | ordinary_digital |
| D31 | Creative Commons annual report — `creativecommons.org` | InDesign / Canva export | CC-BY 4.0 | 2–8 MB | designed_stress |
| D32 | Wikimedia "Download as PDF" article export — `wikipedia.org` | in-house renderer (Chromium-based) | CC-BY-SA 4.0 | 0.3–2 MB | ordinary_digital |
| D33 | Linux Foundation / Apache Software Foundation annual report | InDesign / Canva | CC-BY 4.0 | 3–10 MB | designed_stress |
| D34 | Our World in Data downloadable report — `ourworldindata.org` | Chromium print / Prince | CC-BY 4.0 | 1–5 MB | ordinary_digital |

## E. Deliberate tier-boundary candidates

The `unsupported` tier currently holds zero documents, which means the refusal
path has never been tested against a real example of what it refuses. These
exist to populate it, and are expected to be **rejected before qualification** —
a document that is refused is a passing test of the refusal, not a failure.

| ID | Source | Producer (expected) | Licence | Size (est.) | Tier (est.) |
|---|---|---|---|---|---|
| D35 | Scanned public-domain book page images — `archive.org` (pre-1929 US works) | scanner + Acrobat, image-only | Public domain | 5–50 MB | **unsupported** (no text layer) |
| D36 | Scanned document with an OCR text layer — `archive.org` | ABBYY FineReader / Tesseract | Public domain | 5–30 MB | designed_stress (OCR text layer, misaligned) |
| D37 | US Government fillable AcroForm, e.g. an IRS or USCIS form | in-house / Adobe LiveCycle | Public domain | 0.3–2 MB | **unsupported** (form logic) |
| D38 | Very long public-domain report, > 200 pages — `govinfo.gov` | XPP | Public domain | 10–40 MB | **unsupported** (exceeds limits) |

---

## Coverage this list would deliver

Against `docs/corpus-expansion.md` §3, taking ~16 of the 38 candidates:

| producer class | target | after tranche 1 | candidates available here |
|---|---|---|---|
| word-processor export | 12 | 7 | D09, D10, D11, D18, D22, D26, D27, D28 |
| browser print-to-PDF | 12 | 14 | D32, D34 (met; these are surplus) |
| report generator | 10 | 11 | D15, D16, D17, D38 (met) |
| LaTeX-light | 8 | 0 | D01–D08 — **the whole gap** |
| other / unknown real-world | 6 | 0 | D13, D14, D19, D20, D24, D25, D29–D31, D33 |

The two thin classes are LaTeX (0 of 8) and real-world strangers (0 of 6), and
between them they account for the ~16 documents this tranche needs. The browser
and report-generator classes are already met after tranche 1, so candidates
D32/D34 and D15–D17 are optional surplus and should be fetched last if at all.

New producer strings this would introduce, none of which the corpus has ever
seen: pdfTeX, XeTeX, LuaTeX, Acrobat Distiller, Adobe PDF Library, Adobe
InDesign, Ghostscript, XPP, Prince, WeasyPrint, ABBYY FineReader, and whatever
the agencies in section B are actually running — which is itself worth measuring,
since the expected column above is a guess until someone looks.
