#!/usr/bin/env bash
# Usage: gate_full.sh <name> <srcdir> [steps]
#   steps: comma list of: suite,scripts,golden,gate  (default: all)
# Creates a fresh container from exactdoc-gate:boot (bootstrapped venv inside),
# copies <srcdir> (minus .git/.venv) over /work, runs the CI steps, writes
# <scratch>/runs/<name>.log, removes the container. Exit code = number of failed steps.
export MSYS_NO_PATHCONV=1
NAME="$1"; SRC="$2"; STEPS="${3:-suite,scripts,golden,gate}"
SCR="${EXACTDOC_SCR:-$PWD/.scratch}"
mkdir -p "$SCR/runs"
LOG="$SCR/runs/$NAME.log"
C="exg-$NAME"
docker rm -f "$C" >/dev/null 2>&1
docker run -d --name "$C" -w /work exactdoc-gate:boot sleep infinity >/dev/null || exit 99
( cd "$SRC" && tar --exclude=./.git --exclude=./.venv --exclude=./.scratch --exclude='*.pyc' --exclude=__pycache__ --exclude=./testkit/batch -cf - . ) | docker exec -i "$C" tar -xf - -C /work
E="docker exec -e FONTCONFIG_FILE=/work/scripts/fonts.conf -e EXACTDOC_BASE_IMAGE_DIGEST=sha256:4fbb8e6a8395de5a7550b33509421a2bafbc0aab6c06ba2cef9ebffbc7092d90 $C"
P="/work/.venv/bin/python"
fails=0
: > "$LOG"
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
echo "FAILED_STEPS=$fails" >> "$LOG"
exit $fails
