#!/usr/bin/env bash
# Usage: holdout_exam.sh [options] <tree> <name>
#
# The single release exam for 0.3.0b1 (docs/beta-bar.md, amendment 6): the
# sealed holdout-2 converted ONCE on the release candidate, in the canonical
# image (LibreOffice product lane) and the Word lane, and read as R1-R5.
#   (a) preflight   refuse a tree that is not a clean git checkout, a second exam
#                   (a results file exists, or the ledger records an exam; see
#                   --rerun-reason), other running containers; verify the
#                   manifest's SHA-256 and every PDF's; record the start
#   (b) sweeps      product + raw over the holdout PDFs, two containers at once
#                   (quality_sweep's own code, select() swapped: holdout_sweep.py),
#                   DOCX kept; the product container then runs every refused
#                   document through the real CLI and records its exit status
#   (c) Word        word_oracle over the product DOCX (holdout_word.py; the oracle
#                   takes its own Word lock: mutex + C:\lotmp\word.lock)
#   (d) exam        holdout_exam.py verdict: R1-R5, JSON + text, per-document table
#   (e) evidence    <tree>/docs/evidence/holdout2-<date>.json: the verdict, every
#                   input by path and SHA-256, the tree's commit as the host reads
#                   it (passed into the containers as EXACTDOC_GIT_COMMIT), the
#                   image id; the ledger records the exam as finished
#
# Options:
#   --dry-run            the 2-PDF SYNTHETIC set (holdout_dryset.py) under
#                        $EXACTDOC_DRY_DIR (default C:\lotmp\wp52\scratch\dry):
#                        every step for real, but its own manifest, state,
#                        ledger and evidence there; the sealed set and the tree's
#                        docs/evidence are never touched
#   --print              print every command, run none (preflight is reported)
#   --steps b,c,d,e      run only these steps (a always runs)
#   --rerun-reason TEXT  override the single-use refusal; logged in the ledger,
#                        the run log and the evidence
#   --docs-rows PATH     live Google Docs rows for R5 (gdsweep rows.jsonl), if flown
#   --jobs N             per sweep container (default 4; two containers)
#   --allow-busy         start beside other containers (written into the log)
#   --hold DIR           the sealed set (default C:\lotmp\rv_hold2; read-only)
#
# Environment: EXACTDOC_SCR (default C:\lotmp\scr; state under
# $SCR/runs/<name>.holdout2/, ledger $SCR/holdout2-exam.ledger.jsonl),
# EXACTDOC_PY (host Python), EXACTDOC_GATE_IMAGE (default exactdoc-gate:boot),
# EXACTDOC_WORD_TMP (default C:\lotmp\h2word: a short TEMP for the Word lane).
export MSYS_NO_PATHCONV=1
set -u

SEALED_SHA="4db48b08935795065af12016dd3c975eb37860e6299d101554cf61fde3460d61"
DRY=0; PRINT=0; STEPS="a,b,c,d,e"; RERUN=""; DOCS_ROWS=""; JOBS=4; ALLOW_BUSY=0
HOLD='C:\lotmp\rv_hold2'
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1; shift;;
    --print) PRINT=1; shift;;
    --steps) STEPS="a,$2"; shift 2;;
    --rerun-reason) RERUN="$2"; shift 2;;
    --docs-rows) DOCS_ROWS="$2"; shift 2;;
    --jobs) JOBS="$2"; shift 2;;
    --allow-busy) ALLOW_BUSY=1; shift;;
    --hold) HOLD="$2"; shift 2;;
    -h|--help) sed -n '2,45p' "$0"; exit 0;;
    -*) echo "unknown option $1" >&2; exit 2;;
    *) break;;
  esac
