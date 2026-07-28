"""Shared path discovery for the testkit (no hard-coded machine paths)."""
import os, sys, glob, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
TOOL = os.path.join(PROJECT, "exactdoc_v1.1")
if TOOL not in sys.path:
    sys.path.insert(0, TOOL)
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def _first(cands, env=None):
    if env and os.environ.get(env) and os.path.exists(os.environ[env]):
        return os.environ[env]
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
], env="SOFFICE")

CHROME = _first([
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome", "/usr/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "google-chrome", "chromium",
], env="CHROME")
