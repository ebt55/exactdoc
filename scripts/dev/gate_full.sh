#!/usr/bin/env bash
# Usage: gate_full.sh <name> <srcdir> [steps]
#   steps: comma list of: suite,scripts,golden,gate  (default: all)
# Creates a fresh container from $EXACTDOC_GATE_IMAGE (default exactdoc-gate:boot,
# the bootstrapped canonical snapshot; e.g. exactdoc-gate:boot-carlito for the
# WP31 candidate, see scripts/dev/README.md),
# copies <srcdir> (minus .git/.venv) over /work, runs the CI steps, writes
# <scratch>/runs/<name>.log, removes the container. Exit code = number of failed steps.
export MSYS_NO_PATHCONV=1
NAME="$1"; SRC="$2"; STEPS="${3:-suite,scripts,golden,gate}"
SCR="${EXACTDOC_SCR:-$PWD/.scratch}"
mkdir -p "$SCR/runs"
LOG="$SCR/runs/$NAME.log"
C="exg-$NAME"
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
( cd "$SRC" && tar --exclude=./.git --exclude=./.venv --exclude=./.scratch --exclude='*.pyc' --exclude=__pycache__ --exclude=./testkit/batch -cf - . ) | docker exec -i "$C" tar -xf - -C /work
# Baseline binding (WP43): runall fails a lane whose baseline was recorded in
# another environment or harness reading. EXACTDOC_GATE_ALLOW_STALE_BASELINE=1
# (set by the coordinator until the owner-approved re-record) downgrades that to
# a WARNING; it is passed into the container only when set, and the mode is the
# first thing in the log.
ALLOW=""
if [ "${EXACTDOC_GATE_ALLOW_STALE_BASELINE:-}" = "1" ]; then ALLOW="-e EXACTDOC_GATE_ALLOW_STALE_BASELINE=1"; MODE="TRANSITIONAL ALLOWANCE (EXACTDOC_GATE_ALLOW_STALE_BASELINE=1): a stale baseline is a WARNING"; else MODE="strict: a stale baseline FAILS the gate"; fi
E="docker exec -e FONTCONFIG_FILE=/work/scripts/fonts.conf -e EXACTDOC_BASE_IMAGE_DIGEST=sha256:4fbb8e6a8395de5a7550b33509421a2bafbc0aab6c06ba2cef9ebffbc7092d90 $ALLOW $PROV $C"
P="/work/.venv/bin/python"
fails=0
: > "$LOG"
echo "=== IMAGE $IMAGE $(docker image inspect -f '{{.Id}}' "$IMAGE")" >> "$LOG"
echo "=== BASELINE BINDING $MODE" >> "$LOG"
echo "=== COMMIT ${GIT_COMMIT:-unrecorded} DIRTY=$GIT_DIRTY" >> "$LOG"
run() { echo "=== STEP $1" >> "$LOG"; $E bash -c "set -o pipefail; cd /work && $2" >> "$LOG" 2>&1; rc=$?; echo "=== RC $1 = $rc" >> "$LOG"; [ $rc -ne 0 ] && fails=$((fails+1)); }
$E bash -c "cd /work && $P -m pip install -q -e . 2>/dev/null; true" >/dev/null 2>&1
run manifest "$P testkit/corpus_manifest.py verify"
case ",$STEPS," in *,suite,*) run suite "$P -m unittest discover -s tests 2>&1 | tail -60";; esac
case ",$STEPS," in *,scripts,*) run scripts "$P tests/test_purity.py && $P tests/test_corpus_degradation.py && $P tests/test_gate_mutations.py && $P tests/test_golden_ir_backend.py && $P tests/test_bottom_margin_relief.py && $P tests/test_no_pymupdf.py";; esac
case ",$STEPS," in *,golden,*) run golden "($P testkit/gen_corpus.py testkit/adv >/dev/null 2>&1; $P corpus/make_corpus.py >/dev/null 2>&1; true) && $P testkit/golden_ir.py verify && $P testkit/golden_ir.py verify --backend pdfium";; esac
case ",$STEPS," in *,gate,*) run gate "$P testkit/runall.py";; esac
# keep the lane results for inspection
mkdir -p "$SCR/runs/$NAME.batch"
docker cp "$C:/work/testkit/batch/." "$SCR/runs/$NAME.batch/" >/dev/null 2>&1
docker rm -f "$C" >/dev/null 2>&1
echo "BASELINE_BINDING=$( [ -n "$ALLOW" ] && echo allow-stale || echo strict )" >> "$LOG"
echo "FAILED_STEPS=$fails" >> "$LOG"
exit $fails
