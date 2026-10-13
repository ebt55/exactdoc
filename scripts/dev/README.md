# Measurement scripts used by the improvement programme

These are the exact scripts the 2026-10-04/05 programme used to measure every
change. They are developer tools, not part of the package, and they assume a
Windows host with Git Bash, Docker, and the canonical image `exactdoc-gate:boot`
(see `docs/deep-dive/` and the canonical-environment notes). Outputs go to
`$EXACTDOC_SCR` (default `./.scratch`, git-ignored): `runs/<name>.log`,
`runs/<name>.sweep.json`, kept DOCX under `runs/<name>.docx/`.

| Script | What it does |
|---|---|
| `ci_image.sh [--no-chrome] [--from IMG] [--tag TAG]` | Makes the publishable CI image from the canonical snapshot without changing the environment: one container, `/work` emptied but for the venv, `docker export \| docker import` with the snapshot's config. Default `exactdoc-gate:boot` -> `exactdoc-gate:ci`. `--no-chrome` also drops Chrome for Testing (only the non-gating generator check uses it). Pushing is separate. |
| `quality_check.sh [--base REF] [--corpus gated\|both] [--jobs N] [--repeat REF]` | **The contributor's check** (CONTRIBUTING.md), and the one script here that needs no maintainer setup: BASE and HEAD measured one after the other in ONE container (corpus identity, strict `runall`, and with `both` the product sweep on the expansion corpus), then `testkit/quality_check.py compare`: per-document better/same/worse with gate.py's tolerances (criterion 8's rule, `beta_readiness.compare_rows`), the gated 16 per lane, DOCX byte identity, and LIFTS / NEUTRAL / REGRESSES / UNMEASURED (exit 0/3/1/2). `--repeat REF` is the determinism proof (DETERMINISTIC 0 / NONDETERMINISTIC 4). Image: `$EXACTDOC_GATE_IMAGE`, else `exactdoc-gate:boot`, else `exactdoc-gate:local-boot` (`--build` makes it from `docker/gate.Dockerfile`); an unprovisioned image is bootstrapped in the container. Output: `$EXACTDOC_SCR/qc/<base>-<head>-<corpus>/report.json`. |
| `gate_full.sh <name> <tree> [steps]` | The CI-equivalent gate in a fresh canonical container: manifest, unit suite, script suites, golden IR, `runall` in both lanes. Exit code = failed steps. Grep the log for `Ran N tests` / `OK` as well as `FAILED_STEPS=0`. |
| `sweep.sh <name> <tree> [quality_sweep args]` | `testkit/quality_sweep.py` in a fresh canonical container, e.g. `--corpus both --jobs 6 --profile raw`. `KEEP_DOCX=1` keeps the DOCX (needed by the Word lane and the font census). |
| `rerecord.sh <name> <tree>` | Owner-approved baseline re-record only: `GATE_BASELINE=update` runall, then a plain runall that must PASS; copies the new `gate_baseline.json` out. Never run it without the owner's approval. |
| `record_env.sh <name> <tree> [file]` | `evidence.py --record-canonical` in a fresh container, written to `testkit/<file>` (default `canonical_env.proposed.json`, which nothing compares against). Writing `canonical_env.json` redefines canonical: owner approval only. |
| `gdsweep.py OUT [--corpus both] [--only a,b]` | Live Google Docs sweep: convert with the gdocs candidate profile, upload, Google's own PDF export, score. Resumable. Needs `EXACTDOC_ROOT=<tree>` and the `EXACTDOC_GDOCS_CREDENTIALS` / `EXACTDOC_GDOCS_TOKEN` env vars; uploads to the owner's Drive. |
| `final_set.sh [--dry-run] [--only "a b"] --accepted SWEEP <tree> <name>` | The final measurement set for the beta scorecard in one resumable command: preflight, strict gate, product + raw sweeps, Word on both, the Docs command printed, quiet serial timing, `beta_readiness` into `docs/evidence/beta-readiness-<date>.json`. See [below](#the-final-measurement-set-wp44-final_setsh). Helpers: `final_set_helpers.py`. |
| `holdout_exam.sh [--exam holdout3] [--expect-promised N] [--dry-run] [--print] [--rerun-reason T] <tree> <name>` | A single-use release exam on a sealed holdout set (beta-bar.md, amendment 6): holdout-3 for 0.3.0b2 by default, holdout-2 (0.3.0b1, run 2026-10-11) for history. Verify the manifest and PDFs, product + raw sweeps over them, the CLI's exit status for every refusal, Word over the product DOCX, R1-R5 into `docs/evidence/<exam>-<date>.json`. See [below](#the-holdout-release-exam-wp52-wp63-holdout_examsh). Parts: `holdout_exam.py` (the `EXAMS` table), `holdout_sweep.py`, `holdout_word.py`, `holdout_dryset.py`. |
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

## The final measurement set (WP44): `final_set.sh`

One resumable command for the scorecard's inputs, all from one commit:

    EXACTDOC_SCR='C:\lotmp\scr' bash scripts/dev/final_set.sh \
        --accepted 'C:\lotmp\scr\runs\<accepted product>.sweep.json' <tree> <name>

In order: **(a)** refuse a dirty tree (untracked files count), a tree that is
not a git checkout, a run directory started on another commit, or any running
container that is not this run's (they are listed); **(b)** `gate_full.sh`,
strict (`EXACTDOC_GATE_ALLOW_STALE_BASELINE` is unset for it; a failed gate
stops the run unless `--keep-going`); **(c)** product and raw sweeps, both
corpora, `KEEP_DOCX=1`, the two containers in parallel at `--jobs 4`, then a
scan for error and unmeasured rows; **(d)** `word_oracle.py sweep` on the
product and on the raw DOCX (the oracle takes its own Word lock); **(e)** the
exact live Docs command -- uploads are the coordinator's, so it is printed,
not run (`gdsweep.py` flies the drift sentinel first; `docs_sentinel.py check`
reads it); **(f)** serial timing for criterion 2: the documents whose sweep
time is at least `--frac` (0.4) of their limit (`final_set_helpers.py pick`),
each timed alone in one container after the machine has been quiet -- no other
container and host CPU < 20% for 60 s -- with the host CPU and the container
count before and after it written beside its row (`load`); **(g)**
`beta_readiness.py` with every input, `--release 0.3.0b1` and `--all`, wrapped
by `final_set_helpers.py wrap` into `<tree>/docs/evidence/beta-readiness-<date>.json`
(the scorecard's JSON and text, each input by path and SHA-256, the accepted
sweep by path and SHA-256, the commit). (g) waits for a complete Docs lane
(`--docs-rows`, default `<runs>/<name>.gdocs/rows.jsonl`): run (e), then the
same command again.

Re-running the command skips finished steps (markers in
`<runs>/<name>.final/`, which also holds `final_set.log`, every command as it
ran); a finished sweep is kept, an interrupted one re-runs, Word resumes from
its rows, timing from the documents already timed. This run's own containers
left by an interruption are removed at (a).

Until the owner-approved baseline re-record, the strict gate fails on the
baseline binding (recorded under 3ca438f1 / no reading) and (b) says so
("re-record needed"); `--keep-going` carries on to the measurements.

`--dry-run` prints every command, copy-pasteable, and runs none (the preflight
findings are reported, not enforced). `--only "a b c"` restricts sweeps, Word
and timing to a subset (the gate always runs the gated 16); `--steps b,c,d`
runs a selection. `--allow-busy` and `--no-docs` exist for testing the script
and are written into the evidence as "not a final measurement".

## The holdout release exam (WP52, WP63): `holdout_exam.sh`

    EXACTDOC_SCR='C:\lotmp\scr' bash scripts/dev/holdout_exam.sh \
        --exam holdout3 --expect-promised 35 <tree> <name>

Run once per sealed set, on the frozen release candidate, after `final_set.sh`.
Which set is `--exam` (default `holdout3`, the exam for 0.3.0b2; `holdout2`
decided 0.3.0b1 on 2026-10-11). Each exam is one row of `EXAMS` in
`holdout_exam.py`: the release, the sealed manifest's SHA-256 and document
count (holdout-3's are read from its registration,
`docs/evidence/holdout3-registration-2026-10-12.json`), the set directory
(`C:\lotmp\rv_hold3`), the manifest name (found by its SHA-256 if the name
differs), the promise field (`promised_narrowed`), the
ledger (`$SCR/holdout3-exam.ledger.jsonl`), the state suffix
(`$SCR/runs/<name>.holdout3/`) and the evidence prefix (`holdout3-<date>.json`).
`holdout_exam.py resolve --exam holdout3` prints the row without opening the
set. One exam's finished run never blocks another's: each has its own ledger,
and only `<prefix><date>[-rerunN].json` counts as a result.

In order: **(a)** refuse a tree that is not a clean git checkout, any container
that is not this exam's, and a second exam of this set: a result already in
`<tree>/docs/evidence/`, or this exam's ledger recording a finished exam or one
started under another name or commit. Resuming the same name on the same commit
is not a second exam. `--rerun-reason TEXT` overrides the refusal and is
written into the ledger, the log and the evidence. Then the manifest's SHA-256
and document count, its promise field (and `--expect-promised N`, which refuses
before anything is converted unless N documents are promised) and every PDF's
SHA-256 are verified, and the start is recorded; **(b)** product and raw sweeps
over the PDFs, two containers in parallel (`holdout_sweep.py`: quality_sweep's
own code with `select()` swapped, as holdout-1 ran), DOCX kept; the product
container then runs each refused document through the real CLI and records its
exit status; **(c)** the Word lane over the product DOCX (`holdout_word.py`:
word_oracle's own sweep and lock, `select()` swapped); **(d)** `holdout_exam.py
verdict`: R1-R5 exactly as amendment 6 states them (the reading of each is in
its docstring and printed with the verdict), PASS/FAIL per criterion,
"announce: yes/no", and a per-document table; R2's and R3's denominators are
the exam's own promised documents; **(e)** `holdout_exam.py wrap` into
`<tree>/docs/evidence/<prefix><date>.json` (never overwritten): the verdict,
every input and exam script by path and SHA-256, the tree's commit as the host
read it (passed into the containers as `EXACTDOC_GIT_COMMIT`), the image id.
The sealed directory is only read.

`--dry-run` runs the same steps on a 2-PDF synthetic set (`holdout_dryset.py`,
reportlab, byte-reproducible, named like the exam's manifest) with its own
manifest, state, ledger and evidence under `C:\lotmp\<exam>-dry`
(`EXACTDOC_DRY_DIR`); every verdict read from it carries a SYNTHETIC banner.
`--print` prints every command and runs none, and does not open the set.
`--steps b,c,d,e` runs a selection; `--docs-rows` adds a live Docs lane to R5.
The host Python is `$EXACTDOC_PY`, else a `.venv` in the tree or in the main
checkout the worktree belongs to, else `python3` (as `final_set.sh`).

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

`testkit/canonical_env.proposed.json` was that image's environment record,
written by `scripts/dev/record_env.sh` (`evidence.py --record-canonical
--record-to`); nothing compares against a proposed record until it is moved into place. The measured before/after is
`docs/evidence/carlito-2026-10-06.json`.

**Switched 2026-10-10 (WP32, owner decision).** Steps 1-3 and 6 below are
done: `exactdoc-gate:boot` is now the Carlito image (bab1cfc0d2cd), the old
snapshot is kept as `exactdoc-gate:boot-pre-carlito` (390a910873d6), and
`testkit/canonical_env.json` was recorded in it with fingerprint 9cb0bc17,
byte-identical to the proposed record, which was then deleted. Step 4 is
done too: the baseline was re-recorded in this image on 2026-10-11 (88a2831,
owner-delegated dual review), so it is bound to 9cb0bc17 and reading wp42.
Step 5 was run as a dry run only. A gate is valid only on a tree that contains
the switch commit.

**Step 7, done differently (WP55, 2026-10-11, owner-delegated decision).** CI
does not run a rebuild. `exactdoc-gate:boot` (image id bab1cfc0d2cd) is
flattened by `ci_image.sh --no-chrome` into `exactdoc-gate:ci-nochrome`
(b46332899ad3): the same filesystem without the working tree its `docker
commit` layer carried (which included local agent settings that must not be
published), the root user's pip/uv caches and Chrome for Testing, pushed to
`ghcr.io/ebt55/exactdoc-gate`; `gate.yml` pins it by manifest digest and runs
the strict gate inside it (pushed as `snapshot-2026-10-11`, digest
`sha256:b4633289…`; contents and source availability:
[docs/gate-image.md](../../docs/gate-image.md)). Measured in it (and in boot) as CI runs it, on
96ede05: fingerprint 9cb0bc17, canonical, every step green, the full unit
suite included. A streamed scan of its whole filesystem found no `.claude`,
settings, credential, key, token or history file and no private document
name. So nothing in steps 3-5 repeats. A rebuild from `gate-image.yml` would
resolve today's apt and is still a new environment.

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
7. For CI, push the new canonical image and pin its digest in `gate.yml` and
   `quality_check.sh` (how WP55 did it: the snapshot flattened by
   `ci_image.sh --no-chrome`, so the environment is unchanged). A full
   rebuild with `gate-image.yml` (it carries the same pinned fonts) is a new
   environment and repeats 3-5.
