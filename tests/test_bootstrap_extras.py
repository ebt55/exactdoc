"""The canonical bootstrap installs both backends without cloud credentials.

PDFium is a core dependency, while the backend-parity harness needs the optional
PyMuPDF reference arm -- so the measurement environment installs the `mupdf`
extra that a user's install deliberately does not have. Keep the uv and pip
fallback paths aligned.

The pin is exact rather than a substring check for one reason: `gdocs` must NOT
appear here. Provisioning the cloud oracle is a separate, consented step, and a
bootstrap that quietly installed its client would make "the canonical
environment" a thing that can talk to Google.

    python tests/test_bootstrap_extras.py
"""
import os
import re


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOTSTRAP = os.path.join(ROOT, "scripts", "bootstrap.sh")


def install_profiles():
    with open(BOOTSTRAP, encoding="utf-8") as f:
        source = f.read()
    uv = re.findall(r"^\s*uv sync ([^#\n]+)$", source, re.MULTILINE)
    pip = re.findall(r'pip" install --quiet -e "\.\[([^]]+)\]"', source)
    return [s.strip() for s in uv], pip


def test_canonical_bootstrap_extras():
    uv, pip = install_profiles()
    assert uv == ["--frozen --extra test --extra mupdf"], uv
    assert pip == ["test,mupdf"], pip


if __name__ == "__main__":
    test_canonical_bootstrap_extras()
    print("bootstrap extras: uv and pip both install test+mupdf only")
