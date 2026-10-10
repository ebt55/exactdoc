#!/usr/bin/env bash
# Usage: final_set.sh [options] <tree> <name>
#
# The final 24-hour measurement set for the beta scorecard, in order, resumable
# (re-run the same command and finished steps are skipped):
#   (a) preflight   refuse a dirty tree, or any container that is not this run's
#   (b) gate        gate_full.sh, strict (EXACTDOC_GATE_ALLOW_STALE_BASELINE unset)
#   (c) sweeps      product + raw, both corpora, KEEP_DOCX, two containers at once
#   (d) Word        word_oracle sweep on the product and on the raw DOCX
#   (e) Docs        prints the live Docs command (uploads are the coordinator's)
#   (f) timing      quiet machine (no other container, host CPU < 20% for 60 s),
#                   then serial timing of the documents criterion 2 needs,
#                   the machine load recorded with each
#   (g) scorecard   beta_readiness with every input, the accepted sweep by path
#                   and SHA-256, --release; JSON + text into
#                   <tree>/docs/evidence/beta-readiness-<date>.json
#
# Options:
#   --dry-run           print every command, run nothing (preflight is reported,
#                       not enforced)
#   --only "a b c"      a corpus subset (document names) for sweeps, Word, timing;
#                       the gate always runs the gated 16
#   --steps b,c,d       run only these steps (default a,b,c,d,e,f,g); a is always run
#   --accepted PATH     the accepted product sweep (required for g)
#   --docs-rows PATH    the live Docs rows (default <runs>/<name>.gdocs/rows.jsonl)
#   --no-docs           let (g) run without a finished Docs lane (testing only)
#   --keep-going        continue after a failed gate (it is still reported)
#   --release V         default 0.3.0b1
#   --frac F            (f) time documents whose sweep time is >= F of their limit
#                       (default 0.4; sweeps run 1.4-2.3x a lone conversion, WP20b)
#
# Environment: EXACTDOC_SCR (default C:\lotmp\scr; runs under $SCR/runs),
# EXACTDOC_PY (host Python, default the shared venv), EXACTDOC_GATE_IMAGE
# (default exactdoc-gate:boot). State: $SCR/runs/<name>.final/ (one marker per
# finished step, final_set.log with every command run).
export MSYS_NO_PATHCONV=1
set -u

DRY=0; ONLY=""; STEPS="a,b,c,d,e,f,g"; ACCEPTED=""; DOCS_ROWS=""; NO_DOCS=0
KEEP_GOING=0; RELEASE="0.3.0b1"; FRAC="0.4"
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1; shift;;
    --only) ONLY="$2"; shift 2;;
    --steps) STEPS="a,$2"; shift 2;;
    --accepted) ACCEPTED="$2"; shift 2;;
    --docs-rows) DOCS_ROWS="$2"; shift 2;;
    --no-docs) NO_DOCS=1; shift;;
    --keep-going) KEEP_GOING=1; shift;;
    --release) RELEASE="$2"; shift 2;;
    --frac) FRAC="$2"; shift 2;;
    -h|--help) sed -n '2,40p' "$0"; exit 0;;
    -*) echo "unknown option $1" >&2; exit 2;;
    *) break;;
  esac
done
[ $# -eq 2 ] || { echo "usage: final_set.sh [options] <tree> <name>" >&2; exit 2; }
TREE="$1"; NAME="$2"
HERE="$(cd "$(dirname "$0")" && pwd)"
SCR="${EXACTDOC_SCR:-C:\\lotmp\\scr}"
RUNS="$SCR/runs"
STATE="$RUNS/$NAME.final"
PY="${EXACTDOC_PY:-C:/Users/ebin/claude-ground/pdftodoc/.venv/Scripts/python.exe}"
IMAGE="${EXACTDOC_GATE_IMAGE:-exactdoc-gate:boot}"
OURS="^(exs-$NAME-(prod|raw)|exg-$NAME-gate|exf-$NAME-serial)\$"
SERIAL_C="exf-$NAME-serial"
mkdir -p "$STATE"
LOG="$STATE/final_set.log"

say() { echo "[final_set $(date '+%H:%M:%S')] $*" | tee -a "$LOG"; }
want() { case ",$STEPS," in *,"$1",*) return 0;; esac; return 1; }
done_mark() { [ -f "$STATE/$1.done" ]; }
mark() { [ "$DRY" = 1 ] || echo "$2" > "$STATE/$1.done"; }
# run CMD...: print it; execute unless --dry-run
run() {
  echo "+ $*" | tee -a "$LOG"
  [ "$DRY" = 1 ] && return 0
  "$@"
}
hostpy() { ( cd "$TREE" && PYTHONPATH="$TREE" "$PY" "$@" ); }
host_cpu() {
  powershell.exe -NoProfile -Command \
    "[int](Get-CimInstance Win32_Processor | Measure-Object LoadPercentage -Average).Average" \
    2>/dev/null | tr -d '\r'
}
others() { docker ps --format '{{.Names}}' 2>/dev/null | grep -Ev "$OURS" || true; }
only_args() { [ -n "$ONLY" ] && echo "--only $ONLY"; }

