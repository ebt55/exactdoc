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
`c3_tables` nested tables and D10 rasterised-text regions in `c5_graphics` and
`04_exec_brief` remain known shipping limitations.

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

The final live run on 2026-08-02 completed the operational gate for
`pdfium/gdocs/none/refine0@240dpi`: all 16 documents were attempted and
succeeded, zero failed, and cleanup left no `.gdocs_orphans.json`. Targeted
fixes improved its Google-Docs result from 12/16 to 14/16 page match, 6.07pt to
4.98pt median dy50, 0.8356 to 0.8745 word recall, 0.7475 to 0.7767 SSIM, and
0.1814 to 0.2108 ink IoU. Mean within-2pt was essentially flat (0.1391 to
0.1378) and mean live text remained 0.9568. `01_whitepaper_market` and
`04_exec_brief` now retain their source page counts.

The quality gate is still unqualified and unacceptable for release:
`testkit/gdocs_quality_policy.json` is missing, which makes `quality_pass` and
`overall_pass` false. The next action is review of this evidence and a genuine
quality policy, not a permissive policy written to turn the candidate green.

Next ordinary-document priority is a general cross-page table assembler for
`c3_tables`, whose alternating-fill multi-page table is currently fragmented by
inference into 1x1/1x4 tables and paragraphs. `c5_graphics` depends on gradient
and rounded/rotated complex graphics and remains deferred as a designed-page
limitation. The parser now preserves stretched literal interword spaces, fixing
the `01_whitepaper_market` word staircase without changing shipping PyMuPDF.

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
preserving the other 12 page-matching fixtures. Candidate `c3_tables` nested
tables and `c5_graphics` designed graphics remain explicit limitations.

The next migration decision requires both:

1. same-profile parity that clears the agreed quality bar; and
2. reviewed real Google Docs quality evidence for the exact candidate.

Do not replace the shipping profile, regenerate golden/numeric evidence, or
change licensing before those gates pass.

## Third: release only after quality gates

Input handling is already hardened: encrypted PDFs produce unsupported-input
errors; malformed/truncated PDFs produce parse errors; failed conversions keep
an existing destination atomic. This is not a remaining release blocker.

The deferred engineering scope is deliberately narrow: ordinary digital text,
multi-column documents, common tables, and i18n come first. Heavy LaTeX,
highly designed/vector pages, and nested tables are future work. Scan/OCR PDFs
are unsupported rather than silently mishandled.

## Licensing strategy

exactdoc remains AGPL-3.0-or-later today because PyMuPDF is core. Apache-2.0 is
the preferred future target for its patent grant and business-friendly terms,
but PDFium being optional does not unblock that change. It requires the candidate
quality gates above and appropriate legal review. This roadmap is project
strategy, not legal advice.

## Reproducible checks

```bash
bash scripts/bootstrap.sh --strict
python testkit/corpus_manifest.py verify
python testkit/runall.py
python tests/test_gate_mutations.py
```

Use `testkit/runall.py --absolute` for release qualification. The ordinary gate
only establishes regression status against its canonical record.
