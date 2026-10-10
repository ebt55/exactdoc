#!/usr/bin/env bash
# Usage: sweep.sh <name> <srcdir> [quality_sweep args...]
# Fresh container from $EXACTDOC_GATE_IMAGE (default exactdoc-gate:boot), copy <srcdir>, run testkit/quality_sweep.py
# with the given args; payload -> <scratch>/runs/<name>.sweep.json, log -> <name>.sweep.log
export MSYS_NO_PATHCONV=1
NAME="$1"; SRC="$2"; shift 2
SCR="${EXACTDOC_SCR:-$PWD/.scratch}"
mkdir -p "$SCR/runs"
C="exs-$NAME"
docker rm -f "$C" >/dev/null 2>&1
IMAGE="${EXACTDOC_GATE_IMAGE:-exactdoc-gate:boot}"
# Provenance (WP43): the container gets a copy of the tree without .git, so the
# commit is read here on the host and passed in, with the image's id.
GIT_COMMIT="$(git -C "$SRC" rev-parse HEAD 2>/dev/null)"
GIT_DIRTY="$( [ -n "$(git -C "$SRC" status --porcelain 2>/dev/null)" ] && echo 1 || echo 0 )"
GIT_BRANCH="$(git -C "$SRC" rev-parse --abbrev-ref HEAD 2>/dev/null)"
IMAGE_ID="$(docker image inspect -f '{{.Id}}' "$IMAGE" 2>/dev/null)"
PROV="-e EXACTDOC_GIT_COMMIT=$GIT_COMMIT -e EXACTDOC_GIT_DIRTY=$GIT_DIRTY -e EXACTDOC_GIT_BRANCH=$GIT_BRANCH -e EXACTDOC_GATE_IMAGE_ID=$IMAGE_ID -e EXACTDOC_GATE_IMAGE_REF=$IMAGE"
docker run -d --name "$C" -w /work "$IMAGE" sleep infinity >/dev/null || exit 99
( cd "$SRC" && tar --exclude=./.git --exclude=./.venv --exclude=./.scratch --exclude='*.pyc' --exclude=__pycache__ --exclude=./testkit/batch --exclude=./testkit/sweep -cf - . ) | docker exec -i "$C" tar -xf - -C /work
docker exec -e FONTCONFIG_FILE=/work/scripts/fonts.conf $PROV "$C" bash -c "cd /work && /work/.venv/bin/python testkit/quality_sweep.py --json /work/sweep.json $*" > "$SCR/runs/$NAME.sweep.log" 2>&1
rc=$?
docker cp "$C:/work/sweep.json" "$SCR/runs/$NAME.sweep.json" >/dev/null 2>&1
if [ -n "$KEEP_DOCX" ]; then mkdir -p "$SCR/runs/$NAME.docx"; docker cp "$C:/work/testkit/sweep/." "$SCR/runs/$NAME.docx/" >/dev/null 2>&1; fi
docker rm -f "$C" >/dev/null 2>&1
echo "IMAGE=$IMAGE $(docker image inspect -f '{{.Id}}' "$IMAGE")" >> "$SCR/runs/$NAME.sweep.log"
echo "COMMIT=${GIT_COMMIT:-unrecorded} DIRTY=$GIT_DIRTY" >> "$SCR/runs/$NAME.sweep.log"
echo "RC=$rc" >> "$SCR/runs/$NAME.sweep.log"
exit $rc