say "run $NAME on $TREE (dry-run=$DRY, steps=$STEPS, only=${ONLY:-all})"

# (a) preflight ----------------------------------------------------------------
COMMIT="$(git -C "$TREE" rev-parse HEAD 2>/dev/null)"
DIRTY="$(git -C "$TREE" status --porcelain 2>/dev/null)"
OTHERS="$(others)"
STALE="$(docker ps -a --format '{{.Names}}' 2>/dev/null | grep -E "$OURS" || true)"
say "(a) tree $TREE at ${COMMIT:-<not a git tree>}"
if [ -z "$COMMIT" ]; then
  say "(a) REFUSED: $TREE is not a git checkout (the run must name a commit)"; [ "$DRY" = 1 ] || exit 10
fi
if [ -n "$DIRTY" ]; then
  say "(a) REFUSED: the tree is dirty:"; echo "$DIRTY" | sed 's/^/      /' | tee -a "$LOG"
  [ "$DRY" = 1 ] || exit 11
fi
if [ -n "$OTHERS" ]; then
  say "(a) REFUSED: containers that are not this run's are running:"
  echo "$OTHERS" | sed 's/^/      /' | tee -a "$LOG"
  [ "$DRY" = 1 ] || exit 12
fi
if [ -f "$STATE/commit" ] && [ "$(cat "$STATE/commit")" != "$COMMIT" ] && [ "$DRY" = 0 ]; then
  say "(a) REFUSED: $STATE was started on $(cat "$STATE/commit"), the tree is now $COMMIT;"
  say "    use a new run name"; exit 13
fi
[ "$DRY" = 1 ] || echo "$COMMIT" > "$STATE/commit"
if [ -n "$STALE" ]; then
  say "(a) this run's containers from an interrupted run are removed: $(echo $STALE)"
  for c in $STALE; do run docker rm -f "$c"; done
fi

# (b) gate -----------------------------------------------------------------------
if want b; then
  if done_mark b; then say "(b) gate: done ($(cat "$STATE/b.done"))"; else
    say "(b) gate (strict): $RUNS/$NAME-gate.log"
    run env -u EXACTDOC_GATE_ALLOW_STALE_BASELINE EXACTDOC_SCR="$SCR" \
        bash "$HERE/gate_full.sh" "$NAME-gate" "$TREE"
    rc=$?
    if [ "$DRY" = 0 ]; then
      tests="$(grep -E '^Ran [0-9]+ tests' "$RUNS/$NAME-gate.log" | tail -1)"
      ok="$(grep -E '^(OK|FAILED)' "$RUNS/$NAME-gate.log" | tail -1)"
      lanes="$(grep -E '^lane ' "$RUNS/$NAME-gate.log" | tr -s ' ' | paste -sd ';' -)"
      say "(b) $tests $ok; $(grep -E '^FAILED_STEPS=' "$RUNS/$NAME-gate.log" | tail -1); $lanes"
      if [ $rc -ne 0 ]; then
        say "(b) GATE FAILED ($rc step(s)); see $RUNS/$NAME-gate.log"
        [ "$KEEP_GOING" = 1 ] || exit 20
        mark b "FAILED rc=$rc"
      else
        mark b "PASS"
      fi
    fi
  fi
fi

