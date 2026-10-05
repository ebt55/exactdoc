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
| `record_env.sh <name> <tree> [file]` | `evidence.py --record-canonical` in a fresh container, written to `testkit/<file>` (default `canonical_env.proposed.json`, which nothing compares against). Writing `canonical_env.json` redefines canonical: owner approval only. |
| `gdsweep.py OUT [--corpus both] [--only a,b]` | Live Google Docs sweep: convert with the gdocs candidate profile, upload, Google's own PDF export, score. Resumable. Needs `EXACTDOC_ROOT=<tree>` and the `EXACTDOC_GDOCS_CREDENTIALS` / `EXACTDOC_GDOCS_TOKEN` env vars; uploads to the owner's Drive. |
| `flypairs.py PROBE OUT A B` | Fly a probe set's `<doc>.<A>.gdocs.docx` / `<doc>.<B>.gdocs.docx` pairs live and score them (a missing variant is skipped). |

The Word lane is in the package's testkit: `python testkit/word_oracle.py sweep
OUT --docx-dir <runs>/<name>.docx/raw --lane raw`. The beta scorecard is
`python testkit/beta_readiness.py --raw ... --product ... --gdocs ... --word ...
--gate <runs>/<name>.batch --accepted ... --docx-dir ...` (see its docstring).

Set `TEMP`/`TMP` to a short path such as `C:\lotmp\<name>` before anything that
starts LibreOffice on Windows: long profile paths crash soffice with a popup.

## Candidate images and switching the canonical image (WP31, Carlito/Caladea)

Every script above takes the image from `EXACTDOC_GATE_IMAGE` (default
`exactdoc-gate:boot`), so a candidate renderer can be measured while other
runs keep using the canonical one. Each log records the image name and ID.

The Carlito/Caladea candidate is a layer on the existing snapshot, so its delta
is the two font families and nothing else (a full rebuild would also move
LibreOffice and Python to the current apt snapshot):

    docker build -f docker/gate-carlito.Dockerfile \
        --build-arg BASE=exactdoc-gate:boot -t exactdoc-gate:boot-carlito docker
    EXACTDOC_GATE_IMAGE=exactdoc-gate:boot-carlito bash scripts/dev/gate_full.sh <name> <tree>
    EXACTDOC_GATE_IMAGE=exactdoc-gate:boot-carlito KEEP_DOCX=1 \
        bash scripts/dev/sweep.sh <name> <tree> --corpus both --jobs 6 --profile raw

`testkit/canonical_env.proposed.json` is that image's environment record,
written by `scripts/dev/record_env.sh` (`evidence.py --record-canonical
--record-to`); nothing compares against it until it is moved into place. The measured before/after is
`docs/evidence/carlito-2026-10-06.json`.

Switching is a baseline migration and needs the owner's approval at step 3.
Do it when no other run is using `exactdoc-gate:boot`:

1. Merge the WP31 commit that changes `scripts/fonts.conf` (and the Dockerfiles,
   bootstrap and `tests/test_crosextra_pins.py`). Before this step the old image
   is canonical; after it, its fonts.conf digest no longer matches the record,
   although it renders identically (the crosextra directory does not exist there).
2. Retag, keeping the old snapshot for reference:
   `docker tag exactdoc-gate:boot exactdoc-gate:boot-pre-carlito` then
   `docker tag exactdoc-gate:boot-carlito exactdoc-gate:boot`.
3. Record the canonical environment inside it (replaces `canonical_env.json`):
   `bash scripts/dev/record_env.sh <name> <tree> canonical_env.json`.
   Its fingerprint must equal the one in `canonical_env.proposed.json`; if it
   does, delete the proposed file. If it does not, something besides the fonts
   moved: stop.
4. Re-record the gate baseline: `bash scripts/dev/rerecord.sh <name> <tree>`
   and commit the copied `gate_baseline.json` (recording is refused until step 3
   makes the image canonical).
5. Remeasure the parity floors, which carry the environment fingerprint
   (`testkit/parity_policy.json`, `product_parity_policy.json`):
   `backend_parity.py --profile candidate --update-policy` and the same with
   `--profile product`; otherwise they report `environment-mismatch` rather
   than a regression. The hand-ratified `expansion_parity_policy.json` entries
   record the fingerprint too: remeasure with `parity_expansion.py` and have
   the owner re-ratify any entry whose floors move.
6. Update the two docstrings in `exactdoc/fonts.py` (module "What the canonical
   renderer has", and `writer_family`) that say Calibri and Cambria render as
   FreeSerif; comment-only, output unchanged.
7. For CI, publish a full rebuild with `gate-image.yml` (it carries the same
   pinned fonts) and pin its digest; that is a new environment and repeats 3-5.
