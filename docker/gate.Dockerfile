# The canonical measurement environment, as an image.
#
# Every fidelity number in this repository is a property of a renderer, not only
# of the converter. Two CI failures established that the hard way, both with the
# corpus already frozen byte-for-byte:
#
#   Chromium 149 -> 150       c4_i18n became a different document; dy_p50 5x
#   an unpinned font set      c4_i18n dy_p50 0.15pt -> 2.1pt, within2pt 0.416 -> 0.038
#
# `ubuntu-24.04` on GitHub Actions is not a fixed environment: its LibreOffice
# build, its font collection and its Python patch level all move without anything
# in this repository changing. So "canonical" cannot be a description of a runner
# -- it has to be an artifact with a digest.
#
# This image is that artifact. CI references it by immutable `sha256`, and
# testkit/canonical_env.json records the exact toolchain found inside it.
# Rebuilding may produce different apt versions; that is fine and is the point of
# pinning the *digest* rather than the tag. A new digest is a new environment, and
# adopting one is a deliberate baseline migration (plan §17 rule 2), never a
# side effect of a rebuild.
#
#   docker build -f docker/gate.Dockerfile -t ghcr.io/ebt55/exactdoc-gate:dev .
#   docker run --rm -v "$PWD:/work" -w /work ghcr.io/ebt55/exactdoc-gate:dev \
#       bash -lc 'bash scripts/bootstrap.sh --strict && python testkit/evidence.py'
#
# Base pinned by digest, not by tag. `ubuntu:24.04` is a moving reference and
# would defeat the whole exercise.
FROM ubuntu:24.04@sha256:4fbb8e6a8395de5a7550b33509421a2bafbc0aab6c06ba2cef9ebffbc7092d90

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright

# The renderer, the fonts it is allowed to see, and the toolchain.
#
# The five font packages are exactly the directories scripts/fonts.conf lists.
# LibreOffice's own dependencies drag in Charter, Loma, OpenSymbol and Unifont;
# those stay installed and stay INVISIBLE, because fonts.conf replaces
# fontconfig's search path rather than extending it. Installing the right fonts
# is half the job; seeing no others is the other half.
RUN apt-get update -qq \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl git \
      python3 python3-venv python3-pip \
      fontconfig \
      fonts-liberation \
      fonts-dejavu-core \
      fonts-freefont-ttf \
      fonts-wqy-zenhei \
      fonts-ipafont-gothic \
      libreoffice-writer \
 && rm -rf /var/lib/apt/lists/*

# uv, because uv.lock is the pinned truth for every Python dependency.
RUN curl -fsSL https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh \
 && uv --version

# Chromium, for the corpus generators only.
#
# It is deliberately NOT in the environment fingerprint: the 16 metric inputs are
# frozen fixtures pinned by SHA-256, so the browser no longer touches a measured
# number. It is still needed for the generator health test, which proves the
# corpus could be regenerated.
#
# On Ubuntu both `chromium` and `chromium-browser` apt packages are snap shims
# that exit 1 with "requires the chromium snap to be installed", so the working
# option is Playwright's headless shell. Symlinked to a stable path because the
# install directory carries a version number, and `bootstrap.sh` consults $CHROME
# before it goes looking.
RUN python3 -m venv /opt/pw \
 && /opt/pw/bin/pip install --quiet playwright \
 && /opt/pw/bin/python -m playwright install --with-deps chromium --only-shell \
 && ln -sf "$(find /opt/ms-playwright -name chrome-headless-shell -type f | head -n1)" \
      /usr/local/bin/chrome-headless-shell \
 && /usr/local/bin/chrome-headless-shell --version

ENV CHROME=/usr/local/bin/chrome-headless-shell

# The cache directory scripts/fonts.conf names, world-writable so the image runs
# as any UID a CI job cares to use.
RUN mkdir -p /tmp/exactdoc-fontconfig && chmod 1777 /tmp/exactdoc-fontconfig

# Record what this build actually resolved, inside the image. canonical_env.json
# is the gating record; this is the provenance behind it, readable without a
# Python interpreter and without guessing which apt snapshot was in effect.
RUN { echo "# exactdoc canonical gate image"; \
      echo "built_from_base=ubuntu:24.04@sha256:4fbb8e6a8395de5a7550b33509421a2bafbc0aab6c06ba2cef9ebffbc7092d90"; \
      echo "python=$(python3 --version 2>&1)"; \
      echo "uv=$(uv --version 2>&1)"; \
      echo "soffice=$(soffice --version 2>&1 | head -n1)"; \
      echo "chrome=$(/usr/local/bin/chrome-headless-shell --version 2>&1)"; \
      echo "# apt versions of everything that can move a measured number"; \
      dpkg-query -W -f='${Package}=${Version}\n' \
        libreoffice-writer fontconfig fonts-liberation fonts-dejavu-core \
        fonts-freefont-ttf fonts-wqy-zenhei fonts-ipafont-gothic python3; \
    } > /etc/exactdoc-image.txt \
 && cat /etc/exactdoc-image.txt

LABEL org.opencontainers.image.title="exactdoc canonical gate environment" \
      org.opencontainers.image.description="Pinned LibreOffice + font set for the exactdoc fidelity gate. Referenced by digest; a new digest is a new environment." \
      org.opencontainers.image.source="https://github.com/ebt55/exactdoc" \
      org.opencontainers.image.licenses="Apache-2.0"

WORKDIR /work
CMD ["bash"]
