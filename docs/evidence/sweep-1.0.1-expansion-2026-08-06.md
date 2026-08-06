# 1.0.1 confirmation sweep — expansion corpus, before and after

The measurement behind the 1.0.1 CHANGELOG entry. Two runs of
`testkit/parity_expansion.py` over the 31-document expansion corpus at the
shipping product profile, taken either side of the résumé fix batch.

Non-gating, like everything measured over this corpus: no baseline describes it,
`testkit/gate.py` never sees it, and the runs' own trailer says so.

| artifact | sha256 | bytes |
|---|---|---|
| `sweep-1.0.1-expansion-before-2026-08-06.json` | `feea999c93847c824bbec1c8b2fb6fc470e176f2beff2c99c8101a097b984429` | 139011 |
| `sweep-1.0.1-expansion-after-2026-08-06.json` | `20dc397508100ebd6401386dde5837ca7d8f58f8c167356de497f831fbd86ca1` | 139016 |
| `sweep-1.0.1-expansion-before-2026-08-06.log` | *(see note)* | 6079 |
| `sweep-1.0.1-expansion-after-2026-08-06.log` | *(see note)* | 6079 |

The two JSONs carry digests because `.gitattributes` pins `*.json` to LF, so
their bytes are the same in every checkout and a hash means something. The logs
carry none deliberately: they are console output, no rule pins their line
endings, and a checkout that normalises them would produce a digest that
disagrees with a recorded one for no reason worth chasing. Sizes above are as
committed from the Linux container. Hash the JSONs; read the logs.

Profile, from both run headers: `pdfium/standard/libreoffice/refine3@240dpi`.
28 of 31 documents measured; three refused as expected — `y07` and `y14` as
interactive forms, `y11` over the 250-page cap.

## What it shows

The résumé pair is the batch's target and moves as claimed:

| | `dy_p50` | `dy_p90` | `within2pt` | `mean_ssim` | `word_recall` |
|---|---|---|---|---|---|
| `x17_resume_twocol` | 3.13 → **0.38** | 25.43 → **8.92** | 0.0590 → **0.1022** | 0.8422 → **0.8733** | 0.9443 → 0.8719 |
| `x18_resume_twocol_tnr` | 3.67 → **0.48** | 25.43 → **8.92** | 0.0644 → **0.1400** | 0.8467 → **0.8767** | 0.9422 → 0.8671 |

`word_recall` falls on both, and that is a **reference artifact rather than a
text regression**: the harness reference was extracted with the same PDFium
fragmentation this batch fixes, so it holds no whole heading tokens to match
against. The converted document gained the headings; the yardstick never had
them.

Eight documents differ on at least one gated metric between the two runs —
`x11`, the résumé pair, `y01`, `y02`, `y09`, `y13`, `y17`. `x11` is the
IR-identical control that establishes the render-noise floor at 2.3%; the
adjudicated reading is that the non-résumé movement sits at or under it. Read
raw, without that floor applied, the count is eight rather than the six the
CHANGELOG describes, and the difference is entirely definitional — the two files
here are what to recount against.

Every other field that differs across the two runs is `convert_s` and
`docx_bytes`, which move on 28 of 28 measured documents and are timing and
archive-size rather than fidelity.

## What this does *not* authenticate

Stated because the rest of this directory sets a higher bar. These four files
carry **no build digest, no environment fingerprint, no profile binding block
and no commit stamp** — the JSONs are bare arrays of per-document results, and
the logs are console output. Two module-digest lines were expected to be present
in the logs and are not: neither `257496acf969580c` (after) nor
`bb2161e84f365b3d` (before) appears anywhere in the four files.

So these artifacts show *what was measured*; they do not by themselves prove
*which build measured it*. They are committed because the numbers they contain
reproduce the CHANGELOG's claim exactly and are better in the repository than
outside it, not because they meet the standard set by, say,
`parity-expanded-2026-08-05f.json`. A future sweep should carry the same
environment and binding blocks the parity artifacts do.
