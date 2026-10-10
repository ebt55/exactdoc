#!/usr/bin/env bash
# Usage: rerecord.sh <name> <srcdir>
# Owner-approved baseline re-record in the canonical container: GATE_BASELINE=update
# runall, then a plain runall over the new record (must PASS), then copy the new
# testkit/gate_baseline.json back to <scratch>/runs/<name>.gate_baseline.json.
export MSYS_NO_PATHCONV=1
NAME="$1"; SRC="$2"
SCR="${EXACTDOC_SCR:-$PWD/.scratch}"
LOG="$SCR/runs/$NAME.log"; C="exg-$NAME"
docker rm -f "$C" >/dev/null 2>&1
# $EXACTDOC_GATE_IMAGE as in gate_full.sh. Recording is refused unless the image
# matches testkit/canonical_env.json, so a candidate image needs its record first.
IMAGE="${EXACTDOC_GATE_IMAGE:-exactdoc-gate:boot}"
# Provenance, as gate_full.sh and sweep.sh pass it (WP43): the container gets a
# copy of the tree without .git, so the commit is read here on the host. Run
# this from inside the checkout, or <srcdir> must be one.
GIT_COMMIT="$(git -C "$SRC" rev-parse HEAD 2>/dev/null)"
GIT_DIRTY="$( [ -n "$(git -C "$SRC" status --porcelain 2>/dev/null)" ] && echo 1 || echo 0 )"
GIT_BRANCH="$(git -C "$SRC" rev-parse --abbrev-ref HEAD 2>/dev/null)"
IMAGE_ID="$(docker image inspect -f '{{.Id}}' "$IMAGE" 2>/dev/null)"
PROV="-e EXACTDOC_GIT_COMMIT=$GIT_COMMIT -e EXACTDOC_GIT_DIRTY=$GIT_DIRTY -e EXACTDOC_GIT_BRANCH=$GIT_BRANCH -e EXACTDOC_GATE_IMAGE_ID=$IMAGE_ID -e EXACTDOC_GATE_IMAGE_REF=$IMAGE"
docker run -d --name "$C" -w /work "$IMAGE" sleep infinity >/dev/null || exit 99
( cd "$SRC" && tar --exclude=./.git --exclude=./.venv --exclude=./.scratch --exclude='*.pyc' --exclude=__pycache__ --exclude=./testkit/batch -cf - . ) | docker exec -i "$C" tar -xf - -C /work
E="docker exec -e FONTCONFIG_FILE=/work/scripts/fonts.conf -e EXACTDOC_BASE_IMAGE_DIGEST=sha256:4fbb8e6a8395de5a7550b33509421a2bafbc0aab6c06ba2cef9ebffbc7092d90 $PROV $C"
P="/work/.venv/bin/python"
$E bash -c "cd /work && $P -m pip install -q -e . 2>/dev/null; true" >/dev/null 2>&1
: > "$LOG"
echo "=== IMAGE $IMAGE $(docker image inspect -f '{{.Id}}' "$IMAGE")" >> "$LOG"
echo "=== COMMIT ${GIT_COMMIT:-unrecorded} DIRTY=$GIT_DIRTY" >> "$LOG"
echo "=== UPDATE" >> "$LOG"; $E bash -c "cd /work && GATE_BASELINE=update $P testkit/runall.py" >> "$LOG" 2>&1; echo "=== RC update = $?" >> "$LOG"
echo "=== VERIFY" >> "$LOG"; $E bash -c "cd /work && $P testkit/runall.py" >> "$LOG" 2>&1; rc=$?; echo "=== RC verify = $rc" >> "$LOG"
docker cp "$C:/work/testkit/gate_baseline.json" "$SCR/runs/$NAME.gate_baseline.json" >/dev/null 2>&1
docker rm -f "$C" >/dev/null 2>&1
exit $rc