# (c) sweeps ---------------------------------------------------------------------
sweep_ok() { [ -f "$RUNS/$1.sweep.json" ] && grep -q '^RC=0' "$RUNS/$1.sweep.log" 2>/dev/null; }
if want c; then
  if done_mark c; then say "(c) sweeps: done"; else
    pids=""
    for lane in prod raw; do
      prof=$([ $lane = prod ] && echo product || echo raw)
      if sweep_ok "$NAME-$lane"; then say "(c) $prof sweep: done"; continue; fi
      say "(c) $prof sweep: $RUNS/$NAME-$lane.sweep.json"
      if [ "$DRY" = 1 ]; then
        run env KEEP_DOCX=1 EXACTDOC_SCR="$SCR" bash "$HERE/sweep.sh" "$NAME-$lane" "$TREE" \
            --corpus both --jobs 4 --profile $prof $(only_args)
      else
        echo "+ env KEEP_DOCX=1 EXACTDOC_SCR=$SCR bash $HERE/sweep.sh $NAME-$lane $TREE --corpus both --jobs 4 --profile $prof $(only_args) &" | tee -a "$LOG"
        KEEP_DOCX=1 EXACTDOC_SCR="$SCR" bash "$HERE/sweep.sh" "$NAME-$lane" "$TREE" \
            --corpus both --jobs 4 --profile $prof $(only_args) &
        pids="$pids $!"
      fi
    done
    for p in $pids; do wait "$p"; done
    if [ "$DRY" = 0 ]; then
      for lane in prod raw; do
        sweep_ok "$NAME-$lane" || { say "(c) $lane sweep FAILED: $RUNS/$NAME-$lane.sweep.log"; exit 30; }
        bad="$(hostpy -c "import json,sys; d=json.load(open(sys.argv[1])); print(' '.join(r['document'] for r in d['documents'] if r.get('error') or not r.get('out_pages')))" "$RUNS/$NAME-$lane.sweep.json")"
        say "(c) $lane: $(grep -c ' done ' "$RUNS/$NAME-$lane.sweep.log") documents; error/unmeasured rows: ${bad:-none}"
      done
      mark c "ok"
    fi
  fi
fi

# (d) Word ------------------------------------------------------------------------
if want d; then
  if done_mark d; then say "(d) Word: done"; else
    for lane in prod raw; do
      prof=$([ $lane = prod ] && echo product || echo raw)
      say "(d) Word, $prof DOCX: $RUNS/$NAME-word-$lane/rows.jsonl (word_oracle holds its own Word lock)"
      run hostpy testkit/word_oracle.py sweep "$RUNS/$NAME-word-$lane" \
          --docx-dir "$RUNS/$NAME-$lane.docx/$prof" --lane $prof $(only_args)
      rc=$?
      [ "$DRY" = 1 ] || [ $rc -eq 0 ] || { say "(d) Word $prof FAILED rc=$rc"; exit 40; }
    done
    mark d "ok"
  fi
fi

# (e) Docs (the coordinator runs it) ----------------------------------------------
GDROWS="${DOCS_ROWS:-$RUNS/$NAME.gdocs/rows.jsonl}"
if want e; then
  ONLY_GD=""; [ -n "$ONLY" ] && ONLY_GD="--only $(echo $ONLY | tr ' ' ',')"
  say "(e) live Google Docs sweep -- uploads; the coordinator runs it, with the Google credentials:"
  say "      EXACTDOC_ROOT=$TREE EXACTDOC_GDOCS_CREDENTIALS=... EXACTDOC_GDOCS_TOKEN=... \\"
  say "        $PY $HERE/gdsweep.py $(dirname "$GDROWS") --corpus both $ONLY_GD"
  say "      (it flies the drift sentinel first: check it with"
  say "       $PY $TREE/testkit/docs_sentinel.py check $GDROWS)"
fi

