"""The canonical bootstrap installs both backends without cloud credentials.

PyMuPDF is a core dependency, while the backend-parity harness needs the
optional PDFium candidate backend. Keep the uv and pip fallback paths aligned.

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
    assert uv == ["--frozen --extra test --extra pdfium"], uv
    assert pip == ["test,pdfium"], pip


if __name__ == "__main__":
    test_canonical_bootstrap_extras()
    print("bootstrap extras: uv and pip both install test+pdfium only")