done
[ $# -eq 2 ] || { echo "usage: holdout_exam.sh [options] <tree> <name>" >&2; exit 2; }
TREE="$1"; NAME="$2"
# A Windows-native path (C:/...): MSYS_NO_PATHCONV hands /c/... to git.exe and
# the host Python unconverted, and neither understands it.
TREE="$(cd "$TREE" 2>/dev/null && (pwd -W 2>/dev/null || pwd))" || { echo "no such tree: $1" >&2; exit 2; }
HERE="$(cd "$(dirname "$0")" && (pwd -W 2>/dev/null || pwd))"
PY="${EXACTDOC_PY:-C:/Users/ebin/claude-ground/pdftodoc/.venv/Scripts/python.exe}"
IMAGE="${EXACTDOC_GATE_IMAGE:-exactdoc-gate:boot}"
WORD_TMP="${EXACTDOC_WORD_TMP:-C:\\lotmp\\h2word}"
if [ "$DRY" = 1 ]; then
  BASE="${EXACTDOC_DRY_DIR:-C:\\lotmp\\wp52\\scratch\\dry}"
  HOLD="$BASE/set"; SCR="$BASE"; EVDIR="$BASE/evidence"
else
  SCR="${EXACTDOC_SCR:-C:\\lotmp\\scr}"; EVDIR="$TREE/docs/evidence"
fi
STATE="$SCR/runs/$NAME.holdout2"
LEDGER="$SCR/holdout2-exam.ledger.jsonl"
MANIFEST="$HOLD/holdout2.json"
OURS="^exs-$NAME-h2(prod|raw)\$"
mkdir -p "$STATE"
LOG="$STATE/holdout_exam.log"

say() { echo "[holdout_exam $(date '+%H:%M:%S')] $*" | tee -a "$LOG"; }
want() { case ",$STEPS," in *,"$1",*) return 0;; esac; return 1; }
done_mark() { [ -f "$STATE/$1.done" ]; }
mark() { [ "$PRINT" = 1 ] || echo "$2" > "$STATE/$1.done"; }
hostpy() { ( cd "$TREE" && PYTHONPATH="$TREE" "$PY" "$@" ); }
run() {
  if [ "$1" = hostpy ]; then
    shift
    { printf '+ (cd %q && PYTHONPATH=%q %q' "$TREE" "$TREE" "$PY"; printf ' %q' "$@"; printf ')\n'; } | tee -a "$LOG"
    [ "$PRINT" = 1 ] && return 0
    hostpy "$@"; return $?
  fi
  { printf '+'; printf ' %q' "$@"; printf '\n'; } | tee -a "$LOG"
  [ "$PRINT" = 1 ] && return 0
  "$@"
}
others() { docker ps --format '{{.Names}}' 2>/dev/null | grep -Ev "$OURS" || true; }
refuse() { say "(a) REFUSED: $*"; [ "$PRINT" = 1 ] || exit "${RC:-10}"; }

say "exam $NAME on $TREE (dry-run=$DRY, print=$PRINT, steps=$STEPS, set=$HOLD)"
[ "$DRY" = 1 ] && say "*** DRY RUN on the SYNTHETIC 2-PDF set: plumbing only, not the exam ***"
[ -n "$RERUN" ] && say "RERUN REASON (logged): $RERUN"

# (a) preflight -------------------------------------------------------------------
COMMIT="$(git -C "$TREE" rev-parse HEAD 2>/dev/null)"
DIRTY="$(git -C "$TREE" status --porcelain 2>/dev/null)"
SCRIPTS_COMMIT="$(git -C "$HERE" rev-parse HEAD 2>/dev/null)"
say "(a) tree $TREE at ${COMMIT:-<not a git tree>}; exam scripts at ${SCRIPTS_COMMIT:-?} ($HERE)"
[ -n "$COMMIT" ] || RC=10 refuse "$TREE is not a git checkout (the exam must name a commit)"
if [ -n "$DIRTY" ]; then
  say "(a) the tree is dirty:"; echo "$DIRTY" | sed 's/^/      /' | tee -a "$LOG"
  RC=11 refuse "a dirty tree is not the frozen commit"
fi
if [ -f "$STATE/commit" ] && [ "$(cat "$STATE/commit")" != "$COMMIT" ]; then
  RC=13 refuse "$STATE was started on $(cat "$STATE/commit"), the tree is now $COMMIT"
fi
OTHERS="$(others)"
if [ -n "$OTHERS" ]; then
  say "(a) containers that are not this exam's are running: $(echo $OTHERS)"
  if [ "$ALLOW_BUSY" = 1 ]; then say "(a) ALLOWED BY FLAG (--allow-busy)"; else RC=12 refuse "other containers"; fi
fi
if [ "$DRY" = 1 ] && [ ! -f "$MANIFEST" ]; then
  say "(a) generating the synthetic set: $HOLD"
  run hostpy "$HERE/holdout_dryset.py" "$HOLD" || RC=14 refuse "could not build the synthetic set"
fi
if [ "$DRY" = 1 ]; then
  WANT_SHA="$(cut -d' ' -f1 "$HOLD/holdout2.sha256" 2>/dev/null)"
else
  WANT_SHA="$SEALED_SHA"
fi
run hostpy "$HERE/holdout_exam.py" verify-manifest "$MANIFEST" --sha256 "$WANT_SHA" --pdfs "$HOLD/pdfs" \
  || RC=15 refuse "the manifest or a PDF is not the sealed one"
