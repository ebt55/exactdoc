#!/usr/bin/env bash
# Run the CI-equivalent checks, or a quality sweep, in the canonical container
# from any checkout -- including a Windows one, where fidelity numbers are
# otherwise meaningless (host fonts, a different LibreOffice).
#
#   scripts/canon.sh image                       # build exactdoc-gate:dev, bootstrap it, snapshot :boot
#   scripts/canon.sh gate  <name> [steps]        # steps: suite,scripts,golden,gate (default: all)
#   scripts/canon.sh sweep <name> [quality_sweep args...]
#
# Each run gets a FRESH container from the bootstrapped snapshot, the working
# tree is copied in (never bind-mounted: a Windows bind mount changes file
# semantics under LibreOffice), and the container is removed afterwards. Logs
# and payloads land in $CANON_OUT (default: ./testkit/canon_runs, gitignored).
# A run measures the working tree as it is, uncommitted edits included.
#
# The environment fingerprint only matches the recorded canonical one when the
# base-image digest is declared; it is the digest pinned in the Dockerfile's
# FROM line, so declaring it for a local build is truthful.
set -u
export MSYS_NO_PATHCONV=1
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${CANON_OUT:-$ROOT/testkit/canon_runs}"
DIGEST="sha256:4fbb8e6a8395de5a7550b33509421a2bafbc0aab6c06ba2cef9ebffbc7092d90"
BOOT="exactdoc-gate:boot"
mkdir -p "$OUT"

_copy_in() {   # container
    ( cd "$ROOT" && tar --exclude=./.git --exclude=./.venv --exclude='*.pyc' \
        --exclude=__pycache__ --exclude=./testkit/batch --exclude=./testkit/sweep \
        --exclude=./testkit/canon_runs -cf - . ) | docker exec -i "$1" tar -xf - -C /work
}

_exec() {      # container cmd...
    local c="$1"; shift
    docker exec -e FONTCONFIG_FILE=/work/scripts/fonts.conf \
        -e EXACTDOC_BASE_IMAGE_DIGEST="$DIGEST" "$c" bash -c "cd /work && $*"
}

case "${1:-}" in
image)
    docker build -f "$ROOT/docker/gate.Dockerfile" -t exactdoc-gate:dev "$ROOT" || exit 1
    c=exactdoc-canon-boot
    docker rm -f "$c" >/dev/null 2>&1
    docker run -d --name "$c" -w /work exactdoc-gate:dev sleep infinity >/dev/null || exit 1
    _copy_in "$c"
    _exec "$c" "bash scripts/bootstrap.sh --strict" || { docker rm -f "$c"; exit 1; }
    docker commit "$c" "$BOOT" >/dev/null && docker rm -f "$c" >/dev/null
    echo "bootstrapped snapshot: $BOOT"
    ;;
gate)
    name="$2"; steps="${3:-suite,scripts,golden,gate}"
    c="canon-gate-$name"; log="$OUT/$name.gate.log"; P=/work/.venv/bin/python
    docker rm -f "$c" >/dev/null 2>&1
    docker run -d --name "$c" -w /work "$BOOT" sleep infinity >/dev/null || exit 99
    _copy_in "$c"; : > "$log"; fails=0
    step() { echo "=== STEP $1" >> "$log"; _exec "$c" "$2" >> "$log" 2>&1; rc=$?
             echo "=== RC $1 = $rc" >> "$log"; [ $rc -ne 0 ] && fails=$((fails+1)); }
    step manifest "$P testkit/corpus_manifest.py verify"
    case ",$steps," in *,suite,*) step suite "$P -m unittest discover -s tests 2>&1 | tail -60";; esac
    case ",$steps," in *,scripts,*) step scripts "$P tests/test_purity.py && $P tests/test_corpus_degradation.py && $P tests/test_gate_mutations.py && $P tests/test_golden_ir_backend.py && $P tests/test_bottom_margin_relief.py && $P tests/test_no_pymupdf.py";; esac
    case ",$steps," in *,golden,*) step golden "($P testkit/gen_corpus.py testkit/adv >/dev/null 2>&1; $P corpus/make_corpus.py >/dev/null 2>&1; true) && $P testkit/golden_ir.py verify && $P testkit/golden_ir.py verify --backend pdfium";; esac
    case ",$steps," in *,gate,*) step gate "$P testkit/runall.py";; esac
    mkdir -p "$OUT/$name.batch"
    docker cp "$c:/work/testkit/batch/." "$OUT/$name.batch/" >/dev/null 2>&1
    docker rm -f "$c" >/dev/null 2>&1
    echo "FAILED_STEPS=$fails" >> "$log"; echo "$log: FAILED_STEPS=$fails"
    exit $fails
    ;;
sweep)
    name="$2"; shift 2
    c="canon-sweep-$name"; log="$OUT/$name.sweep.log"
    docker rm -f "$c" >/dev/null 2>&1
    docker run -d --name "$c" -w /work "$BOOT" sleep infinity >/dev/null || exit 99
    _copy_in "$c"
    _exec "$c" "/work/.venv/bin/python testkit/quality_sweep.py --json /work/sweep.json $*" > "$log" 2>&1
    rc=$?
    docker cp "$c:/work/sweep.json" "$OUT/$name.sweep.json" >/dev/null 2>&1
    if [ -n "${KEEP_DOCX:-}" ]; then
        mkdir -p "$OUT/$name.docx"; docker cp "$c:/work/testkit/sweep/." "$OUT/$name.docx/" >/dev/null 2>&1
    fi
    docker rm -f "$c" >/dev/null 2>&1
    echo "RC=$rc" >> "$log"; echo "$log: RC=$rc"
    exit $rc
    ;;
*)
    sed -n '2,20p' "$0"; exit 2
    ;;
esac
