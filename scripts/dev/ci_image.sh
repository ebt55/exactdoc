#!/usr/bin/env bash
# Usage: scripts/dev/ci_image.sh [--no-chrome] [--from IMG] [--tag TAG]
#
# Make the image CI's gate runs in (.github/workflows/gate.yml) from the
# canonical snapshot, WITHOUT changing the measurement environment, so that it
# can be published. Default: exactdoc-gate:boot -> exactdoc-gate:ci. What CI
# pins (WP55) is `--no-chrome --tag exactdoc-gate:ci-nochrome`.
#
# Why not push exactdoc-gate:boot as it is. That snapshot was made with
# `docker commit` of a bootstrapped container (2026-10-04), and its committed
# layer carries the working tree it was bootstrapped from, including the
# maintainer's local agent settings (/work/.claude/settings.local.json) and
# scripts/env.sh. Deleting them in a new layer would still publish them in the
# layer below, so the filesystem is flattened instead: one container, /work
# emptied but for the venv (CI copies each commit's tree in), then `docker
# export | docker import` with the snapshot's own config (ENV, WORKDIR, CMD)
# restored. Nothing the environment fingerprint reads is touched -- the OS,
# Python, LibreOffice, fonts.conf, the font files and the venv's packages --
# so a gate in the result is still environment 9cb0bc17 (verify it: see the
# last lines printed). Only the image id changes; it is provenance, not part of
# the fingerprint, and gate.yml records it in EXACTDOC_GATE_IMAGE_ID.
#
# --no-chrome also removes Playwright's Chrome for Testing (/opt/ms-playwright,
# /opt/pw, /usr/local/bin/chrome-headless-shell) and the CHROME variable. The
# gate does not need it: only tests/test_corpus_generation.py launches it, to
# regenerate the 8 Chromium corpus documents, and that step reports drift and
# never gates; without Chrome it skips those 8 and still passes. The
# fingerprint does not read Chrome (evidence.py records its version as
# provenance only).
#
# Before publishing, scan the result (see the WP55 notes in scripts/dev/README.md).
#
# Uses ONE container, removed at the end. Pushing is a separate, deliberate
# step (needs `docker login ghcr.io`):
#   docker tag <TAG> ghcr.io/ebt55/exactdoc-gate:snapshot-<date>
#   docker push ghcr.io/ebt55/exactdoc-gate:snapshot-<date>
# then pin the printed digest in gate.yml and quality_check.sh (PUBLISHED).
export MSYS_NO_PATHCONV=1
set -euo pipefail
FROM=exactdoc-gate:boot; TAG=exactdoc-gate:ci; NOCHROME=0
while [ $# -gt 0 ]; do
  case "$1" in
    --from) FROM="$2"; shift 2;;
    --tag) TAG="$2"; shift 2;;
    --no-chrome) NOCHROME=1; shift;;
    -h|--help) sed -n '2,38p' "$0"; exit 0;;
    *) echo "unknown option $1" >&2; exit 2;;
  esac
done
C="exci-$$"
docker image inspect "$FROM" >/dev/null || { echo "no image $FROM" >&2; exit 2; }
trap 'docker rm -f "$C" >/dev/null 2>&1 || true' EXIT

# Also the root user's pip and uv caches: they hold a wheel built from that
# old working tree, and CI never reads them (the runner sets HOME=/github/home,
# so uv uses an empty cache there; the venv's files do not depend on them).
SCRUB='find /work -mindepth 1 -maxdepth 1 ! -name .venv -exec rm -rf {} +
rm -f /tmp/uv-*.lock
rm -rf /root/.cache/uv /root/.cache/pip
test -x /work/.venv/bin/python
/work/.venv/bin/python -c "import numpy, lxml, pypdfium2, fitz, docx, PIL, reportlab, fpdf"'
if [ "$NOCHROME" = 1 ]; then
  SCRUB="$SCRUB
rm -rf /opt/ms-playwright /opt/pw /usr/local/bin/chrome-headless-shell
echo '# ci_image.sh --no-chrome: Chrome for Testing removed (the chrome= line above is history)' >> /etc/exactdoc-image.txt"
fi
docker run --name "$C" "$FROM" bash -c "$SCRUB"

# The snapshot's config, as `docker image inspect` reports it, minus CHROME
# when Chrome is gone. Labels: the source link lets GHCR attach the package to
# the repository; no licence label, because the image is not Apache-2.0 as a
# whole (docs/license-audit.md, section 6).
CHANGES=()
while IFS= read -r e; do
  [ -n "$e" ] || continue
  case "$e" in CHROME=*) [ "$NOCHROME" = 1 ] && continue;; esac
  CHANGES+=(--change "ENV $e")
done < <(docker image inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$FROM" | tr -d '\r')
CHANGES+=(--change 'WORKDIR /work' --change 'CMD ["bash"]'
          --change 'LABEL org.opencontainers.image.source=https://github.com/ebt55/exactdoc'
          --change 'LABEL org.opencontainers.image.documentation=https://github.com/ebt55/exactdoc/blob/main/docs/gate-image.md'
          --change 'LABEL org.opencontainers.image.title="exactdoc canonical gate environment"'
          --change "LABEL org.opencontainers.image.description=\"Snapshot of exactdoc-gate:boot (flattened, working tree removed$( [ "$NOCHROME" = 1 ] && echo ', Chrome for Testing removed' || true)). Referenced by digest.\"")
docker export "$C" | docker import "${CHANGES[@]}" - "$TAG" >/dev/null
docker rm -f "$C" >/dev/null

echo "made $TAG from $FROM"
docker image inspect -f 'image id {{.Id}}' "$TAG"
docker image inspect -f '{{json .Config}}' "$TAG"
echo "verify (one container): EXACTDOC_GATE_IMAGE=$TAG bash scripts/dev/gate_full.sh <name> <tree>"
