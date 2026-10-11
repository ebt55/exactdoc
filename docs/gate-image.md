# The published measurement image

CI's fidelity gate (`.github/workflows/gate.yml`) runs inside
`ghcr.io/ebt55/exactdoc-gate`, pinned by digest:

    ghcr.io/ebt55/exactdoc-gate@sha256:b46332899ad379ce6afa3bfadaead5bfaad039b2d5556bc78fdb7c17c3b32eb4
    (tag: snapshot-2026-10-11)

`scripts/dev/quality_check.sh` uses the same image by default, so a
contributor's local verdict and CI's agree.

## What it is

The maintainer's canonical measurement snapshot (`exactdoc-gate:boot`, built
from [docker/gate.Dockerfile](../docker/gate.Dockerfile) and the Carlito layer
[docker/gate-carlito.Dockerfile](../docker/gate-carlito.Dockerfile), then
provisioned with `scripts/bootstrap.sh`), flattened by
`scripts/dev/ci_image.sh --no-chrome`. That removes the working tree the
snapshot was provisioned from, the root user's pip and uv caches and Chrome
for Testing, and changes nothing the environment fingerprint reads: inside it
the gate is environment 9cb0bc17, the one `testkit/gate_baseline.json` was
recorded in. It is not rebuilt, because a rebuild resolves today's packages
and is a new environment ([scripts/dev/README.md](../scripts/dev/README.md),
step 7).

It is a measuring instrument for this repository. Nothing in it is part of
the `exactdoc` package on PyPI, and exactdoc's own code is Apache-2.0
([LICENSE](../LICENSE)); the image as a whole carries the licences of the
software in it.

## Sources of the software in the image

The image contains free and open-source software under its own licences,
including the GNU GPL, the GNU LGPL, the GNU AGPL and the Mozilla Public
License. The complete corresponding source of each component is available
from the places below. If you need a source that is not reachable there,
open an issue and it will be provided.

**Ubuntu 24.04 LTS ("noble") packages.** The base is
`ubuntu:24.04@sha256:4fbb8e6a8395de5a7550b33509421a2bafbc0aab6c06ba2cef9ebffbc7092d90`,
and every distribution package in the image is an unmodified Ubuntu binary.
List them, with exact versions, with

    docker run --rm ghcr.io/ebt55/exactdoc-gate@sha256:b46332899ad379ce6afa3bfadaead5bfaad039b2d5556bc78fdb7c17c3b32eb4 dpkg-query -W

and get the source of any of them from the Ubuntu archive
(<https://archive.ubuntu.com/ubuntu/pool/>, <https://launchpad.net/ubuntu/+source/>),
or with `apt-get source <package>=<version>` on an Ubuntu 24.04 system with
`deb-src` entries enabled. The measurement-relevant ones are recorded in
`/etc/exactdoc-image.txt` inside the image, among them:

| Package | Version | Licence (main) | Upstream |
|---|---|---|---|
| `libreoffice-writer` (and the LibreOffice packages it pulls in) | 4:24.2.7-0ubuntu0.24.04.6 | MPL-2.0 (parts LGPL-3.0+) | <https://www.libreoffice.org/about-us/source-code/>, <https://git.libreoffice.org/core> |
| `fonts-liberation` | 1:2.1.5-3 | SIL OFL 1.1 | <https://github.com/liberationfonts/liberation-fonts> |
| `fonts-dejavu-core` | 2.37-8 | Bitstream Vera / public-domain changes | <https://dejavu-fonts.github.io/> |
| `fonts-freefont-ttf` (GNU FreeFont) | 20211204+svn4273-2 | GPL-3.0+ with font exception | <https://www.gnu.org/software/freefont/> |
| `fonts-wqy-zenhei` (WenQuanYi Zen Hei) | 0.9.45-8 | GPL-2.0 with font exception | <https://sourceforge.net/projects/wqy/> |
| `fonts-ipafont-gothic` | 00303-21ubuntu1 | IPA Font License 1.0 | <https://moji.or.jp/ipafont/> |
| `python3` (CPython 3.12.3) | 3.12.3-0ubuntu2.1 | PSF-2.0 | <https://www.python.org/downloads/source/> |
| `fontconfig` | 2.15.0-1.1ubuntu2 | MIT-style | <https://gitlab.freedesktop.org/fontconfig/fontconfig> |

**Carlito and Caladea.** Installed from the Ubuntu 22.04 ("jammy") pool by
exact file name and SHA-256 (see the Dockerfiles):
`fonts-crosextra-carlito` 20130920-1.1 (SIL OFL 1.1) and
`fonts-crosextra-caladea` 20130214-2.1 (Apache-2.0). Source packages:
<https://archive.ubuntu.com/ubuntu/pool/universe/f/fonts-crosextra-carlito/>,
<https://archive.ubuntu.com/ubuntu/pool/universe/f/fonts-crosextra-caladea/>.
Upstream: <https://github.com/googlefonts/carlito>,
<https://github.com/huertatipografica/Caladea>.

**The Python environment (`/work/.venv`).** Installed by uv from PyPI at the
versions pinned in [uv.lock](../uv.lock); listed with
`uv pip freeze --python /work/.venv/bin/python` inside the image.
The copyleft ones:

| Package | Version | Licence | Source |
|---|---|---|---|
| PyMuPDF, with the MuPDF it bundles | 1.28.0 | AGPL-3.0 | <https://github.com/pymupdf/PyMuPDF>, <https://github.com/ArtifexSoftware/mupdf> |
| fpdf2 | 2.8.7 | LGPL-3.0 | <https://github.com/py-pdf/fpdf2> |

PyMuPDF is a reference instrument for the measurement harness and is never
part of the exactdoc wheel ([docs/license-audit.md](license-audit.md),
sections 2 and 6). The other packages (pypdfium2 with PDFium, numpy, lxml,
Pillow, python-docx, reportlab, fontTools and their dependencies) are under
permissive licences; their sources are on PyPI and their project pages.

**uv** (`/usr/local/bin/uv`, Apache-2.0 or MIT): <https://github.com/astral-sh/uv>.
