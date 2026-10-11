#!/usr/bin/env bash
# Usage: scripts/dev/quality_check.sh [options]
#
# Does my change lift quality, leave it alone, or regress it?
#
# Measures two commits, BASE and HEAD, in ONE container from the measurement
# image, one after the other, the same way: the corpus identity check, the
# strict fidelity gate (testkit/runall.py: the gated 16, raw and product
# lanes) and, with --corpus both, the product profile on the 79 expansion
# documents (testkit/quality_sweep.py). Then testkit/quality_check.py compares
# them document by document with gate.py's tolerances (criterion 8 of
# docs/beta-bar.md) and prints one verdict:
#
#   exit 0  LIFTS             something better beyond tolerance, nothing worse
#   exit 1  REGRESSES         something worse beyond tolerance, a new crash,
#                             or a gate finding on HEAD
#   exit 2  UNMEASURED        the two sides could not be compared (read why)
#   exit 3  NEUTRAL           nothing better, nothing worse
#   with --repeat REF (the determinism proof):
#   exit 0  DETERMINISTIC     every DOCX's word/*.xml and every number identical
#   exit 4  NONDETERMINISTIC  something differed between two runs of one commit
#
# Results go to OUT (default $EXACTDOC_SCR/qc/<base>-<head>, EXACTDOC_SCR
# defaulting to ./.scratch): report.json (paste it into the PR), verdict.txt,
# one log per step, base/ and head/ with each side's record and its DOCX.
#
# Options:
#   --base REF        compare against this commit. Default: the merge-base of
#                     HEAD with the first that exists of $EXACTDOC_QC_BASE_BRANCH,
#                     upstream/main, origin/main, main.
#   --head REF        the commit to measure (default HEAD). Only COMMITTED trees
#                     are measured (git archive); uncommitted edits are not.
#   --repeat REF      measure REF twice and judge determinism instead
#   --corpus C        gated (default: the 16, both lanes, ~10-20 min per commit)
#                     or both (+ the expansion corpus, product; ~1 h per commit)
#   --jobs N          documents side by side in the sweep (default 4)
#   --image IMG       measurement image. Default: $EXACTDOC_GATE_IMAGE, else
#                     exactdoc-gate:boot if it exists (the maintainer's canonical
#                     snapshot), else exactdoc-gate:local-boot (made by --build)
#   --build           build docker/gate.Dockerfile as exactdoc-gate:local, then
#                     provision it with scripts/bootstrap.sh --strict and save it
#                     as exactdoc-gate:local-boot (needs the network; ~10 min once)
#   --out DIR         where the results go
#   --keep            leave the container running (named in the output)
#   --dry-run         print what would run, run nothing
#
# Needs: git, bash, Docker. On Windows, Git Bash (the script sets
# MSYS_NO_PATHCONV). The comparison is valid in any image because both commits
# are measured in the same container; the gate's absolute PASS/FAIL is the
# number of record only in the canonical environment (testkit/canonical_env.json),
# and the report says which it was. See CONTRIBUTING.md.
export MSYS_NO_PATHCONV=1
set -u

BASE=""; HEAD_REF="HEAD"; REPEAT=""; CORPUS="gated"; JOBS=4; IMAGE="${EXACTDOC_GATE_IMAGE:-}"
BUILD=0; OUT=""; KEEP=0; DRY=0
die() { echo "quality_check: $*" >&2; exit 2; }
while [ $# -gt 0 ]; do
  case "$1" in
    --base) BASE="${2:?--base needs a ref}"; shift 2;;
    --head) HEAD_REF="${2:?--head needs a ref}"; shift 2;;
    --repeat) REPEAT="${2:?--repeat needs a ref}"; shift 2;;
    --corpus) CORPUS="${2:?}"; shift 2;;
    --jobs) JOBS="${2:?}"; shift 2;;
    --image) IMAGE="${2:?}"; shift 2;;
    --build) BUILD=1; shift;;
    --out) OUT="${2:?}"; shift 2;;
    --keep) KEEP=1; shift;;
    --dry-run) DRY=1; shift;;
    -h|--help) sed -n '2,51p' "$0"; exit 0;;
    *) die "unknown option $1 (see --help)";;
  esac
done
case "$CORPUS" in gated|both) ;; *) die "--corpus is gated or both";; esac
case "$JOBS" in ''|*[!0-9]*) die "--jobs takes a number";; esac