G_ARGS=(--ledger "$LEDGER" --evidence-dir "$EVDIR" --run "$NAME" --commit "$COMMIT")
[ -n "$RERUN" ] && G_ARGS+=(--rerun-reason "$RERUN")
[ "$PRINT" = 1 ] || G_ARGS+=(--record)
run hostpy "$HERE/holdout_exam.py" guard "${G_ARGS[@]}" || RC=16 refuse "the exam is single-use"
IMAGE_ID="$(docker image inspect -f '{{.Id}}' "$IMAGE" 2>/dev/null)"
[ -n "$IMAGE_ID" ] || RC=17 refuse "image $IMAGE not found"
say "(a) image $IMAGE $IMAGE_ID"
[ "$PRINT" = 1 ] || echo "$COMMIT" > "$STATE/commit"
for c in $(docker ps -a --format '{{.Names}}' 2>/dev/null | grep -E "$OURS"); do
  say "(a) this exam's container from an interrupted run is removed: $c"; run docker rm -f "$c"
done

# (b) sweeps ----------------------------------------------------------------------
sweep_ok() { [ -f "$STATE/$1.sweep.json" ] && grep -q '^RC=0' "$STATE/$1.sweep.log" 2>/dev/null; }
one_sweep() {   # one_sweep prod|raw
  local lane="$1" prof C rc cli_env=""
  prof=$([ "$lane" = prod ] && echo product || echo raw)
  C="exs-$NAME-h2$lane"
  [ "$lane" = prod ] && cli_env="-e HOLD_CLI_EXITS=/work/cli_exits.json"
  local PROV="-e EXACTDOC_GIT_COMMIT=$COMMIT -e EXACTDOC_GIT_DIRTY=0 -e EXACTDOC_GIT_BRANCH=HEAD -e EXACTDOC_GATE_IMAGE_ID=$IMAGE_ID -e EXACTDOC_GATE_IMAGE_REF=$IMAGE"
  docker rm -f "$C" >/dev/null 2>&1
  docker run -d --name "$C" -w /work "$IMAGE" sleep infinity >/dev/null || return 99
  ( cd "$TREE" && tar --exclude=./.git --exclude=./.venv --exclude=./.scratch --exclude='*.pyc' \
      --exclude=__pycache__ --exclude=./testkit/batch --exclude=./testkit/sweep -cf - . ) \
    | docker exec -i "$C" tar -xf - -C /work
  docker exec "$C" mkdir -p /hold
  ( cd "$HOLD" && tar -cf - pdfs holdout2.json ) | docker exec -i "$C" tar -xf - -C /hold
  docker cp "$HERE/holdout_sweep.py" "$C:/opt/holdout_sweep.py" >/dev/null
  docker exec -e FONTCONFIG_FILE=/work/scripts/fonts.conf -e HOLD_DIR=/hold \
      -e HOLD_MANIFEST=/hold/holdout2.json $cli_env $PROV "$C" bash -c \
      "cd /work && /work/.venv/bin/python -I /opt/holdout_sweep.py --json /work/sweep.json --profile $prof --jobs $JOBS" \
      > "$STATE/$lane.sweep.log" 2>&1
  rc=$?
  docker cp "$C:/work/sweep.json" "$STATE/$lane.sweep.json" >/dev/null 2>&1
  [ "$lane" = prod ] && docker cp "$C:/work/cli_exits.json" "$STATE/cli_exits.json" >/dev/null 2>&1
  mkdir -p "$STATE/$lane.docx"; docker cp "$C:/work/testkit/sweep/." "$STATE/$lane.docx/" >/dev/null 2>&1
  docker rm -f "$C" >/dev/null 2>&1
  { echo "IMAGE=$IMAGE $IMAGE_ID"; echo "COMMIT=$COMMIT DIRTY=0"; echo "RC=$rc"; } >> "$STATE/$lane.sweep.log"
  return $rc
}
if want b; then
  if done_mark b; then say "(b) sweeps: done"; else
    pids=""
    for lane in prod raw; do
      if sweep_ok "$lane"; then say "(b) $lane sweep: done"; continue; fi
      say "(b) $lane sweep -> $STATE/$lane.sweep.json (container exs-$NAME-h2$lane, --jobs $JOBS)"
      if [ "$PRINT" = 1 ]; then
        echo "+ one_sweep $lane  # docker run $IMAGE; tree + $HOLD/{pdfs,holdout2.json} copied in; python -I /opt/holdout_sweep.py --json /work/sweep.json --profile $([ $lane = prod ] && echo product || echo raw) --jobs $JOBS" | tee -a "$LOG"
      else
        one_sweep "$lane" & pids="$pids $!"
      fi
    done
    for p in $pids; do wait "$p"; done
    if [ "$PRINT" = 0 ]; then
      # quality_sweep exits 2 when a row is an error: that is a finding (R1), not a
      # failed step, so only a missing payload stops the exam here.
      for lane in prod raw; do
        [ -f "$STATE/$lane.sweep.json" ] || { say "(b) $lane sweep wrote no payload: $STATE/$lane.sweep.log"; exit 30; }
        say "(b) $lane: $(grep -E '^RC=' "$STATE/$lane.sweep.log" | tail -1); $(grep -c ' done ' "$STATE/$lane.sweep.log") documents"
      done
      [ -f "$STATE/cli_exits.json" ] || { say "(b) no CLI exit record from the product container"; exit 31; }
      mark b "ok"
    fi
  fi
