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
docker run -d --name "$C" -w /work "$IMAGE" sleep infinity >/dev/null || exit 99
( cd "$SRC" && tar --exclude=./.git --exclude=./.venv --exclude=./.scratch --exclude='*.pyc' --exclude=__pycache__ --exclude=./testkit/batch -cf - . ) | docker exec -i "$C" tar -xf - -C /work
E="docker exec -e FONTCONFIG_FILE=/work/scripts/fonts.conf -e EXACTDOC_BASE_IMAGE_DIGEST=sha256:4fbb8e6a8395de5a7550b33509421a2bafbc0aab6c06ba2cef9ebffbc7092d90 $C"
P="/work/.venv/bin/python"
$E bash -c "cd /work && $P -m pip install -q -e . 2>/dev/null; true" >/dev/null 2>&1
: > "$LOG"
echo "=== IMAGE $IMAGE $(docker image inspect -f '{{.Id}}' "$IMAGE")" >> "$LOG"
echo "=== UPDATE" >> "$LOG"; $E bash -c "cd /work && GATE_BASELINE=update $P testkit/runall.py" >> "$LOG" 2>&1; echo "=== RC update = $?" >> "$LOG"
echo "=== VERIFY" >> "$LOG"; $E bash -c "cd /work && $P testkit/runall.py" >> "$LOG" 2>&1; rc=$?; echo "=== RC verify = $rc" >> "$LOG"
docker cp "$C:/work/testkit/gate_baseline.json" "$SCR/runs/$NAME.gate_baseline.json" >/dev/null 2>&1
docker rm -f "$C" >/dev/null 2>&1
exit $rc
