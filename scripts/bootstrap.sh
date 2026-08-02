#!/usr/bin/env bash
# Provision a Linux machine to run exactdoc's measurement harness.
#
# The harness is this project's real product, and until now its dependencies
# were folklore: LibreOffice, headless Chromium and the metric-compatible font
# families are all required, none of them was declared anywhere, and the corpus
# generator crashed rather than said so. An executor who cannot run the gate is
# flying blind, and a gate that cannot run looks exactly like a gate that
# passes -- this repository has already paid for that lesson once (STATUS.md §5).
#
#   bash scripts/bootstrap.sh              provision, then report
#   bash scripts/bootstrap.sh --report     report only, change nothing
#   bash scripts/bootstrap.sh --strict     exit 1 if any capability is missing
#
# Idempotent: safe to re-run, installs only what is absent. Writes
# scripts/env.sh with the SOFFICE/CHROME paths it found; source it, or export
# them yourself. Nothing here ships in the wheel -- these are dev/CI oracles.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
VENV="$ROOT/.venv"
cd "$ROOT"

REPORT_ONLY=0
STRICT=0
for a in "$@"; do
  case "$a" in
    --report) REPORT_ONLY=1 ;;
    --strict) STRICT=1 ;;
    *) echo "unknown option: $a" >&2; exit 2 ;;
  esac
done

say()  { printf '\n=== %s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
  have sudo && SUDO="sudo"
fi

# --------------------------------------------------------------- package layer
PKG=""
if   have apt-get; then PKG=apt
elif have dnf;     then PKG=dnf
elif have apk;     then PKG=apk
fi

pkg_install() {
  [ "$REPORT_ONLY" -eq 1 ] && return 0
  [ -z "$PKG" ] && return 1
  case "$PKG" in
    apt) $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y \
           --no-install-recommends "$@" ;;
    dnf) $SUDO dnf install -y "$@" ;;
    apk) $SUDO apk add --no-cache "$@" ;;
  esac
}

if [ "$REPORT_ONLY" -eq 0 ] && [ "$PKG" = apt ]; then
  say "refreshing the package index"
  $SUDO env DEBIAN_FRONTEND=noninteractive apt-get update -qq || true
fi

# ------------------------------------------------------------ Python interpreter
# A stock container image has no python at all, so this cannot be assumed.
if ! have python3 && [ "$REPORT_ONLY" -eq 0 ]; then
  say "python3"
  case "$PKG" in
    apt) pkg_install python3 python3-venv python3-pip ca-certificates curl ;;
    dnf) pkg_install python3 python3-pip ca-certificates curl ;;
    apk) pkg_install python3 py3-pip ca-certificates curl ;;
  esac
fi

# ---------------------------------------------------------------------- fonts
# LibreOffice renders the DOCX we measure. Without metric-compatible families
# it substitutes something else, every line wraps differently, and the fidelity
# numbers move for a reason that has nothing to do with the converter.
# Latin metric compatibility is not enough: the corpus contains a CJK + Arabic +
# Hebrew document, and Liberation covers none of those scripts. Measured, after
# the corpus was already frozen byte-for-byte, c4_i18n still moved dy_p50
# 0.15pt -> 2.1pt between the measurement container and a GitHub runner, purely
# because the runner's larger font collection gave LibreOffice different faces to
# resolve those runs to. scripts/fonts.conf then restricts the renderer to
# exactly this set -- installing the right fonts is half the job, seeing no
# others is the other half.
say "fonts (Latin metrics + the CJK/RTL faces the i18n document needs)"
if have fc-list && [ -n "$(fc-list 2>/dev/null | grep -i 'wqy\|ipafont' | head -1)" ]; then
  echo "already present"
else
  case "$PKG" in
    apt) pkg_install fontconfig fonts-liberation fonts-dejavu-core \
           fonts-freefont-ttf fonts-wqy-zenhei fonts-ipafont-gothic ;;
    dnf) pkg_install fontconfig liberation-fonts dejavu-sans-fonts \
           dejavu-serif-fonts gnu-free-fonts-common wqy-zenhei-fonts \
           ipa-gothic-fonts ;;
    apk) pkg_install fontconfig font-liberation font-dejavu font-wqy-zenhei \
           font-ipa ;;
    *)   echo "no known package manager -- install Liberation, DejaVu, FreeFont, WenQuanYi and IPA by hand" ;;
  esac
  have fc-cache && [ "$REPORT_ONLY" -eq 0 ] && $SUDO fc-cache -f >/dev/null 2>&1