# A Windows-native path where the shell can give one (Git Bash): with
# MSYS_NO_PATHCONV a /c/... path means nothing to git.exe.
HERE="$(cd "$(dirname "$0")" && (pwd -W 2>/dev/null || pwd))"
ROOT="$(git -C "$HERE" rev-parse --show-toplevel 2>/dev/null)" || die "not inside a git checkout"
g() { git -C "$ROOT" "$@"; }
sha() { g rev-parse --verify --quiet "$1^{commit}" || die "not a commit: $1"; }

# ------------------------------------------------------------- the two commits
if [ -n "$REPEAT" ]; then
  BASE_SHA="$(sha "$REPEAT")" || exit 2; HEAD_SHA="$BASE_SHA"
  BASE_NAME="$REPEAT"; HEAD_NAME="$REPEAT"; MODE=repeat
else
  HEAD_SHA="$(sha "$HEAD_REF")" || exit 2; HEAD_NAME="$HEAD_REF"; MODE=compare
  if [ -z "$BASE" ]; then
    for b in "${EXACTDOC_QC_BASE_BRANCH:-}" upstream/main origin/main main; do
      [ -n "$b" ] && g rev-parse --verify --quiet "$b^{commit}" >/dev/null && { BASE_BRANCH="$b"; break; }
    done
    [ -n "${BASE_BRANCH:-}" ] || die "no base branch found; pass --base REF"
    BASE="$(g merge-base "$BASE_BRANCH" "$HEAD_SHA")" || die "no merge-base of $BASE_BRANCH and $HEAD_REF"
    BASE_NAME="merge-base($BASE_BRANCH)"
  else
    BASE_NAME="$BASE"
  fi
  BASE_SHA="$(sha "$BASE")" || exit 2
  [ "$BASE_SHA" != "$HEAD_SHA" ] || die "BASE and HEAD are the same commit ($HEAD_SHA); \
for the determinism proof use --repeat $HEAD_REF"
fi
B7="${BASE_SHA:0:7}"; H7="${HEAD_SHA:0:7}"
SCR="${EXACTDOC_SCR:-$ROOT/.scratch}"
OUT="${OUT:-$SCR/qc/$B7-$H7$( [ $MODE = repeat ] && echo -repeat)-$CORPUS}"
C="exq-$B7-$H7-$$"
DIGEST=sha256:4fbb8e6a8395de5a7550b33509421a2bafbc0aab6c06ba2cef9ebffbc7092d90

if [ $MODE = compare ] && [ "$HEAD_REF" = HEAD ] && [ -n "$(g status --porcelain --untracked-files=no)" ]; then
  echo "NOTE: the working tree has uncommitted changes; they are NOT measured. Commit first."
fi
if [ $MODE = compare ] && ! g diff --quiet "$BASE_SHA" "$HEAD_SHA" -- uv.lock; then
  echo "NOTE: uv.lock differs between BASE and HEAD; the verdict will be UNMEASURED."
fi

# ------------------------------------------------------------------ the image
have_image() { docker image inspect "$1" >/dev/null 2>&1; }
if ! docker version >/dev/null 2>&1; then
  [ "$DRY" = 1 ] || die "Docker is not reachable: start Docker Desktop (or the docker daemon) first"
  echo "NOTE: Docker is not reachable; the plan below is printed anyway."
fi
run() {   # print, then run unless --dry-run
  { printf '+'; printf ' %q' "$@"; printf '\n'; } >&2
  [ "$DRY" = 1 ] || "$@"
}
# provision CONTAINER: scripts/bootstrap.sh --strict on HEAD's tree inside it,
# which creates /work/.venv from uv.lock (needs the network), then /work is
# emptied but for the venv. For an image built from docker/gate.Dockerfile or
# pulled from wherever gate-image.yml publishes it: neither carries a venv.
provision() {
  g -c core.autocrlf=false archive --format=tar "$HEAD_SHA" | docker exec -i "$1" tar -xf - -C /work
  docker exec "$1" bash -c "cd /work && bash scripts/bootstrap.sh --strict" > "$OUT/provision.log" 2>&1 \
    || return 1
  docker exec "$1" bash -c 'find /work -mindepth 1 -maxdepth 1 ! -name .venv -exec rm -rf {} +'
}
[ "$DRY" = 1 ] || mkdir -p "$OUT" 2>/dev/null || die "cannot create $OUT"
if [ "$BUILD" = 1 ]; then
  echo "== building exactdoc-gate:local from docker/gate.Dockerfile"
  run docker build -f "$ROOT/docker/gate.Dockerfile" -t exactdoc-gate:local "$ROOT" || die "docker build failed"
  BC="exq-build-$$"
  echo "== provisioning it as exactdoc-gate:local-boot (log: $OUT/provision.log)"
  if [ "$DRY" = 0 ]; then
    docker rm -f "$BC" >/dev/null 2>&1
    docker run -d --name "$BC" -w /work exactdoc-gate:local sleep infinity >/dev/null || die "docker run failed"
    provision "$BC" || { docker rm -f "$BC" >/dev/null; die "bootstrap failed: $OUT/provision.log"; }
    docker commit "$BC" exactdoc-gate:local-boot >/dev/null || die "docker commit failed"
    docker rm -f "$BC" >/dev/null
  else
    echo "+ (container from exactdoc-gate:local; git archive HEAD into /work; bash scripts/bootstrap.sh --strict; docker commit -> exactdoc-gate:local-boot)" >&2
  fi
  [ -n "$IMAGE" ] || IMAGE=exactdoc-gate:local-boot
