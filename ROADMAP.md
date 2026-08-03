# exactdoc roadmap

This is a quality-first roadmap. Shipping remains the measured PyMuPDF product;
the PDFium/Google-Docs profile is a migration candidate, not a quiet default
change.

## Current position

Shipping profile:

```text
pymupdf/standard/libreoffice/refine3@240dpi
```

Canonical product quality is 15/16 page match, 0.4981 mean within-2pt, 0.9652
mean live text, and 0.675pt median dy50. The PyMuPDF/standard open-loop `raw`
control is 13/16, 0.3349, 0.9652, and 2.2pt respectively.

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

The latest live run on 2026-08-02 completed the operational gate for
`pdfium/gdocs/none/refine0@240dpi`: all 16 documents were attempted and
succeeded, zero failed, and cleanup left no `.gdocs_orphans.json`. Against the
prior live candidate, page-count match improved 14/16→15/16, mean within-2pt
0.1378→0.1443, mean word recall 0.8745→0.9064, SSIM 0.7767→0.7878, and IoU
0.2108→0.2138; mean live text stayed 0.9568. Median dy50 rose 4.98→6.68pt
because `c3_tables` now matches many more words and changes median ordering,
not because of a broad regression. Only deferred `c5_graphics` remains 1→2.

The strict quality-policy v2 design is now implemented. It has a blocking
`ordinary_digital` tier, a tracked/nonblocking `designed_stress` tier, and a
clear pre-qualification refusal contract for `unsupported` inputs. Policy
ratification is explicit and fail-closed, and collected evidence can be
reassessed offline without a new Google upload.

The committed policy remains a draft. Applied to the latest evidence, 9/13
ordinary fixtures meet every threshold; seven blocking findings remain across
four documents: `01_whitepaper_market` SSIM; `c2_paper2col` dx/dy/SSIM;
`c7_code` dx; and `l1_word_native` dx/dy. The Word-native tranche is now
implemented locally as a general symbol-font list-marker normalizer: l1 becomes
three editable list items, and only its `document.xml` changes across the full
prepared corpus. Local proxy metrics improve, but the live blocker remains until
fresh Google qualification.

The next engineering target is `c2_paper2col`. Its right column ends near
551pt, while margin inference trusts an inset abstract ending near 509pt; that
narrows content by about 42pt and shifts column two left by about 21pt, matching
the measured 20.09pt error. Correct this from verified two-column geometry, then
address code indentation and whitepaper visual similarity. Fix these as general
layout rules, not fixture exceptions. Afterward expand to roughly 40–60 frozen
real/generated PDFs from common producers, review/ratify the policy, and perform
the second consented full Google pass. The current 16 fixtures are regression evidence,
not market coverage.

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

After bottom-margin relief it has 14/16 page match, 0.2429 mean within-2pt,
0.9568 live text, and 2.425pt median dy50. Its candidate-refined diagnostic has
15/16, 0.3381, 0.9568, and 2.06pt. Same-profile parity is 7 regressions, 7 same,
and 2 better, including major regressions in plain memo placement, complex
scripts, and graphics. It is not adopted and not releasable.

The bounded bottom-margin relief is useful evidence, not a declaration of
victory: it fixed candidate `c1_whitepaper` and `c2_paper2col` overflow while
preserving the other 12 page-matching fixtures. Complex/nested tables and
`c5_graphics` designed graphics remain explicit limitations.

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

The next feature tranche preserves proven PDF URI and internal-TOC navigation
(`c8` has three URI and three GoTo annotations; the current PDFium path sees
only a mailto heuristic), then adds heading/list semantics. RTL follows only
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
