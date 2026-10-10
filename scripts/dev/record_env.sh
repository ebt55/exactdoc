#!/usr/bin/env bash
# Usage: record_env.sh <name> <srcdir> [canonical_env.json | canonical_env.proposed.json]
# `evidence.py --record-canonical` in a fresh container from $EXACTDOC_GATE_IMAGE
# (default exactdoc-gate:boot), written to testkit/<file> inside the container
# (default canonical_env.proposed.json, which nothing compares against) and
# copied back to <srcdir>/testkit/<file>. The env vars are the ones the
# recorded canonical_env.json was made with: the base-image digest pinned in
# docker/gate.Dockerfile and the published image's name.
# Recording canonical_env.json itself redefines `canonical`: owner approval only.
export MSYS_NO_PATHCONV=1
NAME="$1"; SRC="$2"; FILE="${3:-canonical_env.proposed.json}"
SCR="${EXACTDOC_SCR:-$PWD/.scratch}"
mkdir -p "$SCR/runs"
LOG="$SCR/runs/$NAME.env.log"; C="exe-$NAME"
IMAGE="${EXACTDOC_GATE_IMAGE:-exactdoc-gate:boot}"
docker rm -f "$C" >/dev/null 2>&1
docker run -d --name "$C" -w /work "$IMAGE" sleep infinity >/dev/null || exit 99
( cd "$SRC" && tar --exclude=./.git --exclude=./.venv --exclude=./.scratch --exclude='*.pyc' --exclude=__pycache__ --exclude=./testkit/batch -cf - . ) | docker exec -i "$C" tar -xf - -C /work
echo "=== IMAGE $IMAGE $(docker image inspect -f '{{.Id}}' "$IMAGE")" > "$LOG"
docker exec -e FONTCONFIG_FILE=/work/scripts/fonts.conf \
    -e EXACTDOC_BASE_IMAGE_DIGEST=sha256:4fbb8e6a8395de5a7550b33509421a2bafbc0aab6c06ba2cef9ebffbc7092d90 \
    -e EXACTDOC_GATE_IMAGE=ghcr.io/ebt55/exactdoc-gate "$C" \
    bash -c "cd /work && /work/.venv/bin/python testkit/evidence.py --record-canonical --force --record-to testkit/$FILE" >> "$LOG" 2>&1
rc=$?
# Through the shell, not `docker cp`: with MSYS_NO_PATHCONV a Git Bash path such
# as /c/Users/... reaches docker.exe unconverted and names C:\c\Users\....
[ $rc -eq 0 ] && docker exec "$C" cat "/work/testkit/$FILE" > "$SRC/testkit/$FILE"
docker rm -f "$C" >/dev/null 2>&1
echo "RC=$rc" >> "$LOG"; cat "$LOG"
exit $rc
