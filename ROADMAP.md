# exactdoc roadmap

This is a quality-first roadmap. Shipping remains the measured PyMuPDF product;
the PDFium/Google-Docs profile is a migration candidate, not a quiet default
change.

## Current position

Shipping profile:

```text
pymupdf/standard/libreoffice/refine3@240dpi
```

Canonical product quality is 16/16 page match, 0.5161 mean within-2pt, 0.9652
mean live text, and 0.675pt median dy50. The PyMuPDF/standard open-loop `raw`
control is 14/16, 0.3349, 0.9652, and 2.79pt respectively. Measured 2026-08-04,
canonical fingerprint `3ca438f1…`, both lanes PASS
(`docs/evidence/canonical-gate-2026-08-04.json`).

Product page match reached 16/16 on one document: the striped-table assembler
took `c3_tables` from one page out to exact (word recall 0.331→0.9359).
Separately, the two-column right-edge fix took `c2_paper2col` median dy
29.2→0.85pt and within-2pt 0.1948→0.4857 — placement, not pagination. The raw
lane moved 13/16→14/16, with `c1_whitepaper` and `c5_graphics` its two remaining
mismatches; its median dy50 2.2→2.79pt is the c3 word population reordering the
median (raw c3 word recall 0.3137→0.8648, dy50 2.5→7.45pt), not a placement
regression.

The gate baseline was deliberately re-recorded in that run (`29945f2`) because
the committed `c3_tables` records had gone stale and the gate refuses a record
that no longer describes reality. Attribution was verified first: with the new
inference rules disabled the `c3` output is byte-identical, so the movement is
the assembler's.

These are regression records, not an absolute release-quality declaration.
Complex/nested table layouts and D10 rasterised-text regions in `c5_graphics`
and `04_exec_brief` remain known shipping limitations.

## First: qualify Google Docs honestly

The user-facing `exactdoc-gdocs` package exists (install `.[gdocs]`; for
example, `exactdoc-gdocs auth`), including authentication, cleanup attempts,
orphan-ledger blocking, and safe evidence output. The testkit qualification
protocol is intentionally separate from the user CLI:

```bash
python testkit/gdocs_oracle.py prepare <dir>
python testkit/gdocs_oracle.py run <dir> --allow-cloud-upload
```

`prepare` is offline and hash-binds the exact candidate; `run` requires explicit
upload consent. It reports operational and quality pass independently.

Four consented full-corpus passes ran on 2026-08-04 for
`pdfium/gdocs/none/refine0@240dpi`. All four completed the operational gate — 16
attempted, 16 succeeded, zero failed, no `.gdocs_orphans.json` — and blocking
quality findings fell 11 → 4 → 3 → **1** across the day. Pass 2 took the
boundary-compensation retirement; pass 3 cleared `l1_word_native` dy
15.19→1.93pt; pass 4 cleared `l1` dx 39.82→1.35pt on the Docs-measured Libre
Baskerville substitution and `c2_paper2col` SSIM 0.6772→0.7087 on a 1.0pt scoped
section-break compensation. Twelve of the thirteen blocking fixtures now clear
every threshold unaided.

The quality policy is implemented and **ratified** (schema v3). It has a
blocking `ordinary_digital` tier, a tracked/nonblocking `designed_stress` tier,
a pre-qualification refusal contract for `unsupported` inputs, and collected
evidence can be reassessed offline without a new Google upload. Ratification is
explicit and fail-closed, and v3 adds bounded per-metric waivers that are
ratified-only.

Assessed against pass 4, the ratified policy returns `overall_pass: true` with
zero blocking findings, carrying **one bounded waiver**: `01_whitepaper_market`
`mean_ssim`, floored at 0.65 against a measured 0.6589, cause probe-measured as
the Docs importer's unconditional addition above a page-leading cover band. The
waiver covers one metric on one document, blocks again below its floor, and
becomes a blocking `stale-waiver` the moment `01` clears 0.70 unaided — so it
retires by mechanism rather than by memory. Two residual fixable causes are
filed: a missing 4pt accent bar and a ~2pt band-to-body gap.

**Migration gate (b) is MET**: passes 4 and 5 both assess clean under the
ratified policy, which is the two consecutive clean full-corpus passes the gate
asks for. One gate of four is not a release.