fi

# ----------------------------------------------------------------- LibreOffice
# The render-back oracle: --verify, --refine and the whole gate need it.
say "LibreOffice (the render-back oracle)"
find_soffice() {
  for c in "${SOFFICE:-}" /usr/bin/soffice /usr/lib/libreoffice/program/soffice \
           /opt/libreoffice*/program/soffice "$ROOT"/.tools/squashfs-root/opt/libreoffice*/program/soffice; do
    [ -n "$c" ] && [ -x "$c" ] && "$c" --version >/dev/null 2>&1 \
      && { echo "$c"; return 0; }
  done
  p="$(command -v soffice 2>/dev/null)" || return 1
  [ -n "$p" ] && "$p" --version >/dev/null 2>&1 && { echo "$p"; return 0; }
  return 1
}
SOFFICE_PATH="$(find_soffice || true)"
if [ -n "$SOFFICE_PATH" ]; then
  echo "already present: $SOFFICE_PATH"
else
  case "$PKG" in
    apt) pkg_install libreoffice-writer ;;
    apk) pkg_install libreoffice-writer ;;
    dnf) pkg_install libreoffice-writer || true ;;
  esac
  SOFFICE_PATH="$(find_soffice)"
fi
if [ -z "$SOFFICE_PATH" ] && [ "$REPORT_ONLY" -eq 0 ]; then
  # Fallback for distributions that do not package it (Amazon Linux 2023 does
  # not). The AppImage is extracted rather than mounted: no FUSE in containers.
  say "LibreOffice not packaged here -- extracting the AppImage"
  mkdir -p "$ROOT/.tools" && cd "$ROOT/.tools"
  if [ ! -d squashfs-root ]; then
    if have curl; then
      curl -fsSL -o lo.AppImage \
        https://appimages.libreitalia.org/LibreOffice-fresh.standard-x86_64.AppImage \
        && chmod +x lo.AppImage && ./lo.AppImage --appimage-extract >/dev/null
    else
      echo "curl not available; install LibreOffice by hand"
    fi
  fi
  cd "$ROOT"
  SOFFICE_PATH="$(find_soffice)"
fi

# ------------------------------------------------------------- Python packages
# uv when it is available (uv.lock is the pinned truth); otherwise a plain venv,
# because modern distributions mark the system interpreter externally-managed
# and `pip install -e .` into it simply refuses (PEP 668).
#
# This runs BEFORE Chromium on purpose: the no-root fallback for Chromium is a
# Playwright download, and Playwright needs somewhere to be installed.
say "Python packages (converter + test harness + PDFium candidate backend)"
if [ "$REPORT_ONLY" -eq 0 ]; then
  if have uv; then
    # --frozen: uv.lock is the pinned truth, and gate.yml has said so in a comment
    # since before the flag was actually passed. Without it a resolve can move a
    # parser out from under backend-specific goldens and parity evidence; parser
    # versions are part of those records because their grouping can differ.
    # PyMuPDF ships in the core runtime. The canonical gate, evidence capture and
    # backend-parity comparison additionally need the optional PDFium candidate;
    # the cloud Google Docs oracle is provisioned separately when requested.
    uv sync --frozen --extra test --extra pdfium
  else
    [ -d "$VENV" ] || python3 -m venv "$VENV"
    "$VENV/bin/pip" install --quiet --upgrade pip
    "$VENV/bin/pip" install --quiet -e ".[test,pdfium]"
  fi
fi

pyrun() {
  if   have uv;                then uv run python "$@"
  elif [ -x "$VENV/bin/python" ]; then "$VENV/bin/python" "$@"
  else python3 "$@"; fi
}
pyhas() { pyrun -c "import $1" >/dev/null 2>&1; }

# -------------------------------------------------------------------- Chromium
# Generates the Chromium/Skia half of the corpus (8 of 16 documents). Not
# needed to convert a PDF, only to build the corpus.
say "Chromium (generates the Chromium/Skia corpus documents)"
# Executable is not the same as working. Ubuntu's `chromium-browser` apt package
# is a snap shim: it installs, it is on PATH, it is executable, and every
# invocation exits 1 with "requires the chromium snap to be installed" -- which
# in a container is unreachable. Probing with --version is the difference
# between a capability report that is true and one that is merely optimistic.
find_chrome() {
  for c in "${CHROME:-}" /usr/bin/google-chrome /usr/bin/chromium \
           /usr/bin/chromium-browser \
           "$HOME"/.cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell; do
    [ -n "$c" ] && [ -x "$c" ] && "$c" --version >/dev/null 2>&1 \
      && { echo "$c"; return 0; }
  done
  for c in chromium google-chrome; do
    p="$(command -v $c 2>/dev/null)" || continue
    [ -n "$p" ] && "$p" --version >/dev/null 2>&1 && { echo "$p"; return 0; }
  done
  return 1
}
CHROME_PATH="$(find_chrome || true)"
if [ -n "$CHROME_PATH" ]; then
  echo "already present: $CHROME_PATH"
