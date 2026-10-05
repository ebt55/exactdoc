# Measurement scripts used by the improvement programme

These are the exact scripts the 2026-10-04/05 programme used to measure every
change. They are developer tools, not part of the package, and they assume a
Windows host with Git Bash, Docker, and the canonical image `exactdoc-gate:boot`
(see `docs/deep-dive/` and the canonical-environment notes). Outputs go to
`$EXACTDOC_SCR` (default `./.scratch`, git-ignored): `runs/<name>.log`,
`runs/<name>.sweep.json`, kept DOCX under `runs/<name>.docx/`.

| Script | What it does |
|---|---|
| `gate_full.sh <name> <tree> [steps]` | The CI-equivalent gate in a fresh canonical container: manifest, unit suite, script suites, golden IR, `runall` in both lanes. Exit code = failed steps. Grep the log for `Ran N tests` / `OK` as well as `FAILED_STEPS=0`. |
| `sweep.sh <name> <tree> [quality_sweep args]` | `testkit/quality_sweep.py` in a fresh canonical container, e.g. `--corpus both --jobs 6 --profile raw`. `KEEP_DOCX=1` keeps the DOCX (needed by the Word lane and the font census). |
| `rerecord.sh <name> <tree>` | Owner-approved baseline re-record only: `GATE_BASELINE=update` runall, then a plain runall that must PASS; copies the new `gate_baseline.json` out. Never run it without the owner's approval. |
| `gdsweep.py OUT [--corpus both] [--only a,b]` | Live Google Docs sweep: convert with the gdocs candidate profile, upload, Google's own PDF export, score. Resumable. Needs `EXACTDOC_ROOT=<tree>` and the `EXACTDOC_GDOCS_CREDENTIALS` / `EXACTDOC_GDOCS_TOKEN` env vars; uploads to the owner's Drive. |
| `flypairs.py PROBE OUT A B` | Fly a probe set's `<doc>.<A>.gdocs.docx` / `<doc>.<B>.gdocs.docx` pairs live and score them (a missing variant is skipped). |

The Word lane is in the package's testkit: `python testkit/word_oracle.py sweep
OUT --docx-dir <runs>/<name>.docx/raw --lane raw`. The beta scorecard is
`python testkit/beta_readiness.py --raw ... --product ... --gdocs ... --word ...
--gate <runs>/<name>.batch --accepted ... --docx-dir ...` (see its docstring).
Since 2026-10-06 its LibreOffice lane is the product sweep (beta-bar.md,
amendment 1). Renders saved before the harness's 2026-10-06 reading change are
re-read, without converting, by `python testkit/rescore.py sweep|rows|gate ...`
(it keeps the old values and a recomputed control beside the new ones).

Set `TEMP`/`TMP` to a short path such as `C:\lotmp\<name>` before anything that
starts LibreOffice on Windows: long profile paths crash soffice with a popup.