The **parity** policy is ratified as well (2026-08-04, DEC-D2, decided on the
Google evidence rather than this LibreOffice proxy). Its two D10 findings —
`c4_i18n` and `c5_graphics` — moved to `ratified_shortfalls` with an owner, a
date, an issue and a review condition each; both remain floored in both
directions and stale-checked, so ratified means "cannot block a swap by itself",
not "fixed". A `dy_p50` absolute-magnitude exemption landed with it, resolving
task #22: below 2.0pt on both arms the metric is reporting a base-14 ascent
convention rather than placement, so it is exempt — but only while `within2pt`
holds, which keeps `02_research_paper` and `03_tech_report_code` blocked on a
real placement regression the dy framing had been masking. Details in
[docs/dy-ascent-artifact.md](docs/dy-ascent-artifact.md).

The long-document pagination campaign is **closed and exonerated**. Seven
mechanisms landed — `y01` 158→92 pages against an 80-page source, `y02` 314→142,
`y09` 116→64, `y13` +32, `y12` +55 on a one-line wrap margin — plus U+0002
hyphen recovery (`y12`/`y13` recall past 0.996) and a `candidate_profile_id`
mislabel fix. Ablation cleared it of the candidate-arm regressions that looked
like its fallout: reverting `parse_pdfium.py` alone restores the −04b counts
(109/68/72), reverting the campaign's `infer`/`docxout` changes moves nothing,
and disabling its margin guard makes `y01` worse (114→162). The culprits are
three recent PDFium parse commits, each of which fixed a real defect, so the
work is parse-side refinement rather than revert.

Still blocked, all in flight unless noted: **#31** pdfium line-count inflation
from the parse fixes (`y01`/`y09`/`y03`/`y02`), now merged with **#34**
(`y17`/`x10`/`x07` segmentation) and `y13`'s gutter-crossing rate into one
**pdfium line-segmentation convergence campaign** owned by the pagination agent;
**#33** `y06` writer-path OOM; **#28** `x03` markers; **#27** `y03`/`y10` recall.

The `c2_paper2col` target is addressed. Its right column ends near 551pt while
margin inference trusted an inset abstract ending near 509pt, narrowing content
by about 42pt and shifting column two left by about 21pt; the fix (`ff518be`)
derives the edge from verified two-column geometry rather than from the inset,
as a general layout rule and not a fixture exception. Against the LibreOffice
proxy the product lane moves `c2` median dy 29.2→0.85pt and within-2pt
0.1948→0.4857, and raw `c2` median dy 26.8→4.0pt. **That is proxy evidence and
does not clear the live blocker**, which still stands against the committed
2026-08-04 Google evidence until a fresh consented run replaces it.

The same commit's `GDOCS_PARA_BOUNDARY_COMP_PT = 3.0` is what took the live pass
from seven findings to eleven, and it is now retired (`41e8e7f`). Remeasured
against Google's own exported PDFs over 187 single-column boundaries in 12
documents, Docs contributes about +0.10pt at a paragraph boundary, not 3pt:
compensated boundaries rendered gaps 2.90pt *smaller* than the source, so the
subtraction was lost space accumulating down every page. The earlier reading
came from probes using `lineRule="exact"`, which this profile already
retranslates, so it double-counted. A column-aware counterfactual predicts
eleven of thirteen ordinary documents inside the 10pt bound, `c1_whitepaper`
marginal and `l1_word_native` separately caused — **a prediction, not a
measurement**, and it needs a consented live pass to confirm.

Next: confirm that retirement live, then code indentation and whitepaper visual
similarity, likewise as general rules. Afterward expand to roughly 40–60 frozen
real/generated PDFs from common producers, review/ratify the policy, and perform
the second consented full Google pass. The current 16 fixtures are regression
evidence, not market coverage.