fi
if [ -z "$IMAGE" ]; then
  if have_image exactdoc-gate:boot; then IMAGE=exactdoc-gate:boot
  elif have_image exactdoc-gate:local-boot; then IMAGE=exactdoc-gate:local-boot
  elif [ "$DRY" = 1 ]; then IMAGE=exactdoc-gate:local-boot
  else die "no measurement image: run once with --build (or pass --image)"; fi
fi
IMAGE_ID="$(docker image inspect -f '{{.Id}}' "$IMAGE" 2>/dev/null)"
[ -n "$IMAGE_ID" ] || [ "$DRY" = 1 ] || die "image $IMAGE not found"

echo "quality check: $MODE, corpus $CORPUS, jobs $JOBS"
echo "  BASE $BASE_SHA ($BASE_NAME)"
echo "  HEAD $HEAD_SHA ($HEAD_NAME)"
echo "  image $IMAGE ${IMAGE_ID:0:19}"
echo "  out $OUT"

# ----------------------------------------------------------------- one container
cleanup() {
  if [ "$KEEP" = 1 ]; then echo "container kept: $C (docker rm -f $C)"
  else docker rm -f "$C" >/dev/null 2>&1; fi
}
if [ "$DRY" = 0 ]; then
  docker rm -f "$C" >/dev/null 2>&1
  docker run -d --name "$C" -w /work "$IMAGE" sleep infinity >/dev/null || die "docker run $IMAGE failed"
  trap cleanup EXIT
  if ! docker exec "$C" test -x /work/.venv/bin/python; then
    echo "== $IMAGE is not provisioned: running scripts/bootstrap.sh --strict in this container"
    echo "   (log: $OUT/provision.log; --build keeps a provisioned image for next time)"
    provision "$C" || die "bootstrap failed: $OUT/provision.log"
  fi
  docker exec "$C" mkdir -p /qc/tool /qc/out
  # The comparison is this checkout's, whatever the two commits carry.
  tar -C "$ROOT/testkit" -cf - quality_check.py gate.py beta_readiness.py \
    | docker exec -i "$C" tar -xf - -C /qc/tool
  g diff --name-only "$BASE_SHA" "$HEAD_SHA" | docker exec -i "$C" sh -c 'cat > /qc/out/changed_files.txt'
else
  echo "+ docker run -d --name $C -w /work $IMAGE sleep infinity" >&2
fi
P=/work/.venv/bin/python

