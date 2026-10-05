#!/usr/bin/env bash
# Usage: sweep.sh <name> <srcdir> [quality_sweep args...]
# Fresh container from exactdoc-gate:boot, copy <srcdir>, run testkit/quality_sweep.py
# with the given args; payload -> <scratch>/runs/<name>.sweep.json, log -> <name>.sweep.log
export MSYS_NO_PATHCONV=1
NAME="$1"; SRC="$2"; shift 2
SCR="${EXACTDOC_SCR:-$PWD/.scratch}"
mkdir -p "$SCR/runs"
C="exs-$NAME"
docker rm -f "$C" >/dev/null 2>&1
docker run -d --name "$C" -w /work exactdoc-gate:boot sleep infinity >/dev/null || exit 99
( cd "$SRC" && tar --exclude=./.git --exclude=./.venv --exclude=./.scratch --exclude='*.pyc' --exclude=__pycache__ --exclude=./testkit/batch --exclude=./testkit/sweep -cf - . ) | docker exec -i "$C" tar -xf - -C /work
docker exec -e FONTCONFIG_FILE=/work/scripts/fonts.conf "$C" bash -c "cd /work && /work/.venv/bin/python testkit/quality_sweep.py --json /work/sweep.json $*" > "$SCR/runs/$NAME.sweep.log" 2>&1
rc=$?
docker cp "$C:/work/sweep.json" "$SCR/runs/$NAME.sweep.json" >/dev/null 2>&1
if [ -n "$KEEP_DOCX" ]; then mkdir -p "$SCR/runs/$NAME.docx"; docker cp "$C:/work/testkit/sweep/." "$SCR/runs/$NAME.docx/" >/dev/null 2>&1; fi
docker rm -f "$C" >/dev/null 2>&1
echo "RC=$rc" >> "$SCR/runs/$NAME.sweep.log"
exit $rc
