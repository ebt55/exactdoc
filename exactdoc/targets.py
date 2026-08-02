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

from .errors import OracleUnavailableError
from .options import DEFAULT_ORACLE, ORACLES, canonical_oracle

DEFAULT = DEFAULT_ORACLE


def _libreoffice_render(docx_path: str, tmp_dir: str) -> Optional[str]:
    from .verify import docx_to_pdf
    return docx_to_pdf(docx_path, tmp_dir)


def _gdocs_render_factory() -> Callable[[str, str], Optional[str]]:
    """Round-trip through Drive: upload, let Docs convert, export a PDF.

    Imported lazily and kept out of the default path: it needs credentials and
    network, neither of which a conversion should require.
    """
    from . import gdocs
    svc = gdocs.service(interactive=False)

    def render(docx_path, tmp_dir):
        return gdocs.roundtrip(svc, docx_path, os.path.join(tmp_dir, "gd.pdf"))
    return render


def get_renderer(oracle: str):
    """-> (render_callable | None, resolved_oracle_name).

    Raises OracleUnavailableError when a renderer is named and absent. It used
    to return `(None, "none")`, and the caller then converted open-loop -- so
    'libreoffice' silently resolved to 'no feedback loop at all', which is a
    different product delivered under the same exit code. That is the mechanism
    behind a published fidelity number describing a profile no surface ran, and
    a fallback nobody can see is indistinguishable from a lie.

    `none` is not a failure: it is a legitimate, explicit request for no
    feedback loop, and returns `(None, "none")`.
    """
    t = canonical_oracle(oracle or DEFAULT)
    if t == "none":
        return None, "none"
    if t == "gdocs":
        return _gdocs_render_factory(), "gdocs"
    from .verify import SOFFICE
    if SOFFICE is None:
        raise OracleUnavailableError(
            "the LibreOffice oracle was requested but soffice was not found. "
            "Install LibreOffice, choose another oracle, or set refine_rounds=0 "
            "to convert open-loop deliberately.")
    return _libreoffice_render, "libreoffice"