# measure SIDE SHA NAME: one commit, from a clean /work (the image's venv kept)
measure() {
  local side="$1" s="$2" name="$3" t0 rc_m rc_g rc_s=0 t_g t_s=0
  local E=(docker exec -e FONTCONFIG_FILE=/work/scripts/fonts.conf -e EXACTDOC_BASE_IMAGE_DIGEST=$DIGEST
           -e EXACTDOC_GIT_COMMIT="$s" -e EXACTDOC_GIT_DIRTY=0 -e EXACTDOC_GIT_BRANCH="$name"
           -e EXACTDOC_GATE_IMAGE_ID="$IMAGE_ID" -e EXACTDOC_GATE_IMAGE_REF="$IMAGE" "$C")
  echo "== $side: ${s:0:12} ($name)"
  if [ "$DRY" = 1 ]; then
    echo "+ git archive $s | tar -x -C /work   (after emptying /work but .venv)" >&2
    echo "+ ${E[*]} bash -c 'cd /work && $P testkit/corpus_manifest.py verify'" >&2
    echo "+ ${E[*]} bash -c 'cd /work && $P testkit/runall.py --no-images --out /qc/$side/batch'" >&2
    [ "$CORPUS" = both ] && echo "+ ${E[*]} bash -c 'cd /work && $P testkit/quality_sweep.py --corpus expansion --profile product --jobs $JOBS --out /qc/$side/sweep --json /qc/$side/sweep.json'" >&2
    echo "+ docker exec $C $P /qc/tool/quality_check.py collect --side $side ..." >&2
    return 0
  fi
  # Each side starts as a fresh container would: the tree replaced, and /tmp
  # (where the converter and the harness keep their LibreOffice profiles)
  # emptied but for the fontconfig cache scripts/fonts.conf names.
  docker exec "$C" bash -c "find /work -mindepth 1 -maxdepth 1 ! -name .venv -exec rm -rf {} + ; \
find /tmp -mindepth 1 -maxdepth 1 ! -name exactdoc-fontconfig -exec rm -rf {} + ; \
rm -rf /qc/$side /qc/out/$side; mkdir -p /qc/$side"
  g -c core.autocrlf=false archive --format=tar "$s" | docker exec -i "$C" tar -xf - -C /work \
    || die "could not copy $s into the container"
  "${E[@]}" bash -c "cd /work && $P testkit/corpus_manifest.py verify" > "$OUT/$side.manifest.log" 2>&1
  rc_m=$?
  t0=$SECONDS
  # Strict: EXACTDOC_GATE_ALLOW_STALE_BASELINE is never passed into the container.
  "${E[@]}" bash -c "cd /work && $P testkit/runall.py --no-images --out /qc/$side/batch" > "$OUT/$side.gate.log" 2>&1
  rc_g=$?; t_g=$((SECONDS - t0))
  echo "   gate rc $rc_g in ${t_g}s ($(grep -E 'gate (PASS|FAIL)' "$OUT/$side.gate.log" | tr -s ' ' | paste -sd ';' -))"
  local SW=()
  if [ "$CORPUS" = both ]; then
    t0=$SECONDS
    "${E[@]}" bash -c "cd /work && $P testkit/quality_sweep.py --corpus expansion --profile product --jobs $JOBS --out /qc/$side/sweep --json /qc/$side/sweep.json" > "$OUT/$side.sweep.log" 2>&1
    rc_s=$?; t_s=$((SECONDS - t0))
    echo "   sweep rc $rc_s in ${t_s}s ($(grep -c ' done ' "$OUT/$side.sweep.log") documents)"
    SW=(--sweep /qc/$side/sweep.json --sweep-dir /qc/$side/sweep)
  fi
  docker exec "$C" "$P" /qc/tool/quality_check.py collect --side "$side" \
      --batch /qc/$side/batch ${SW[@]+"${SW[@]}"} --out /qc/out/$side --ref "$name" --commit "$s" \
      --step manifest=$rc_m --step gate=$rc_g --step sweep=$rc_s \
      --timing gate_s=$t_g --timing sweep_s=$t_s >> "$OUT/$side.gate.log" 2>&1 \
    || echo "   collect failed (see $OUT/$side.gate.log)"
}

measure base "$BASE_SHA" "$BASE_NAME"
measure head "$HEAD_SHA" "$HEAD_NAME"

# ----------------------------------------------------------------- the verdict
REP=()
[ $MODE = repeat ] && REP=(--repeat)
if [ "$DRY" = 1 ]; then
  echo "+ docker exec $C $P /qc/tool/quality_check.py compare /qc/out/base /qc/out/head --json /qc/out/report.json --changed-files /qc/out/changed_files.txt ${REP[*]+${REP[*]}}" >&2
  exit 0
fi
docker exec "$C" "$P" /qc/tool/quality_check.py compare /qc/out/base /qc/out/head \
    --json /qc/out/report.json --changed-files /qc/out/changed_files.txt ${REP[@]+"${REP[@]}"} \
  | tee "$OUT/verdict.txt"
rc=${PIPESTATUS[0]}
# Through the shell, not `docker cp`: with MSYS_NO_PATHCONV a Git Bash path does
# not reach docker.exe as a Windows path (see scripts/dev/record_env.sh).
docker exec "$C" tar -cf - -C /qc/out . | tar -xf - -C "$OUT"
echo "report: $OUT/report.json"
exit $rc
