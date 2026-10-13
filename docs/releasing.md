# Releasing exactdoc

How a version gets from this repository to PyPI. Publishing is automated by
[`.github/workflows/release.yml`](../.github/workflows/release.yml), but it is
inert until the one-time setup below is done by hand, and it only ever runs
when a version tag is pushed. Nothing here uses an API token: PyPI's *Trusted
Publishing* gives the workflow a credential that lasts minutes, for one upload,
and only from this repository's release workflow.

The first public beta, **0.3.0b1**, was published on PyPI on 2026-10-12 and
**0.3.0b2** on 2026-10-13, both quietly; **0.3.0b3** is the first announced
release. The version in `pyproject.toml` changes only in the release commit
itself, and that commit is not made while any gating criterion of
[the beta bar](beta-bar.md) fails.

## What runs, in order

When a tag such as `v0.3.0b3` is pushed, `release.yml` runs four jobs:

| Job | What it does | Stops the release when |
|---|---|---|
| `build` | Points README's relative links at the tag (`scripts/pypi_readme.py`, so the PyPI page shows its pictures), builds the sdist and wheel once, runs `twine check --strict` and `scripts/check_dist.py` | the tag is not `v` + the version in `pyproject.toml`; the metadata does not render; the files contain anything but the package |
| `testpypi` | Uploads exactly those files to test.pypi.org | TestPyPI refuses them |
| `verify-testpypi` | On Linux and Windows: downloads the wheel back from TestPyPI, checks it is byte-identical to the build, installs it in a clean virtualenv (dependencies from PyPI), checks `exactdoc --version` and converts two test PDFs | any of those fails |
| `pypi` | Uploads the same files to pypi.org | it waits for your approval first (see setup step 4) |

The `install` workflow (`.github/workflows/install.yml`) runs the same build
and a wider install check on every push and pull request: Linux, Windows and
macOS, Python 3.9, 3.12, 3.13 and 3.14 (and 3.10 and 3.11 on Linux), the wheel in a clean virtualenv with no
LibreOffice, two conversions, and the unit tests. A release is tagged only on
a commit where `gate` (the strict two-lane gate inside the pinned canonical
image) and `install` are both green.

## One-time setup (by hand)

1. **Check the name is still free.** On 2026-10-05 both
   <https://pypi.org/project/exactdoc/> and
   <https://test.pypi.org/project/exactdoc/> returned "not found". If either
   now exists and is not yours, stop: the project needs another name.