# (f) quiet serial timing ----------------------------------------------------------
wait_quiet() {   # no other container and host CPU < 20% for 60 s (12 samples, 5 s apart)
  local good=0 waited=0 cpu n deadline=$(( $(date +%s) + ${EXACTDOC_QUIET_WAIT_S:-21600} ))
  while [ $good -lt 12 ]; do
    [ $(date +%s) -gt $deadline ] && { say "(f) the machine never went quiet"; return 1; }
    n="$(others | grep -cv "^$SERIAL_C\$" || true)"; cpu="$(host_cpu)"
    if [ "${n:-0}" -eq 0 ] && [ -n "$cpu" ] && [ "$cpu" -lt 20 ]; then good=$((good+1)); else
      good=0; waited=$((waited+1))
      [ $((waited % 12)) -eq 1 ] && say "(f) waiting for quiet: $n other container(s), host CPU ${cpu:-?}%"
    fi
    sleep 5
  done
}
load_json() { echo "{\"host_cpu_pct\": ${1:-null}, \"other_containers\": ${2:-0}, \"utc\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}"; }
if want f; then
  if done_mark f; then say "(f) timing: done"; else
    TDIR="$STATE/timing"; mkdir -p "$TDIR"
    for lane in prod raw; do
      prof=$([ $lane = prod ] && echo product || echo raw)
      if [ "$DRY" = 1 ]; then
        echo "+ hostpy $HERE/final_set_helpers.py pick $RUNS/$NAME-$lane.sweep.json --tree $TREE --frac $FRAC $( [ -n "$ONLY" ] && echo --only $ONLY )" | tee -a "$LOG"
        docs="<picked-$prof-document>"
      else
        docs="$(hostpy "$HERE/final_set_helpers.py" pick "$RUNS/$NAME-$lane.sweep.json" --tree "$TREE" --frac "$FRAC" $( [ -n "$ONLY" ] && echo --only $ONLY ) | tr -d '\r')"
      fi
      echo "$docs" > "$TDIR/$lane.docs"
      say "(f) $prof: $(echo $docs | wc -w) document(s) to time serially: $(echo $docs)"
    done
    if [ "$DRY" = 0 ]; then
      docker rm -f "$SERIAL_C" >/dev/null 2>&1
      docker run -d --name "$SERIAL_C" -w /work "$IMAGE" sleep infinity >/dev/null || exit 50
      ( cd "$TREE" && tar --exclude=./.git --exclude=./.venv --exclude=./.scratch --exclude='*.pyc' \
          --exclude=__pycache__ --exclude=./testkit/batch --exclude=./testkit/sweep -cf - . ) \
        | docker exec -i "$SERIAL_C" tar -xf - -C /work
      docker exec "$SERIAL_C" mkdir -p /work/t
    else
      run docker run -d --name "$SERIAL_C" -w /work "$IMAGE" sleep infinity
    fi
    for lane in prod raw; do
      prof=$([ $lane = prod ] && echo product || echo raw)
      for doc in $(cat "$TDIR/$lane.docs"); do
        stem="${doc%.pdf}"; part="$TDIR/$prof-$stem.json"
        [ -f "$part" ] && continue
        if [ "$DRY" = 1 ]; then
          say "(f) wait for quiet (no other container, CPU < 20% for 60 s), sample the load, then:"
          run docker exec -e FONTCONFIG_FILE=/work/scripts/fonts.conf "$SERIAL_C" bash -c \
              "cd /work && /work/.venv/bin/python testkit/serial_timing.py --profile $prof --docs $doc --json /work/t/$prof-$stem.json"
          continue
        fi
        wait_quiet || exit 51
        before_cpu="$(host_cpu)"; before_n="$(others | grep -cv "^$SERIAL_C\$" || true)"
        docker exec -e FONTCONFIG_FILE=/work/scripts/fonts.conf "$SERIAL_C" bash -c \
          "cd /work && /work/.venv/bin/python testkit/serial_timing.py --profile $prof --docs $doc --json /work/t/$prof-$stem.json" \
          >> "$LOG" 2>&1 || { say "(f) $doc ($prof) failed"; exit 52; }
        after_cpu="$(host_cpu)"; after_n="$(others | grep -cv "^$SERIAL_C\$" || true)"
        docker cp "$SERIAL_C:/work/t/$prof-$stem.json" "$part" >/dev/null
        echo "{\"before\": $(load_json "$before_cpu" "$before_n"), \"after\": $(load_json "$after_cpu" "$after_n")}" \
          > "$TDIR/$prof-$stem.load.json"
        say "(f) $prof $doc timed (CPU before ${before_cpu}% after ${after_cpu}%)"
      done
      parts="$(ls "$TDIR"/$prof-*.json 2>/dev/null | grep -v '\.load\.json$')"
      if [ -n "$parts" ]; then
        run hostpy "$HERE/final_set_helpers.py" merge $prof "$RUNS/$NAME-$prof-serial.timing.json" $parts \
            --quiet-rule "no other container and host CPU < 20% for 60 s before each document"
      elif [ "$DRY" = 0 ]; then
        say "(f) $prof: nothing to time serially"
      fi
    done
    run docker rm -f "$SERIAL_C"
    mark f "ok"
  fi
