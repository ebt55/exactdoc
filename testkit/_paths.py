"""Shared path discovery for the testkit (no hard-coded machine paths).

`scripts/bootstrap.sh` writes the oracle paths it found into `scripts/env.sh`
and tells you to source it. Nobody sources it: each CI step is its own shell,
and so is every command a contributor pastes. Measured in a bare
`ubuntu:24.04` container -- bootstrap reported `chromium OK <playwright shell>`
and the very next command reported `chromium=MISSING` and generated 3 of 16
corpus documents, exit code 0. CI only escaped it because the GitHub runner
image happens to ship `/usr/bin/google-chrome`, which is provisioning by
accident.

So this module reads `scripts/env.sh` itself. Discovery order is: an explicitly
exported variable, then what bootstrap recorded, then the search path. An
exported value always wins -- overriding the record is how you test another
build of the oracle.
"""
import os, sys, glob, re, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
TOOL = PROJECT                       # the `exactdoc` package lives at the root
if TOOL not in sys.path:
    sys.path.insert(0, TOOL)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

ENV_SH = os.path.join(PROJECT, "scripts", "env.sh")


def _recorded():
    """{name: path} from scripts/env.sh, if bootstrap has run here."""
    out = {}
    try:
        with open(ENV_SH) as f:
            for line in f:
                m = re.match(r'\s*export\s+(\w+)\s*=\s*"?([^"\n]+)"?\s*$', line)
                if m:
                    out[m.group(1)] = m.group(2)
    except OSError:
        pass
    return out


RECORDED = _recorded()


def _first(cands, env=None):
    if env:
        v = os.environ.get(env)
        if v and os.path.exists(v):
            return v
        v = RECORDED.get(env)
        if v and os.path.exists(v):
            return v
    for c in cands:
        if os.path.exists(c):
            return c
        w = shutil.which(c)
        if w:
            return w
    return None


SOFFICE = _first([
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    "/usr/bin/soffice", "/opt/libreoffice26.2/program/soffice",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice", "soffice",
] + sorted(glob.glob(os.path.join(PROJECT, ".tools", "squashfs-root", "opt",
                                  "libreoffice*", "program", "soffice"))),
    env="SOFFICE")

CHROME = _first([
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome", "/usr/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "google-chrome", "chromium",
] + sorted(glob.glob(os.path.expanduser(
    "~/.cache/ms-playwright/chromium_headless_shell-*/"
    "chrome-headless-shell-linux64/chrome-headless-shell"))),
    env="CHROME")