The long ordinary striped table in `c3_tables` is now one editable 46-row ×
4-column table with IDs 1–45 exactly once; it naturally spans pages and has no
invented repeating header. Its conservative detector rejects ambiguous
multiline/cards/callouts and coalesces only page-edge segments with matching
geometry. It also consolidates `c1_whitepaper`'s 5-row comparison table.
Only c1/c3 `document.xml` changed in the structural corpus diff; the other 14
candidates are byte-identical by OOXML part. The candidate is now live-Google
qualified operationally: c3 is 3→3 with all 45 rows in an editable continuous
table, though row distribution differs from source. Its word recall improved
0.3120→0.8215, SSIM 0.5785→0.7573, and IoU 0.0973→0.1448; live 0.9226 and
document recall 0.9359 were unchanged. dy50/dy90 rose 2.94→7.85pt and
80.52→103.34pt because many more words now match. `c1_whitepaper` remains 2→2
with unchanged content/layout metrics and only tiny visual tradeoffs
(within-2pt 0.0719→0.0688, SSIM 0.8006→0.7993, IoU 0.1568→0.1563).
`c5_graphics` remains a deliberately deferred gradient/rounded/rotated
designed-page limitation.

## Second: prove or reject the PDFium migration

The non-shipping candidate is:

```text
PDFIUM_GDOCS_CANDIDATE = pdfium/gdocs/none/refine0@240dpi
```

On 2026-08-04 the candidate arm measures 15/16 page match, 0.0694 mean
within-2pt, 0.9566 live text, and 13.78pt median dy50 against the LibreOffice
proxy. Those absolutes say little alone — a Google-Docs output profile graded by
a renderer that is not Google — so read them against the reference arm at the
same profile: 14/16, 0.0712, 0.9652, and 13.27pt. Both rows predate `c1cbc2a`,
which improved `c2_paper2col` on four dimensions; no canonical parity run has
been recorded since, so they are not restated from a partially updated set. The
`candidate-refined` diagnostic was not remeasured and its earlier figures are
not carried forward.

Same-profile parity is 7 regressions, 6 same, and 3 better as raw measurement
(`--measure` uses empty margins, so every movement shows; the 2026-08-04
evidence recorded 8/6/2 and `c1cbc2a` retired one). The composition moved more
than the count: `c7_code` is now identical on every dimension after the
Google-Docs cell-margin fix, `c1_whitepaper` is now better (page error 1→0, word
recall 0.8273→0.9697), and plain memo placement is no longer a regression.
`c2_paper2col` entered because the *incumbent* improved — PyMuPDF took more of
the right-column-edge fix than PDFium did — and then left when `c1cbc2a`
absorbed a superscript into its host line in the parser, taking dy 23.55→10.00
against a 10.05 reference and within-2pt 0.0131→0.1247 against 0.1039.
Adjudicated against the profile-bound policy that leaves no unwaived regressions
and two tracked provisional findings: `c4_i18n` complex scripts and
`c5_graphics` designed-page rasterisation. Provisional is not accepted, nothing
in the **parity** policy is ratified, and the candidate is not adopted and not
releasable. (The **Google Docs quality** policy is a separate file and a
separate decision; it was ratified on 2026-08-04 and that says nothing about
these two parity findings.)

`testkit/parity_policy.json` is now bound to the full profile ID rather than to
`recorded_refine_rounds: 3`. That rebinding is not a migration: floors measured
at one full profile say nothing about another, and the four D2 core-14 findings
the old file carried were measured elsewhere. They are not retired — their own
profile has simply not been remeasured.

The bounded bottom-margin relief is useful evidence, not a declaration of
victory: it fixed candidate `c1_whitepaper` and `c2_paper2col` overflow, and the
candidate now matches page count on 15 of 16 fixtures, one better than the
reference arm. Complex/nested tables and `c5_graphics` designed graphics remain
explicit limitations; `c5_graphics` is a page out under both backends.

The next migration decision requires all of:

1. expanded same-profile parity with no unratified regressions — **MET**
   (2026-08-05, bound to `parity-expanded-2026-08-05f.json`). All four
   adjudication paths clean: gated/candidate 0 regressions 4 ratified,
   gated/shipping 0 regressions 4 ratified, expansion/candidate 11 MAJOR all
   ratified, expansion/shipping 7 MAJOR all ratified. Zero unratified findings,
   zero stale entries, zero floor breaches, across three profile-bound
   artifacts;
2. two clean full-corpus Google Docs passes for the exact candidate, each after
   explicit upload consent — **MET**: passes 4 and 5;