fi

# (g) scorecard ---------------------------------------------------------------------
if want g; then
  [ -n "$ACCEPTED" ] || { say "(g) --accepted <accepted product sweep> is required"; exit 60; }
  if [ "$DRY" = 0 ] && [ "$NO_DOCS" = 0 ]; then
    hostpy "$HERE/final_set_helpers.py" docs-done "$GDROWS" --sweep "$RUNS/$NAME-prod.sweep.json" | tee -a "$LOG"
    [ "${PIPESTATUS[0]}" -eq 0 ] || { say "(g) the Docs lane is not finished: run (e), then re-run this command"; exit 61; }
  fi
  DATE="$(date +%Y-%m-%d)"
  OUTJ="$TREE/docs/evidence/beta-readiness-$DATE.json"
  TMPJ="$STATE/readiness.json"; TMPT="$STATE/readiness.txt"
  T_ARGS=""
  for prof in product raw; do
    [ -f "$RUNS/$NAME-$prof-serial.timing.json" ] && T_ARGS="$T_ARGS --timing $RUNS/$NAME-$prof-serial.timing.json"
  done
  G_ARGS=""; [ "$NO_DOCS" = 1 ] && [ ! -f "$GDROWS" ] || G_ARGS="--gdocs $GDROWS"
  say "(g) scorecard -> $OUTJ (accepted $ACCEPTED, release $RELEASE)"
  if [ "$DRY" = 1 ]; then
    run hostpy testkit/beta_readiness.py --raw "$RUNS/$NAME-raw.sweep.json" --product "$RUNS/$NAME-prod.sweep.json" \
        $G_ARGS --word "$RUNS/$NAME-word-prod/rows.jsonl" --gate "$RUNS/$NAME-gate.batch" \
        --accepted "$ACCEPTED" --docx-dir "$RUNS/$NAME-prod.docx" $T_ARGS --release "$RELEASE" --all --json "$TMPJ"
  else
    echo "+ beta_readiness ... --json $TMPJ > $TMPT" >> "$LOG"
    hostpy testkit/beta_readiness.py --raw "$RUNS/$NAME-raw.sweep.json" --product "$RUNS/$NAME-prod.sweep.json" \
        $G_ARGS --word "$RUNS/$NAME-word-prod/rows.jsonl" --gate "$RUNS/$NAME-gate.batch" \
        --accepted "$ACCEPTED" --docx-dir "$RUNS/$NAME-prod.docx" $T_ARGS --release "$RELEASE" --all \
        --json "$TMPJ" > "$TMPT" 2>&1
    say "(g) beta_readiness exit $? ($(grep -E '^verdict' "$TMPT" | head -1))"
  fi
  run hostpy "$HERE/final_set_helpers.py" wrap "$OUTJ" --readiness "$TMPJ" --text "$TMPT" \
      --accepted "$ACCEPTED" --run "$NAME" --commit "$COMMIT" --release "$RELEASE" \
      --input "raw=$RUNS/$NAME-raw.sweep.json" --input "product=$RUNS/$NAME-prod.sweep.json" \
      --input "gdocs=$GDROWS" --input "word_product=$RUNS/$NAME-word-prod/rows.jsonl" \
      --input "word_raw=$RUNS/$NAME-word-raw/rows.jsonl" --input "gate=$RUNS/$NAME-gate.log" \
      --input "timing_product=$RUNS/$NAME-product-serial.timing.json" \
      --input "timing_raw=$RUNS/$NAME-raw-serial.timing.json"
  mark g "ok"
fi
say "finished (state $STATE)"
