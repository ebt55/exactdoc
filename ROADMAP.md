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

The latest live run is 2026-08-04 and completed the operational gate for
`pdfium/gdocs/none/refine0@240dpi`: all 16 documents were attempted and
succeeded, zero failed, and cleanup left no `.gdocs_orphans.json`. On fidelity
it is worse than the 2026-08-02 run it replaces. Page match holds at 15/16 (only
deferred `c5_graphics` 1→2) and live text is flat 0.9568→0.9566, but mean
within-2pt fell 0.1443→0.0483, SSIM 0.7878→0.7635, IoU 0.2138→0.1560, word
recall 0.9064→0.9056, and median dy50 rose 6.68→12.31pt with every document
drifting upward. The cause has been attributed to a 3pt per-boundary spacing
compensation and retired; see below.

The strict quality-policy v2 design is now implemented. It has a blocking
`ordinary_digital` tier, a tracked/nonblocking `designed_stress` tier, and a
clear pre-qualification refusal contract for `unsupported` inputs. Policy
ratification is explicit and fail-closed, and collected evidence can be
reassessed offline without a new Google upload.

The committed policy remains a draft. Applied to the 2026-08-04 evidence, 5/13
ordinary fixtures meet every threshold, down from 9/13; eleven blocking findings
remain across eight documents — `dy_p50` on `03_tech_report_code`,
`c1_whitepaper`, `c2_paper2col`, `c6_long`, `c8_toc_links`, `l1_word_native` and
`r1_reportlab_report`, SSIM on `01_whitepaper_market`, `c2_paper2col` and
`c6_long`, and `dx_p50` on `l1_word_native`. `c7_code` dx and `c2_paper2col` dx
cleared. The Word-native tranche is now
implemented locally as a general symbol-font list-marker normalizer: l1 becomes
three editable list items, and only its `document.xml` changes across the full
prepared corpus. Local proxy metrics improve, but the live blocker remains until
fresh Google qualification.

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
is ratified, and the candidate is not adopted and not releasable.

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

1. expanded same-profile parity with no unratified regressions;
2. two clean full-corpus Google Docs passes for the exact candidate, each after
   explicit upload consent;
3. a no-PyMuPDF/base-wheel proof; and
4. a dependency, provenance, and license audit.

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

## Licensing strategy

exactdoc remains AGPL-3.0-or-later today because PyMuPDF is core. Apache-2.0 is
the preferred future target, but PDFium being optional does not unblock it.
PyMuPDF must leave the core/default path; pypdfium2/PDFium and every bundled
dependency need provenance and license audit; and the migration gates above
must pass. This roadmap is project strategy, not legal advice.

## Reproducible checks

```bash
bash scripts/bootstrap.sh --strict
python testkit/corpus_manifest.py verify
python testkit/runall.py
python tests/test_gate_mutations.py
```

Use `testkit/runall.py --absolute` for release qualification. The ordinary gate
only establishes regression status against its canonical record.