2. **Accounts.** Create an account on [pypi.org](https://pypi.org/account/register/)
   and a separate one on [test.pypi.org](https://test.pypi.org/account/register/)
   (they do not share logins). Turn on two-factor authentication on both; PyPI
   requires it to publish.

3. **Add a "pending" trusted publisher on each.** Because the project does not
   exist yet, PyPI calls this a pending publisher; the first upload creates the
   project and binds it to this repository.
   - test.pypi.org → your account → **Publishing** → *Add a new pending
     publisher* → **GitHub**:
     - PyPI Project Name: `exactdoc`
     - Owner: `ebt55`
     - Repository name: `exactdoc`
     - Workflow name: `release.yml`
     - Environment name: `testpypi`
   - pypi.org → your account → **Publishing** → the same form, with
     Environment name: `pypi`.

   Every field must match exactly; a mismatch fails the upload with
   `invalid-publisher`, and nothing is published.

4. **Create the two GitHub environments.** In the repository on GitHub:
   **Settings → Environments → New environment**.
   - `testpypi`: under *Deployment branches and tags*, choose *Selected
     branches and tags* and add a tag rule `v*`.
   - `pypi`: the same tag rule, and tick **Required reviewers** with yourself
     as the reviewer. The final upload then waits in the Actions page until you
     press *Approve*, after the TestPyPI copy has been verified.

5. **Make sure the repository is public.** The PyPI page's pictures are
   served from `raw.githubusercontent.com` at the tag, and they only load for a
   public repository. (That the tagged commit is on `main` is a step of every
   release, step 3 below, not a one-time check.)

## Each release

The commands below use `0.3.0b3`; replace it with the version being released.

1. **Check readiness against [the beta bar](beta-bar.md)**, ratified by the
   owner on 2026-10-05. On the commit to release: the canonical gate is green
   in both lanes, the `install` workflow is green, and
   `python testkit/beta_readiness.py --runs <your runs folder>` reports no
   gating criterion as FAIL or UNMEASURED (criteria 1–6, 8, 10–12). **No
   version is tagged while any gating criterion fails.** Criteria 7, 9 and 13 are
   reported for the beta and gate 1.0.

2. **Bump the version, in one commit.**
   - `pyproject.toml`: `version = "0.3.0b3"`. The classifier is already
     `"Development Status :: 4 - Beta"` (since 0.3.0b1) and stays so until 1.0.
   - `uv.lock`: run `uv lock`, then `uv lock --check`. The lock records the
     project's own version; the gate's `uv sync --frozen` never compares it
     with `pyproject.toml`, which is how it said 1.0.0 for two months after
     the renumbering to 0.2.0a1. The diff should be that one line.
   - `README.md`: the places marked with a `<!-- release: ... -->` comment,
     and nothing else: the status callout names the new version.
     `docs/install.md` says which version `--pre` is for; check it too.
   - `CHANGELOG.md`: the heading line `## Unreleased` becomes exactly

     ```text
     ## 0.3.0b3 — 2026-MM-DD
     ```

     with the release date in ISO form and an em dash, the same shape as
     `## 0.3.0b1 — 2026-10-12`. Then add a new, empty `## Unreleased` above
     it. Step 9 copies this section into the GitHub release.
   - Check the build locally before pushing:

     ```bash
     uv build --out-dir dist
     uvx twine check --strict dist/*
     python scripts/check_dist.py dist
     ```

   - Push the commit and wait for `gate` and `install` to pass on it.

3. **Bring `main` up to the release commit through a pull request. Do not skip this.** `main` is
   what people see: the GitHub front page, the README that PyPI's *Homepage*
   link opens, and the targets of the *Documentation* and *Changelog* links
   (`pyproject.toml`) and of `exactdoc --help`'s usage link
   (`exactdoc/cli.py`, `USAGE_URL`), which all name `blob/main/...`. Until
   `main` carries the release, those links show an older project or 404 (on
   2026-10-11 `main` was 461 commits behind and had no `docs/usage.md`).

   Since 2026-10-13, `main` is protected by the GitHub ruleset "Protect main".
   It has no bypass, so it applies to everyone, including the owner and any
   tool using their login:
   - nobody can push to `main` directly, force-push it or delete it;
   - every change arrives as a pull request;
   - the pull request merges only when these checks pass on its latest
     commit: `gate`, `build sdist + wheel` and `install + smoke` (Ubuntu and
     Windows, Python 3.12).

   ```bash
   gh pr create --base main --head <release-branch> \
     --title "Release <version>" --body "Release commit <sha>; gate and install green."
   ```

   The owner merges it on GitHub with **Create a merge commit**. Then check
   that the release commit is in `main`'s history:

   ```bash
   git fetch origin
   git merge-base --is-ancestor <release-commit> origin/main && echo ok
   ```

4. **Tag and push the tag.** The tag must be `v` followed by exactly the
   version in `pyproject.toml`, or the `build` job stops:

   ```bash
   git tag -a v0.3.0b3 -m "exactdoc 0.3.0b3"
   git push origin v0.3.0b3
   ```

5. **Watch it run.** GitHub → **Actions → release**. `build`, `testpypi` and
   `verify-testpypi` run on their own (a few minutes; the verify job retries
   for up to five minutes while TestPyPI's index catches up).

6. **Optionally, try the TestPyPI copy yourself** in a fresh virtualenv. The
   wheel comes from TestPyPI and its dependencies from PyPI; do not use
   `--extra-index-url`, which would let a look-alike package on TestPyPI stand
   in for a real dependency.

   ```bash
   python -m venv /tmp/try && . /tmp/try/bin/activate          # Windows: py -m venv %TEMP%\try && %TEMP%\try\Scripts\activate
   pip download --no-deps --index-url https://test.pypi.org/simple/ exactdoc==0.3.0b3 -d dl
   pip install dl/exactdoc-0.3.0b3-py3-none-any.whl
   exactdoc --version          # exactdoc 0.3.0b3
   exactdoc some.pdf           # writes some.docx; without LibreOffice it says so
   exactdoc "résumé 日本.pdf" > log.txt   # a non-Latin name, stdout to a file: exit 0
   ```

   Also open <https://test.pypi.org/project/exactdoc/> and check that the
   description shows its pictures.

7. **Approve the PyPI upload.** In the release run, the `pypi` job shows
   *Waiting for review*: **Review deployments → pypi → Approve and deploy**.

8. **Check the real thing** in another fresh virtualenv:

   ```bash
   pip install --pre exactdoc==0.3.0b3
   exactdoc --version
   ```

   and look at <https://pypi.org/project/exactdoc/>.

   A beta is a *pre-release*: while it is the only version on PyPI, a plain
   `pip install exactdoc` installs it; once a final version exists, testers
   need `pip install --pre exactdoc` to get a newer beta.

9. **Create the GitHub pre-release.** The workflow does not create a GitHub
   release. With the GitHub CLI:

   ```bash
   # the CHANGELOG section written in step 2, without its heading
   awk '/^## 0\.3\.0b3 /{f=1; next} /^## /{f=0} f' CHANGELOG.md > notes-0.3.0b3.md
   gh release create v0.3.0b3 --prerelease --verify-tag \
     --title "exactdoc 0.3.0b3" --notes-file notes-0.3.0b3.md
   ```

   Check the front page afterwards: no release should be marked *Latest*
   until the first final version (a pre-release never is).

   *Historical, done once for 0.3.0b1:* the GitHub release v1.0.1 (from
   before the renumbering to 0.2.0a1) showed as *Latest* and was marked a
   pre-release with a "superseded" note, so a 1.x no longer looks newer than
   the beta. There is nothing to repeat. `docs/release-notes-1.0.1.md` stays
   as history.

## When something goes wrong

- **`build` says the tag does not match.** Delete the tag
  (`git push --delete origin v0.3.0b3` and `git tag -d v0.3.0b3`), fix the
  version, tag again.
- **An upload says the file already exists.** PyPI and TestPyPI never accept
  the same file name twice, even after a deletion. Bump to the next number
  (`0.3.0b4`) and release that.
- **`invalid-publisher`.** One of the five fields in setup step 3 does not
  match the run: owner, repository, workflow file name (`release.yml`),
  environment name, or the project name.
- **TestPyPI passed and the PyPI job failed** for a transient reason: re-run
  the failed job from the Actions page. It uploads the same files.
- **A bad release reached PyPI.** *Yank* it (pypi.org → project → release →
  Options → Yank) rather than deleting it, and release a fixed version. A yanked
  version stays installable by exact pin, so nobody's pinned install breaks.

## Known before the first upload

- **Build warnings: resolved (WP48).** The licence is now the SPDX
  `license = "Apache-2.0"` with `license-files = ["LICENSE"]`, the `License ::`
  classifier is gone and the build requires `setuptools>=77`, so the
  deprecation warnings (builds stop working after 2027-02-18) no longer
  appear; `tests/test_packaging_metadata.py` pins the new form.
- **Python 3.9 is past its end of life** (October 2025). The `install`
  workflow proves 3.9 still installs and converts; raising the floor to 3.10 is
  a product decision.
- **Python 3.9–3.11 and 3.12+ can differ by one percent on a rounding tie.**
  Python 3.12 made `sum()` of floats compensated, and a monospace width scale
  that lands exactly on 87.5% writes `w:w` 87 on older interpreters and 88 on
  3.12 (`tests/test_width_scale.py`). The gated numbers are measured on 3.12.
- **Old tags.** `v1.0.0` and `v1.0.1` exist on GitHub from before the version
  was renumbered to 0.2.0a1. They were never uploaded to PyPI and do not
  trigger the release workflow (it did not exist when they were pushed; pushing
  them again would fail its version check). The v1.0.1 GitHub release was
  marked a pre-release for 0.3.0b1, so it no longer shows as "Latest"
  (step 9, historical).
