# Releasing exactdoc

How a version gets from this repository to PyPI. Publishing is automated by
[`.github/workflows/release.yml`](../.github/workflows/release.yml), but it is
inert until the one-time setup below is done by hand, and it only ever runs
when a version tag is pushed. Nothing here uses an API token: PyPI's *Trusted
Publishing* gives the workflow a credential that lasts minutes, for one upload,
and only from this repository's release workflow.

The first public beta will be **0.3.0b1**. The version in `pyproject.toml`
stays `0.2.0a1` until the release commit itself.

## What runs, in order

When a tag such as `v0.3.0b1` is pushed, `release.yml` runs four jobs:

| Job | What it does | Stops the release when |
|---|---|---|
| `build` | Points README's relative links at the tag (`scripts/pypi_readme.py`, so the PyPI page shows its pictures), builds the sdist and wheel once, runs `twine check --strict` and `scripts/check_dist.py` | the tag is not `v` + the version in `pyproject.toml`; the metadata does not render; the files contain anything but the package |
| `testpypi` | Uploads exactly those files to test.pypi.org | TestPyPI refuses them |
| `verify-testpypi` | On Linux and Windows: downloads the wheel back from TestPyPI, checks it is byte-identical to the build, installs it in a clean virtualenv (dependencies from PyPI), checks `exactdoc --version` and converts two test PDFs | any of those fails |
| `pypi` | Uploads the same files to pypi.org | it waits for your approval first (see setup step 4) |

The `install` workflow (`.github/workflows/install.yml`) runs the same build
and a wider install check on every push and pull request: Linux, Windows and
macOS, Python 3.9 and 3.12, the wheel in a clean virtualenv with no
LibreOffice, two conversions, and the unit tests. A release should only be
tagged on a commit where `gate` and `install` are both green.

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

5. **Make sure the repository is public**, and that the commit you will tag is
   on the branch people see (today the work lives on the integration branch
   and `main` is older). The PyPI page's pictures are served from
   `raw.githubusercontent.com` at the tag, and they only load for a public
   repository.

## Each release

The commands below use `0.3.0b1`; replace it with the version being released.

1. **Check readiness.** On the commit to release: the canonical gate is green
   in both lanes, the `install` workflow is green, and
   `python testkit/beta_readiness.py --runs <your runs folder>` has been read.
   (Its bar is a proposal; whether to release with criteria failing is your
   call, and the output says which.)

2. **Bump the version, in one commit.**
   - `pyproject.toml`: `version = "0.3.0b1"`, and the classifier
     `"Development Status :: 3 - Alpha"` → `"Development Status :: 4 - Beta"`.
   - `README.md`: the "Alpha (version 0.2.0a1)" banner, and **delete the
     "Not on PyPI yet" note** in *Install* (after this release it is false).
   - `CHANGELOG.md`: rename `## Unreleased` to `## 0.3.0b1 — <date>` and start
     a new empty `## Unreleased` above it.
   - Push the commit and wait for `gate` and `install` to pass on it.

3. **Tag and push the tag.** The tag must be `v` followed by exactly the
   version in `pyproject.toml`, or the `build` job stops:

   ```bash
   git tag -a v0.3.0b1 -m "exactdoc 0.3.0b1"
   git push origin v0.3.0b1
   ```

4. **Watch it run.** GitHub → **Actions → release**. `build`, `testpypi` and
   `verify-testpypi` run on their own (a few minutes; the verify job retries
   for up to five minutes while TestPyPI's index catches up).

5. **Optionally, try the TestPyPI copy yourself** in a fresh virtualenv. The
   wheel comes from TestPyPI and its dependencies from PyPI; do not use
   `--extra-index-url`, which would let a look-alike package on TestPyPI stand
   in for a real dependency.

   ```bash
   python -m venv /tmp/try && . /tmp/try/bin/activate          # Windows: py -m venv %TEMP%\try && %TEMP%\try\Scripts\activate
   pip download --no-deps --index-url https://test.pypi.org/simple/ exactdoc==0.3.0b1 -d dl
   pip install dl/exactdoc-0.3.0b1-py3-none-any.whl
   exactdoc --version          # exactdoc 0.3.0b1
   exactdoc some.pdf           # writes some.docx; without LibreOffice it says so
   ```

   Also open <https://test.pypi.org/project/exactdoc/> and check that the
   description shows its pictures.

6. **Approve the PyPI upload.** In the release run, the `pypi` job shows
   *Waiting for review*: **Review deployments → pypi → Approve and deploy**.

7. **Check the real thing** in another fresh virtualenv:

   ```bash
   pip install --pre exactdoc==0.3.0b1
   exactdoc --version
   ```

   and look at <https://pypi.org/project/exactdoc/>.

   A beta is a *pre-release*: while it is the only version on PyPI, a plain
   `pip install exactdoc` installs it; once a final version exists, testers
   need `pip install --pre exactdoc` to get a newer beta.

8. **Optionally, a GitHub release** from the tag (Releases → *Draft a new
   release*), with the CHANGELOG section as notes and *Set as a pre-release*
   ticked. The workflow does not create one.

## When something goes wrong

- **`build` says the tag does not match.** Delete the tag
  (`git push --delete origin v0.3.0b1` and `git tag -d v0.3.0b1`), fix the
  version, tag again.
- **An upload says the file already exists.** PyPI and TestPyPI never accept
  the same file name twice, even after a deletion. Bump to the next number
  (`0.3.0b2`) and release that.
- **`invalid-publisher`.** One of the five fields in setup step 3 does not
  match the run: owner, repository, workflow file name (`release.yml`),
  environment name, or the project name.
- **TestPyPI passed and the PyPI job failed** for a transient reason: re-run
  the failed job from the Actions page. It uploads the same files.
- **A bad release reached PyPI.** *Yank* it (pypi.org → project → release →
  Options → Yank) rather than deleting it, and release a fixed version. A yanked
  version stays installable by exact pin, so nobody's pinned install breaks.

## Known before the first upload

- **Build warnings.** setuptools (≥ 77) warns that `license = { text = ... }`
  and the `License ::` classifier are deprecated, and says such builds stop
  working after 2027-02-18. The fix is `license = "Apache-2.0"` plus
  `license-files = ["LICENSE"]`, dropping the classifier and requiring
  `setuptools>=77`; `tests/test_packaging_metadata.py` pins the classifier, so
  change them together. Not urgent for 0.3.0b1.
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
  them again would fail its version check). GitHub may still show v1.0.1 as
  the "latest" release; mark 0.3.0b1 accordingly if you create a GitHub
  release.