fi

# (c) Word ------------------------------------------------------------------------
if want c; then
  if done_mark c; then say "(c) Word: done"; else
    say "(c) Word over the product DOCX -> $STATE/word-prod/rows.jsonl (word_oracle takes its own lock)"
    if [ "$PRINT" = 1 ]; then
      echo "+ EXACTDOC_WORD_TMP=$WORD_TMP" | tee -a "$LOG"
    fi
    run env EXACTDOC_WORD_TMP="$WORD_TMP" bash -c 'cd "$0" && PYTHONPATH="$0" "$1" "${@:2}"' "$TREE" "$PY" \
        "$HERE/holdout_word.py" --manifest "$MANIFEST" --pdfs "$HOLD/pdfs" --tree "$TREE" -- \
        sweep "$STATE/word-prod" --docx-dir "$STATE/prod.docx/product" --lane product
    rc=$?
    if [ "$PRINT" = 0 ]; then
      [ $rc -eq 0 ] && [ -f "$STATE/word-prod/rows.jsonl" ] || { say "(c) Word lane FAILED rc=$rc"; exit 40; }
      mark c "ok"
    fi
  fi
fi

# (d) exam ------------------------------------------------------------------------
if want d; then
  V_ARGS=(--manifest "$MANIFEST" --manifest-sha256 "$WANT_SHA" --product "$STATE/prod.sweep.json"
          --raw "$STATE/raw.sweep.json" --word "$STATE/word-prod/rows.jsonl"
          --cli-exits "$STATE/cli_exits.json" --commit "$COMMIT" --tree "$TREE"
          --json "$STATE/exam.json" --text "$STATE/exam.txt")
  [ -n "$DOCS_ROWS" ] && V_ARGS+=(--docs "$DOCS_ROWS")
  say "(d) exam -> $STATE/exam.json, $STATE/exam.txt"
  run hostpy "$HERE/holdout_exam.py" verdict "${V_ARGS[@]}"
  rc=$?
  [ "$PRINT" = 1 ] || say "(d) holdout_exam exit $rc (0 announce yes, 1 announce no, 3 invalid)"
  [ "$PRINT" = 1 ] || [ $rc -ne 3 ] || { say "(d) INVALID exam: no evidence is written"; exit 50; }
  mark d "rc=$rc"
fi

# (e) evidence --------------------------------------------------------------------
if want e; then
  DATE="$(date +%Y-%m-%d)"
  OUTB="$EVDIR/holdout2-$DATE"
  [ "$DRY" = 1 ] && OUTB="$EVDIR/holdout2-dry-$NAME-$DATE"
  OUTJ="$OUTB.json"; n=2      # a results file is never overwritten
  while [ -e "$OUTJ" ]; do OUTJ="$OUTB-rerun$n.json"; n=$((n+1)); done
  W_ARGS=(--exam "$STATE/exam.json" --text "$STATE/exam.txt" --run "$NAME" --commit "$COMMIT"
          --scripts-commit "$SCRIPTS_COMMIT" --image-ref "$IMAGE" --image-id "$IMAGE_ID"
          --input "manifest=$MANIFEST" --input "product_sweep=$STATE/prod.sweep.json"
          --input "raw_sweep=$STATE/raw.sweep.json" --input "word_rows=$STATE/word-prod/rows.jsonl"
          --input "cli_exits=$STATE/cli_exits.json" --input "product_sweep_log=$STATE/prod.sweep.log"
          --input "raw_sweep_log=$STATE/raw.sweep.log"
          --input "holdout_exam.py=$HERE/holdout_exam.py" --input "holdout_sweep.py=$HERE/holdout_sweep.py"
          --input "holdout_word.py=$HERE/holdout_word.py" --input "holdout_exam.sh=$HERE/holdout_exam.sh")
  [ -n "$DOCS_ROWS" ] && W_ARGS+=(--input "docs_rows=$DOCS_ROWS")
  [ -n "$RERUN" ] && W_ARGS+=(--rerun-reason "$RERUN")
  say "(e) evidence -> $OUTJ"
  run hostpy "$HERE/holdout_exam.py" wrap "$OUTJ" "${W_ARGS[@]}" || { say "(e) writing the evidence failed"; exit 60; }
  run hostpy "$HERE/holdout_exam.py" finish --ledger "$LEDGER" --run "$NAME" --commit "$COMMIT" --evidence "$OUTJ"
  mark e "$OUTJ"
  [ "$PRINT" = 1 ] || { echo; cat "$STATE/exam.txt" | sed -n '1,/^announce:/p' | tee -a "$LOG"; }
fi
say "finished (state $STATE)"
