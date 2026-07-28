"""Render targets: which program is the output supposed to look right in?

There is no single "correct" DOCX. The same file lays out differently in Word,
LibreOffice and Google Docs, and the differences are large enough to swamp the
layout work: on a document where LibreOffice places 99% of words within 2pt of
source, Google Docs places 1%, because Docs adds a one-off gap after the first
heading plus roughly 3pt at every paragraph boundary.

So tuning is only meaningful *relative to a target*, and a layout corrected
against one renderer is not corrected for another. Rather than pick a winner,
the target is the user's choice, and each one owns its oracle: the closed loop
in refine.py measures against the chosen renderer and corrects for it.

    gdocs        Google Docs. Needs Drive API credentials; slowest (a network
                 round trip per pass) and the only oracle that answers the
                 question this project actually asks.
    libreoffice  LibreOffice headless. Fast, offline, a good proxy for Word --
                 but a proxy, and measurably not Docs.
    none         No feedback loop. Fastest, deterministic, no dependencies.
"""
import os
from typing import Callable, Optional

TARGETS = ("none", "libreoffice", "gdocs")
DEFAULT = "libreoffice"


def _libreoffice_render(docx_path: str, tmp_dir: str) -> Optional[str]:
    from .verify import docx_to_pdf
    return docx_to_pdf(docx_path, tmp_dir)


def _gdocs_render_factory() -> Callable[[str, str], Optional[str]]:
    """Round-trip through Drive: upload, let Docs convert, export a PDF.

    Imported lazily and kept out of the default path: it needs credentials and
    network, neither of which a conversion should require.
    """
    import sys
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tk = os.path.join(os.path.dirname(here), "testkit")
    if tk not in sys.path:
        sys.path.insert(0, tk)
    import gdocs_oracle as G           # noqa: E402
    svc = G._service(interactive=False)

    def render(docx_path, tmp_dir):
        try:
            return G.roundtrip(svc, docx_path, os.path.join(tmp_dir, "gd.pdf"))
        except Exception:
            return None
    return render


def get_renderer(target: str):
    """-> (render_callable | None, resolved_target_name)."""
    t = (target or DEFAULT).lower()
    if t in ("none", "off"):
        return None, "none"
    if t in ("gdocs", "google", "googledocs", "google-docs"):
        return _gdocs_render_factory(), "gdocs"
    if t in ("libreoffice", "lo", "word", "soffice"):
        from .verify import SOFFICE
        if SOFFICE is None:
            return None, "none"
        return _libreoffice_render, "libreoffice"
    raise ValueError("unknown target %r; choose from %s" % (target, ", ".join(TARGETS)))
