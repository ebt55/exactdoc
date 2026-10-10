# exactdoc documentation

Start with the [main README](../README.md): what exactdoc does, how to install
it, and what works today. This folder holds the details, for when you want them.

## Using exactdoc

| File | What it is for |
|---|---|
| [usage.md](usage.md) | Every option, the Python API, batch mode, input errors and exit codes, and what happens when LibreOffice is missing or fails |
| [releasing.md](releasing.md) | How a version reaches PyPI: the one-time Trusted Publishing setup, the version bump and tag, the TestPyPI check, and what to do when a step fails |
| [beta-bar.md](beta-bar.md) | The bar the first beta must meet, ratified by the owner on 2026-10-05 and amended on 2026-10-06: 13 criteria, which gate, their thresholds and data, and why |

## Deep dive

The design, the measurements and the history. Code comments cite some of these
as "THEORY §n" or "STATUS §n".

| File | What it is for |
|---|---|
| [deep-dive/limitations.md](deep-dive/limitations.md) | Every known limitation in tiers, with numbers, and the queue of what is not done |
| [deep-dive/measured-state.md](deep-dive/measured-state.md) | The support matrix by the program that made the PDF, quality examples, the measured state at 1.0.0, the Google Docs profile's live measurements, cross-platform determinism, and the commands that reproduce the checks |
| [deep-dive/how-it-works.md](deep-dive/how-it-works.md) | How the converter works and how it got here: measurement first, a frozen corpus, a pinned environment, the parser swap, refusals by design |
| [deep-dive/theory.md](deep-dive/theory.md) | The design laws the codebase is built around ("THEORY"): the fidelity model, what worked, what did not, and the dead ends |
| [deep-dive/status.md](deep-dive/status.md) | The defect register and the measured state, defect by defect ("STATUS") |
| [deep-dive/roadmap.md](deep-dive/roadmap.md) | The plan that took the project to its 1.0.0 record: Google Docs qualification, the PDFium migration, release gates. Historical; it predates the 0.2.0a1 renumbering |
| [deep-dive/licensing.md](deep-dive/licensing.md) | Why the licence is Apache-2.0, what the optional AGPL extra changes (nothing in the output), and the proofs |
| [deep-dive/escalation-ruling-linebox.md](deep-dive/escalation-ruling-linebox.md) | A planning ruling on the line-box convention (the M2.d escalation), kept because theory.md and status.md refer to it |
| [deep-dive/support-by-engine.svg](deep-dive/support-by-engine.svg) | The support matrix as a diagram: rows are the program that made the PDF, columns are where you open the DOCX |

## Corpus, licences and evidence

| File | What it is for |
|---|---|
| [corpus-expansion.md](corpus-expansion.md) | How the test corpus grows (16 gated documents, 79 more measured) without invalidating a number |
| [corpus-download-candidates.md](corpus-download-candidates.md) | The proposal list for corpus tranche 2, kept as a record |
| [license-audit.md](license-audit.md) | Every dependency licence read from installed metadata, the components inside PDFium, and the redistribution basis of every corpus PDF |
| [dy-ascent-artifact.md](dy-ascent-artifact.md) | Decision record: why small `dy_p50` differences between the two parsers are a measurement convention, not a placement error |
| [release-notes-1.0.1.md](release-notes-1.0.1.md) | The 1.0.1 release announcement |
| [evidence/](evidence/) | The evidence system. Every quality claim is a committed record of the numbers, the environment and the commit that produced them |
| [images/](images/) | The README's example images, built by [`scripts/readme_images.py`](../scripts/readme_images.py) from the run in [evidence/readme-examples-2026-10-04.json](evidence/readme-examples-2026-10-04.json) |

The example documents in the images are this project's own test documents
(Apache-2.0) and public documents from the expansion corpus. Each one's source and
licence is recorded in [`testkit/corpus_expansion.json`](../testkit/corpus_expansion.json):
a US Census Bureau presentation and a Social Security Administration sample
statement (US government works, public domain), and arXiv:2309.06427 (CC BY 4.0).