3. a no-PyMuPDF/base-wheel proof — **the remaining gate, and it is the flip
   itself**: the isolation proof holds and the seam is one module
   (`exactdoc/parse.py`), but a PyMuPDF-free *install* is impossible while
   PyMuPDF is a core dependency, so this closes when the dependency moves;
4. a dependency, provenance, and license audit — **first pass done**,
   [docs/license-audit.md](docs/license-audit.md).

Gates (a), (b) and (d) are met. (c) is the flip.

The live status table lives in the audit; this list is the contract.

Do not replace the shipping profile, regenerate golden/numeric evidence, or
change licensing before those gates pass.

## Third: release only after quality gates

Conversion/refinement publication is transactional: candidates remain private
until structural validation succeeds, then replace the public destination
atomically. Batch conversion now has deterministic serial discovery, caps, safe
machine-readable results, and explicit scan/OCR-required rejection. This is
not a remaining release blocker, but is deliberately not a cloud batch feature.

URI navigation is done on the candidate: PDFium now reads the producer's
`/Link` annotations instead of scanning text for URL-shaped substrings, which
was wrong in both directions — `c8_toc_links` found 1 of its 3 real links, and
an expansion fixture invented 17 from URL-shaped prose. Both backends now agree
on link count, URI and rectangle across all 32 documents, and no metric moved.
Internal TOC navigation is **not** done and is not merely a parser gap: `c8`'s
three GoTo destinations resolve fine, but the IR carries a link as a single URI
string and the writer emits only external relationships, so it needs an IR
field, a writer capability, and a rule for which paragraph a destination anchors
to — the last of which is inference and is left as a decision rather than
guessed at. Heading/list semantics follow. RTL follows only
after a logical-Unicode-ordering contract. Heavy LaTeX, highly designed/vector
pages, complex/nested tables, and a full OCR engine remain future work. Scan/OCR
PDFs are explicitly unsupported rather than silently mishandled.

## Licensing — migrated 2026-08-06

**exactdoc is Apache-2.0.** PyMuPDF left the core/default path into an optional
`mupdf` extra, PDFium via pypdfium2 became the core parser and the shipping
backend, and all four migration gates were met before the switch rather than
after it. This roadmap is project strategy, not legal advice.

The audit it rests on is [docs/license-audit.md](docs/license-audit.md). It
reads every licence from installed metadata rather than memory, and its result
was narrow — **PyMuPDF was the only code-licence blocker in the entire
dependency graph.** Of 35 resolved packages only four carried any copyleft term:
exactdoc itself, PyMuPDF (then core, the blocker), fpdf2 (LGPL, `test` extra
only, imported nowhere under `exactdoc/`), and certifi (MPL-2.0, transitive,
unmodified). PDFium's 16 bundled components are all permissive, AGG included —
it vendors 2.3, which predates AGG's move to GPL.

**What the switch did not settle, and what it cost:**

- **LIC-01, the provenance of the initial source itself, remains the hard
  blocker.** The audit covers dependencies and corpus; it does not establish
  where the code came from or the right to relicense it, and Apache-2.0 in
  `LICENSE` does not change that. Neither has legal review happened.
- The default install is measurably **worse** than one with `[mupdf]` on three
  of the sixteen gated documents, because the quality ladder needs base-14 text
  metrics only MuPDF supplies here. Quantified in
  [docs/evidence/base-wheel-proof-2026-08-06.json](docs/evidence/base-wheel-proof-2026-08-06.json).
  A permissive text shaper in `exactdoc/metrics.py` is what closes it, and it is
  release work.
- The gate baseline moved with the parser and is slightly worse in aggregate.
  Every movement was predicted by the ratified parity record and checked against
  it before recording:
  [docs/evidence/parser-default-flip-2026-08-06.json](docs/evidence/parser-default-flip-2026-08-06.json).

## Reproducible checks

```bash
bash scripts/bootstrap.sh --strict
python testkit/corpus_manifest.py verify
python testkit/runall.py
python tests/test_gate_mutations.py
```

Use `testkit/runall.py --absolute` for release qualification. The ordinary gate
only establishes regression status against its canonical record.
