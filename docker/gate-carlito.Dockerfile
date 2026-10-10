# The Carlito/Caladea font layer, on top of an already-bootstrapped gate image.
#
# Why a layer and not a rebuild: `docker/gate.Dockerfile` resolves its apt
# packages at build time, so rebuilding it today would move LibreOffice, Python
# and fontconfig along with the fonts, and a measured delta could no longer be
# attributed to the fonts. This layer changes exactly one thing -- two metric
# clone families become installed -- on the very image every recorded number was
# measured in. `gate.Dockerfile` installs the same two pinned packages for the
# next full rebuild (a new digest, which is a migration of its own).
#
#   docker build -f docker/gate-carlito.Dockerfile \
#       --build-arg BASE=exactdoc-gate:boot -t exactdoc-gate:boot-carlito docker
#
# (The context is only `docker/`: the layer copies nothing from the tree.)
#
# Why these families: the standard profile writes Calibri and Cambria by name
# (exactdoc/fonts.py), and without their clones the canonical LibreOffice draws
# both in FreeSerif -- a serif at the wrong widths, so every Calibri paragraph
# re-wraps in the measurement and in nobody's real reader. Carlito and Caladea
# are drawn on Calibri's and Cambria's advance widths; scripts/fonts.conf maps
# the Microsoft names onto them exactly as it maps Arial onto Liberation Sans.
#
# Why THESE BUILDS, and not noble's own packages. Measured 2026-10-06 by
# regenerating exactdoc/_clone_widths.py from each build (testkit/
# gen_clone_widths.py) and diffing the WinAnsi advance tables:
#
#   noble fonts-crosextra-caladea 20200211-2   135-173 of ~216 codepoints differ
#       per face from Cambria's widths: its figures are proportional ("1" 362
#       units, "0" 517) where Cambria's are tabular (554). It is a redesign, not
#       a metric clone, and would re-wrap every Cambria paragraph with a number.
#   noble fonts-crosextra-carlito 20230309-2   identical except U+00A0 added.
#   jammy 20130214-2.1 / 20130920-1.1          byte-identical (SHA-256) to the
#       files _clone_widths.py was generated from and records in SOURCES -- the
#       original Crosextra releases, the same files LibreOffice's Windows build
#       bundles. tests/test_clone_metrics.py then checks the converter's width
#       tables against the renderer's own fonts byte for byte.
#
# So both packages come from the jammy pool: architecture-independent font
# packages with no dependencies, fetched by exact filename, and refused unless
# both the .deb and every installed .ttf match the SHA-256 recorded here. A
# version string is a claim; a digest is a measurement.
ARG BASE=exactdoc-gate:boot
FROM ${BASE}
ARG BASE
ARG POOL=http://archive.ubuntu.com/ubuntu/pool/universe/f

RUN set -e; mkdir -p /tmp/crosextra; cd /tmp/crosextra; \
    curl -fsSLO "${POOL}/fonts-crosextra-carlito/fonts-crosextra-carlito_20130920-1.1_all.deb"; \
    curl -fsSLO "${POOL}/fonts-crosextra-caladea/fonts-crosextra-caladea_20130214-2.1_all.deb"; \
    printf '%s\n' \
      "7385475cde807e1363c3361976576571870373032466c7f525d5900852b6f420  fonts-crosextra-carlito_20130920-1.1_all.deb" \
      "1330d25dfa5bab2e9b712b4950d2855cdb63a2b2b9451e2ffb93618c77e1f242  fonts-crosextra-caladea_20130214-2.1_all.deb" \
      | sha256sum -c -; \
    dpkg -i ./*.deb; \
    apt-mark hold fonts-crosextra-carlito fonts-crosextra-caladea; \
    cd /; rm -rf /tmp/crosextra; \
    cd /usr/share/fonts/truetype/crosextra; \
    printf '%s\n' \
      "b4ff23ba370cc95a3c349336b73f9c28514a1371210f89832efc85c4b1ea7131  Carlito-Regular.ttf" \
      "0f62ab34ad5d079a0a28fac01bcf7c7a724a4db4d6cb99cab9cabff382fbb80f  Carlito-Bold.ttf" \
      "718a0663864d37a4868220a19b9668a5fe10a46197f6df367b4c2c30c04c026c  Carlito-Italic.ttf" \
      "380764b6898d7b73ceae6384b2958b196d2a0428962ef3adf138d27947228666  Carlito-BoldItalic.ttf" \
      "d2f6cad33f191e65b68bd74e6d4f7708080a41b32db635866109df3090265d91  Caladea-Regular.ttf" \
      "74eda4fc5ffba0d8dc4aa76d41499f5ab76168d9ed6141c6417064c6244db9b6  Caladea-Bold.ttf" \
      "9c968bf60ba1e851cdfea77c71e3540c57792f77482dd241acc29d1425569c4e  Caladea-Italic.ttf" \
      "f47a35ad6cd0efa9914d93f9d03c93e30c55da43674bccfabac73b3c0d522c01  Caladea-BoldItalic.ttf" \
      | sha256sum -c -; \
    test "$(ls | wc -l)" -eq 8; \
    { echo "# layer: docker/gate-carlito.Dockerfile on ${BASE}"; \
      dpkg-query -W -f='${Package}=${Version}\n' \
        fonts-crosextra-carlito fonts-crosextra-caladea; \
    } >> /etc/exactdoc-image.txt; \
    cat /etc/exactdoc-image.txt

WORKDIR /work
