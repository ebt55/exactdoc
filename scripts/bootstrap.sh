#!/usr/bin/env bash
# Provision a Linux machine to run exactdoc's measurement harness.
#
# The harness is this project's real product, and until now its dependencies
# were folklore: LibreOffice, headless Chromium and the metric-compatible font
# families are all required, none of them was declared anywhere, and the corpus
# generator crashed rather than said so. An executor who cannot run the gate is
# flying blind, and a gate that cannot run looks exactly like a gate that
# passes -- this repository has already paid for that lesson once
# (docs/deep-dive/status.md §5).
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

# The Office metric clones (WP31, owner-approved 2026-10-06). The standard
# profile writes Calibri and Cambria by name; without Carlito and Caladea the
# renderer draws both in FreeSerif and every such paragraph re-wraps.
#
# Not the distribution's current packages: noble's fonts-crosextra-caladea
# (20200211) has proportional figures where Cambria's are tabular -- 135+ of
# ~216 WinAnsi advances differ per face -- so it is not a metric clone. The
# original Crosextra releases are, and they are byte-identical to the files
# exactdoc/_clone_widths.py was generated from. Fetched from the Ubuntu pool by
# exact filename and refused unless every digest matches; the same block is in
# docker/gate.Dockerfile and docker/gate-carlito.Dockerfile.
CROSEXTRA=/usr/share/fonts/truetype/crosextra
CROSEXTRA_TTF_SHA256="b4ff23ba370cc95a3c349336b73f9c28514a1371210f89832efc85c4b1ea7131  Carlito-Regular.ttf
0f62ab34ad5d079a0a28fac01bcf7c7a724a4db4d6cb99cab9cabff382fbb80f  Carlito-Bold.ttf
718a0663864d37a4868220a19b9668a5fe10a46197f6df367b4c2c30c04c026c  Carlito-Italic.ttf
380764b6898d7b73ceae6384b2958b196d2a0428962ef3adf138d27947228666  Carlito-BoldItalic.ttf
d2f6cad33f191e65b68bd74e6d4f7708080a41b32db635866109df3090265d91  Caladea-Regular.ttf
74eda4fc5ffba0d8dc4aa76d41499f5ab76168d9ed6141c6417064c6244db9b6  Caladea-Bold.ttf
9c968bf60ba1e851cdfea77c71e3540c57792f77482dd241acc29d1425569c4e  Caladea-Italic.ttf
f47a35ad6cd0efa9914d93f9d03c93e30c55da43674bccfabac73b3c0d522c01  Caladea-BoldItalic.ttf"
crosextra_ok() {
  [ -d "$CROSEXTRA" ] && ( cd "$CROSEXTRA" && printf '%s\n' "$CROSEXTRA_TTF_SHA256" \
    | sha256sum -c - >/dev/null 2>&1 )
}
say "fonts (Carlito + Caladea, the pinned Crosextra builds)"
if crosextra_ok; then
  echo "already present"
elif [ "$REPORT_ONLY" -eq 0 ] && [ "$PKG" = apt ] && have curl; then
  POOL=http://archive.ubuntu.com/ubuntu/pool/universe/f
  T="$(mktemp -d)"
  ( cd "$T" \
    && curl -fsSLO "$POOL/fonts-crosextra-carlito/fonts-crosextra-carlito_20130920-1.1_all.deb" \
    && curl -fsSLO "$POOL/fonts-crosextra-caladea/fonts-crosextra-caladea_20130214-2.1_all.deb" \
    && printf '%s\n' \
      "7385475cde807e1363c3361976576571870373032466c7f525d5900852b6f420  fonts-crosextra-carlito_20130920-1.1_all.deb" \
      "1330d25dfa5bab2e9b712b4950d2855cdb63a2b2b9451e2ffb93618c77e1f242  fonts-crosextra-caladea_20130214-2.1_all.deb" \
      | sha256sum -c - \
    && $SUDO dpkg -i ./fonts-crosextra-carlito_20130920-1.1_all.deb \
                     ./fonts-crosextra-caladea_20130214-2.1_all.deb \
    && $SUDO apt-mark hold fonts-crosextra-carlito fonts-crosextra-caladea >/dev/null )
  rm -rf "$T"
  crosextra_ok && echo "installed and verified" \
    || echo "Carlito/Caladea NOT verified -- $CROSEXTRA does not hold the pinned files"
else
  echo "install the Crosextra Carlito 20130920 and Caladea 20130214 TTFs into"
  echo "$CROSEXTRA by hand (digests in scripts/bootstrap.sh)"
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
say "Python packages (converter + test harness + PyMuPDF reference backend)"
if [ "$REPORT_ONLY" -eq 0 ]; then
  if have uv; then
    # --frozen: uv.lock is the pinned truth, and gate.yml has said so in a comment
    # since before the flag was actually passed. Without it a resolve can move a
    # parser out from under backend-specific goldens and parity evidence; parser
    # versions are part of those records because their grouping can differ.
    #
    # PDFium ships in the core runtime. This environment additionally installs
    # the `mupdf` extra -- NOT because the product needs it, but because this is
    # the MEASUREMENT machine: backend parity compares the shipping parser
    # against the PyMuPDF reference arm, and it cannot do that with one arm
    # uninstalled. A user's install has no AGPL package in it; this one
    # deliberately does, and `tests/test_no_pymupdf.py` plus the base-wheel
    # proof are what keep the distinction honest. The cloud Google Docs oracle
    # is provisioned separately when requested.
    uv sync --frozen --extra test --extra mupdf
  else
    [ -d "$VENV" ] || python3 -m venv "$VENV"
    "$VENV/bin/pip" install --quiet --upgrade pip
    "$VENV/bin/pip" install --quiet -e ".[test,mupdf]"
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
# Informational, not counted as missing: a host without the clones still runs
# every check; its Calibri/Cambria text renders in FreeSerif, as before WP31.
if crosextra_ok; then status "carlito/caladea" "OK      pinned Crosextra builds"
else status "carlito/caladea" "absent  (Calibri/Cambria render as FreeSerif)"; fi
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