elif [ "$REPORT_ONLY" -eq 0 ]; then
  case "$PKG" in
    # Not apt: on Ubuntu both `chromium` and `chromium-browser` are snap shims.
    dnf) pkg_install chromium || true ;;
    apk) pkg_install chromium || true ;;
  esac
  CHROME_PATH="$(find_chrome || true)"
fi
if [ -z "$CHROME_PATH" ] && [ "$REPORT_ONLY" -eq 0 ]; then
  # Playwright's headless shell prints PDFs correctly and installs without root
  # -- the fallback used when the distribution ships Chromium only as a snap.
  say "no system Chromium -- trying Playwright's headless shell"
  # --with-deps because the downloaded shell links against system libraries
  # (libatk, libnss, ...) that a slim image does not carry: without them the
  # binary is present, executable, and exits 127 on every invocation.
  DEPS=""
  { [ "$(id -u)" -eq 0 ] || [ -n "$SUDO" ]; } && [ "$PKG" = apt ] && DEPS="--with-deps"
  if have uv; then
    uv pip install --quiet playwright \
      && uv run python -m playwright install $DEPS chromium --only-shell
  elif [ -x "$VENV/bin/python" ]; then
    "$VENV/bin/pip" install --quiet playwright \
      && "$VENV/bin/python" -m playwright install $DEPS chromium --only-shell
  fi
  CHROME_PATH="$(find_chrome || true)"
fi

# ----------------------------------------------------------------------- report
say "capability report"
status() { printf '  %-22s %s\n' "$1" "$2"; }
MISSING=0
mark() { if [ -n "$2" ]; then status "$1" "OK      $2"; else status "$1" "MISSING"; MISSING=$((MISSING+1)); fi; }

FONTS_OK=""
have fc-list && [ -n "$(fc-list 2>/dev/null | grep -i liberation | head -1)" ] && FONTS_OK="Liberation found"
mark "fonts"          "$FONTS_OK"
mark "soffice"        "$SOFFICE_PATH"
mark "chromium"       "$CHROME_PATH"
PYMUPDF_OK=""; pyhas fitz       && PYMUPDF_OK="importable"
PDFIUM_OK="";  pyhas pypdfium2  && PDFIUM_OK="importable"
RL_OK="";      pyhas reportlab  && RL_OK="importable"
mark "pymupdf"        "$PYMUPDF_OK"
mark "pypdfium2"      "$PDFIUM_OK"
mark "reportlab/fpdf2" "$RL_OK"

if [ "$REPORT_ONLY" -eq 0 ]; then
  mkdir -p /tmp/exactdoc-fontconfig
  {
    echo "# Written by scripts/bootstrap.sh -- source this before running the harness."
    [ -n "$SOFFICE_PATH" ] && echo "export SOFFICE=\"$SOFFICE_PATH\""
    [ -n "$CHROME_PATH" ]  && echo "export CHROME=\"$CHROME_PATH\""
    # The renderer must see exactly the pinned font set, wherever it runs.
    echo "export FONTCONFIG_FILE=\"$HERE/fonts.conf\""
  } > "$HERE/env.sh"
  status "wrote" "scripts/env.sh"
fi

cat <<EOF

next:
  source scripts/env.sh
  python testkit/gen_corpus.py testkit/adv && python corpus/make_corpus.py
  python testkit/golden_ir.py verify            # parser gate, needs no oracle
  python testkit/runall.py
  python testkit/backend_parity.py --profile candidate --measure          # unadjudicated discovery
  python testkit/backend_parity.py --profile candidate-refined --measure  # loop diagnostic
EOF

if [ "$MISSING" -gt 0 ]; then
  echo
  echo "$MISSING capability/capabilities missing -- the corpus and any number"
  echo "computed from it will be incomplete. See the report above."
  [ "$STRICT" -eq 1 ] && exit 1
fi
exit 0
