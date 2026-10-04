"""Fidelity verification: DOCX -> PDF (LibreOffice) -> image diff vs source.

Product diagnostics, not release evidence: `testkit/` is the independent harness
and deliberately shares no code with the converter. This module exists so that
`--verify` can tell a user something about their own document.

Page rasterisation goes through the backend seam (`Backend.render_page`) rather
than through `fitz` directly. The import used to be at module scope, which put
PyMuPDF on the default runtime path of a stage that only wants pixels.
"""
import io
import json
import os
import re
import subprocess
import tempfile
from typing import List, Optional

import numpy as np


def _find_soffice():
    """Locate LibreOffice on any platform.

    The previous list held POSIX paths only, so `--verify` silently reported
    'LibreOffice not found' on every Windows and macOS machine even with a
    working install.
    """
    import shutil
    env = os.environ.get("SOFFICE")
    if env and os.path.exists(env):
        return env
    for cand in (
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
            "/Applications/LibreOffice.app/Contents/MacOS/soffice",
            "/opt/libreoffice26.2/program/soffice",
            "/usr/bin/soffice", "/usr/local/bin/soffice"):
        if os.path.exists(cand):
            return cand
    return shutil.which("soffice") or shutil.which("libreoffice")


SOFFICE = _find_soffice()

# Where a LibreOffice user profile may live. A fresh profile nests 138
# characters below its root, and soffice does not survive a root that pushes
# that past the Windows path limit: measured on LibreOffice 25.2 / Windows 11,
# profile creation succeeds with a 132-character profile path and crashes
# (0xC0000409, with a fatal-error dialog on the user's screen) at 162. Agent
# and CI temp directories routinely run to ~200 characters, which is how every
# product conversion under one failed with "the render oracle produced no
# output" (benchmark gap #11). So the session root -- profile, soffice's own
# temp files and the document copy -- is placed under a SHORT directory, not
# under whatever TEMP happens to be. 96 leaves the session's own ~14 characters
# and a margin under the measured 132.
SHORT_ROOT_MAX = 96
# One render's wall-clock bound. A conversion that has not finished by then has
# hung; it is killed with its whole process tree rather than left holding the
# profile.
RENDER_TIMEOUT_S = 300


# The refine loop reads only text positions from LibreOffice's PDF, so the
# images in it are wasted work. From 7.4 LibreOffice accepts export options as
# JSON on the command line; these drop image quality, outline bookmarks and
# notes, none of which moves a line. Measured in the canonical container
# (LibreOffice 24.2, 2026-10-05) on the eight-document product A/B set: every
# page_lines identical to the default export, PDFs 1.3-8x smaller, renders
# 2-22% faster on the documents with pictures, best of three
# (docs/evidence/refine-speed-2026-10-05c.json).
# An older LibreOffice would reject the JSON and write nothing, so below 7.4,
# or when the version cannot be read, the plain "pdf" export stays.
FAST_EXPORT_MIN_VERSION = (7, 4)
FAST_PDF_EXPORT = "pdf:writer_pdf_Export:" + json.dumps({
    "ExportBookmarks": {"type": "boolean", "value": "false"},
    "ExportNotes": {"type": "boolean", "value": "false"},
    "MaxImageResolution": {"type": "long", "value": "75"},
    "Quality": {"type": "long", "value": "50"},
    "ReduceImageResolution": {"type": "boolean", "value": "true"},
    "UseLosslessCompression": {"type": "boolean", "value": "false"},
}, sort_keys=True, separators=(",", ":"))
VERSION_TIMEOUT_S = 30
_VERSIONS = {}


def soffice_version(soffice: Optional[str] = None):
    """(major, minor) of the LibreOffice at `soffice` (default SOFFICE), or None.

    Asked once per path per process (`soffice --version`, ~0.3-0.7s). On
    Windows the console launcher soffice.com answers; soffice.exe is a GUI
    program whose --version was seen to block, so without a .com beside it
    the version is unknown.
    """
    soffice = soffice or SOFFICE
    if not soffice:
        return None
    if soffice in _VERSIONS:
        return _VERSIONS[soffice]
    exe = soffice
    if os.name == "nt":
        com = os.path.splitext(soffice)[0] + ".com"
        exe = com if os.path.exists(com) else None
    version = None
    if exe:
        try:
            proc = subprocess.run([exe, "--version"], capture_output=True,
                                  text=True, timeout=VERSION_TIMEOUT_S,
                                  stdin=subprocess.DEVNULL)
            m = re.search(r"LibreOffice\s+(\d+)\.(\d+)", proc.stdout or "")
            if m:
                version = (int(m.group(1)), int(m.group(2)))
        except (OSError, subprocess.SubprocessError, ValueError):
            version = None
    _VERSIONS[soffice] = version
    return version


def pdf_export_filter(soffice: Optional[str] = None) -> str:
    """The --convert-to argument the refine loop's renders use."""
    v = soffice_version(soffice)
    if v is not None and v >= FAST_EXPORT_MIN_VERSION:
        return FAST_PDF_EXPORT
    return "pdf"


def _short_root() -> str:
    """A writable directory short enough to hold a LibreOffice profile.

    `EXACTDOC_SOFFICE_ROOT` wins when set. Otherwise the temp directory is used
    when it is short enough, and failing that the platform's ordinary short
    temp location -- the temp directory a default Windows account has
    (`%LOCALAPPDATA%\\Temp`), `C:\\Temp`, or `/tmp`.
    """
    explicit = os.environ.get("EXACTDOC_SOFFICE_ROOT")
    if explicit:
        return explicit
    tmp = tempfile.gettempdir()
    if len(tmp) <= SHORT_ROOT_MAX:
        return tmp
    cands = []
    if os.name == "nt":
        la = os.environ.get("LOCALAPPDATA")
        if la:
            cands.append(os.path.join(la, "Temp"))
        cands.append(os.path.join(os.environ.get("SystemDrive", "C:") + "\\",
                                  "Temp"))
    else:
        cands += ["/tmp", "/var/tmp"]
    for c in cands:
        if len(c) <= SHORT_ROOT_MAX:
            try:
                os.makedirs(c, exist_ok=True)
            except OSError:
                continue
            if os.access(c, os.W_OK):
                return c
    return tmp


def _file_url(path: str) -> str:
    p = os.path.abspath(path).replace("\\", "/")
    return "file:///" + p.lstrip("/")


def _kill_tree(proc) -> None:
    """Kill soffice AND its children. `soffice` is a launcher: on Linux a shell
    script over oosplash over soffice.bin, on Windows soffice.exe over
    soffice.bin. Killing only the process `subprocess` started orphans the one
    doing the work, still holding the profile."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=30)
        else:
            import signal
            os.killpg(proc.pid, signal.SIGKILL)
    except Exception:
        pass
    try:
        proc.kill()
    except Exception:
        pass
    try:
        proc.wait(timeout=30)
    except Exception:
        pass


class SofficeSession:
    """One private LibreOffice installation directory, reused across renders.

    A product conversion renders the same document up to four times. Each
    render used to start soffice against a fresh profile and delete it after,
    so every round paid profile creation: measured on Windows, 7-11s per render
    cold against 3.5-4s with the profile kept (LibreOffice 25.2, an 80-page
    document). In the Linux container creation is cheap (1.9s cold, 2.0-2.3s
    warm) and keeping it costs nothing. The profile now lives for the session.

    A long-lived soffice process (forwarding conversions to a running instance)
    was measured too and bought nothing over the kept profile: 3.2-3.7s on
    Windows, 1.7-4.6s in the container. It would add a process to keep alive,
    find and kill; it is not used.

    Isolation is unchanged: a session's directory is private (`mkdtemp`), so
    concurrent conversions never share a profile, and `close()` removes it.

    Robustness is the other half. A render that exits without writing a PDF is
    retried once on the same profile (soffice refuses some rapid restarts and
    exits 0 having done nothing) and once more on a fresh one (a profile left
    damaged by a crash). A render that hangs is killed, tree and all, and not
    retried. `last_failure` says, content-free, what went wrong.
    """

    def __init__(self, profile: Optional[str] = None,
                 export_filter: Optional[str] = None):
        self.root = None
        self._profile = profile
        self.last_failure = None
        self.renders = 0
        # None: chosen at the first render from the LibreOffice version
        # (pdf_export_filter); "pdf" forces the plain export.
        self.export_filter = export_filter

    def _ensure(self):
        if self.root is None:
            self.root = tempfile.mkdtemp(prefix="xd-", dir=_short_root())
            for sub in ("t", "w"):
                os.makedirs(os.path.join(self.root, sub), exist_ok=True)
        return self.root

    @property
    def profile(self) -> str:
        return self._profile or os.path.join(self._ensure(), "p")

    def _run(self, docx_copy: str, work: str):
        env = dict(os.environ)
        env.setdefault("HOME", tempfile.gettempdir())
        tmp = os.path.join(self._ensure(), "t")
        env["TMP"] = env["TEMP"] = env["TMPDIR"] = tmp
        if self.export_filter is None:
            self.export_filter = pdf_export_filter(SOFFICE)
        cmd = [SOFFICE, "--headless", "--norestore", "--invisible",
               "--nolockcheck", "-env:UserInstallation=" + _file_url(self.profile),
               "--convert-to", self.export_filter, "--outdir", work, docx_copy]
        kw = {}
        if os.name == "nt":
            kw["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            kw["start_new_session"] = True
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, env=env, **kw)
        except OSError as e:
            return "soffice could not be started (%s)" % type(e).__name__
        try:
            rc = proc.wait(timeout=RENDER_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            return "timeout"
        return rc

    def render(self, docx_path: str, out_dir: str) -> Optional[str]:
        """DOCX -> `<out_dir>/<stem>.pdf`. None if no PDF could be produced."""
        if SOFFICE is None:
            self.last_failure = "LibreOffice not found"
            return None
        import shutil
        self.renders += 1
        stem = os.path.splitext(os.path.basename(docx_path))[0]
        final = os.path.join(out_dir, stem + ".pdf")
        if os.path.exists(final):
            os.remove(final)
        work = os.path.join(self._ensure(), "w")
        src = os.path.join(work, "d.docx")
        out = os.path.join(work, "d.pdf")
        shutil.copyfile(docx_path, src)
        outcome = None
        for attempt in range(3):
            if os.path.exists(out):
                os.remove(out)
            if attempt == 2 and self._profile is None:
                shutil.rmtree(self.profile, ignore_errors=True)
            outcome = self._run(src, work)
            if os.path.exists(out) and os.path.getsize(out) > 0:
                shutil.move(out, final)
                self.last_failure = None
                return final
            if isinstance(outcome, str):
                break                 # a hang or a launch failure: not retried
        if outcome == "timeout":
            self.last_failure = ("LibreOffice did not finish within %ds"
                                 % RENDER_TIMEOUT_S)
        elif isinstance(outcome, str):
            self.last_failure = outcome
        else:
            self.last_failure = ("LibreOffice exited with status %s without "
                                 "writing a PDF (%d attempts)"
                                 % (outcome, attempt + 1))
        return None

    def close(self):
        if self.root is not None:
            import shutil
            shutil.rmtree(self.root, ignore_errors=True)
            self.root = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def docx_to_pdf(docx_path: str, out_dir: str, profile: Optional[str] = None
                ) -> Optional[str]:
    """Render a DOCX to PDF. Returns None if LibreOffice is unavailable.

    A dedicated user profile is required, not a nicety: soffice refuses rapid
    successive starts against a shared default profile and exits 0 without
    writing anything, which looks exactly like a silent conversion failure.

    It was a single fixed path under the temp directory, shared by every
    conversion in every process on the machine, so two concurrent conversions
    contended for one profile and reproduced the very failure the profile
    existed to prevent. Each invocation now gets a **fresh** directory and
    removes it afterwards, so concurrency is safe by construction and no state
    survives from one render to influence the next.

    `profile=` overrides that for a caller who wants one profile across a batch.
    `testkit/harness.py` deliberately does exactly that: soffice also refuses
    *rapid* restarts against differing profiles, so a tight batch loop wants one
    warm profile, while a product conversion wants isolation. Those are different
    trade-offs and both are now expressible. A caller rendering the same
    document repeatedly -- the refine loop -- wants a `SofficeSession`.
    """
    if SOFFICE is None:
        return None
    # The plain export: this render is for looking at (`--verify` compares its
    # pixels), where the refine loop's session only reads text positions.
    with SofficeSession(profile=profile, export_filter="pdf") as session:
        return session.render(docx_path, out_dir)


def _page_count(pdf_path: str, backend) -> int:
    """Page count via the seam. `page_lines` returns one entry per page, text or
    not, so its length is the count -- extracting text to count pages is wasteful,
    but this is a diagnostic that goes on to rasterise every page, and a fourth
    seam operation for it would be a worse trade than the wasted extraction."""
    return len(backend.page_lines(pdf_path))


def _page_array(pdf_path: str, i: int, dpi: int, backend) -> Optional[np.ndarray]:
    """One page as an RGB array, or None if the backend will not render it.

    At 96 dpi a US-Letter page is 816x1056x3 float64 = 20.7 MB, so *which* pages
    are alive at once is a scaling property of the caller, not a detail.

    Decoding the backend's PNG with Pillow costs one encode/decode per page that
    reading a MuPDF pixmap's raw samples did not. That is the price of the seam
    being a byte format both backends can honestly produce, and it is paid by a
    diagnostic path, not by conversion.
    """
    data = backend.render_page(pdf_path, i + 1, dpi=dpi)
    if not data:
        return None
    import PIL.Image as Image
    return np.asarray(Image.open(io.BytesIO(data)).convert("RGB")).astype(
        np.float64)


def _page_arrays(pdf_path: str, dpi: int = 96, backend=None) -> List[np.ndarray]:
    """Every page at once. Costs 20.7 MB per page -- see `_page_array`.

    `compare` deliberately does NOT use this: it rasterises one pair at a time.
    Kept because rasterising a whole short document in one call is a reasonable
    thing for an ad-hoc caller to want.
    """
    if backend is None:
        from .backend import get_backend
        backend = get_backend()
    out = []
    for i in range(_page_count(pdf_path, backend)):
        arr = _page_array(pdf_path, i, dpi, backend)
        if arr is None:
            break
        out.append(arr)
    return out


def _pad_to(a: np.ndarray, h: int, w: int) -> np.ndarray:
    out = np.full((h, w, a.shape[2]), 255.0)
    out[:a.shape[0], :a.shape[1], :] = a[:h, :w, :]
    return out


def ssim(a: np.ndarray, b: np.ndarray) -> float:
    """Mean SSIM over 8x8 windows on the grayscale image."""
    ga = a.mean(axis=2)
    gb = b.mean(axis=2)
    k = 8
    H = (ga.shape[0] // k) * k
    W = (ga.shape[1] // k) * k
    ga = ga[:H, :W].reshape(H // k, k, W // k, k).transpose(0, 2, 1, 3).reshape(-1, k * k)
    gb = gb[:H, :W].reshape(H // k, k, W // k, k).transpose(0, 2, 1, 3).reshape(-1, k * k)
    mu_a = ga.mean(1)
    mu_b = gb.mean(1)
    va = ga.var(1)
    vb = gb.var(1)
    cov = ((ga - mu_a[:, None]) * (gb - mu_b[:, None])).mean(1)
    C1, C2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    s = ((2 * mu_a * mu_b + C1) * (2 * cov + C2)) / \
        ((mu_a ** 2 + mu_b ** 2 + C1) * (va + vb + C2))
    return float(s.mean())


def compare(src_pdf: str, converted_pdf: str, out_dir: Optional[str] = None,
            dpi: int = 96, backend=None):
    # Page i of the source is only ever compared with page i of the render, so
    # rasterise exactly that pair and let it go. Materialising both documents
    # first cost (src_pages + out_pages) x 20.7 MB with nothing released until
    # the loop ended -- a property of the documents, not of the comparison.
    # `testkit/harness.py` carried the identical shape and was OOM-killed on a
    # 591-page render before it scored a single page (b0762a2); this module
    # ships in the wheel and drives `--verify`, so the same arithmetic lands on
    # a user converting a long document. The arrays, their order and every
    # number below are unchanged -- only how long each one stays alive.
    if backend is None:
        from .backend import get_backend
        backend = get_backend()
    n_a = _page_count(src_pdf, backend)
    n_b = _page_count(converted_pdf, backend)
    rows = []
    i = 0
    a_ended = b_ended = False
    while True:
        # `_page_arrays` stopped at the first page the backend would not render
        # and the loop then ran to max(len(A), len(B)). Ending each side on its
        # own first refusal reproduces both lengths, and therefore every row.
        a = None if (a_ended or i >= n_a) else _page_array(src_pdf, i, dpi,
                                                           backend)
        if a is None:
            a_ended = True
        b = None if (b_ended or i >= n_b) else _page_array(converted_pdf, i,
                                                           dpi, backend)
        if b is None:
            b_ended = True
        if a is None and b is None:
            break
        if a is None or b is None:
            rows.append({"page": i + 1, "ssim": 0.0, "note": "page count mismatch"})
            i += 1
            continue
        h = max(a.shape[0], b.shape[0])
        w = max(a.shape[1], b.shape[1])
        a2, b2 = _pad_to(a, h, w), _pad_to(b, h, w)
        del a, b
        s = ssim(a2, b2)
        mad = float(np.abs(a2 - b2).mean())
        rows.append({"page": i + 1, "ssim": round(s, 4), "mad": round(mad, 2)})
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
            import PIL.Image as Image
            gapw = 12
            canvas = np.full((h, w * 2 + gapw, 3), 200.0)
            canvas[:, :w, :] = a2
            canvas[:, w + gapw:, :] = b2
            Image.fromarray(canvas.astype(np.uint8)).save(
                os.path.join(out_dir, "cmp_p%02d.png" % (i + 1)))
            del canvas
        del a2, b2
        i += 1
    return rows


def audit(src_pdf: str, docx_path: str, backend=None):
    """Text-coverage audit: is every source character present in the DOCX?

    Rasterized figure regions (charts) legitimately carry their labels as
    pixels, so their text is excluded from the source side. That exclusion is
    exactly why this is a *diagnostic* and not evidence: it lets the converter
    define its own denominator, and the original `verify.py` scored the résumé at
    `src_chars: 0` because everything it rasterised vanished from its own score.
    `testkit/harness.py` is raster-blind on purpose and shares no code with this.
    """
    from .infer import infer
    from .layout import FigureEl
    from .model import bbox_overlap, bbox_area
    import docx as _docx
    from collections import Counter

    if backend is None:
        from .backend import get_backend
        backend = get_backend()
    ir = backend.parse_pdf(src_pdf, keep_image_data=False)
    lay = infer(ir)
    fig_clips = {}
    for pg in lay.pages:
        for ch in pg.chunks:
            for el in ch.elements:
                if isinstance(el, FigureEl):
                    fig_clips.setdefault(el.page_no, []).append(el.clip)
    src_parts = []
    for p in ir.pages:
        clips = fig_clips.get(p.number, [])
        for b in p.blocks:
            for l in b.lines:
                in_fig = any(bbox_overlap(l.bbox, c) > 0.5 * max(1e-6, bbox_area(l.bbox))
                             for c in clips)
                if not in_fig:
                    src_parts.append(l.text)
    d = _docx.Document(docx_path)
    out_parts = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            for c in row.cells:
                out_parts.append(c.text)
    for s in d.sections:
        for hf in (s.header, s.footer, s.first_page_header, s.first_page_footer):
            try:
                for p in hf.paragraphs:
                    out_parts.append(p.text)
                for t in hf.tables:
                    for row in t.rows:
                        for c in row.cells:
                            out_parts.append(c.text)
            except Exception:
                pass

    def norm(t):
        return re.sub(r"[\s ]+", "", t)

    def grams(s, k=3):
        return Counter(s[i:i + k] for i in range(max(0, len(s) - k + 1)))

    src_n = norm("".join(src_parts))
    out_n = norm("".join(out_parts))
    g1, g2 = grams(src_n), grams(out_n)
    inter = sum(min(c, g2[g]) for g, c in g1.items())
    cov = inter / max(1, sum(g1.values()))
    return {"src_chars": len(src_n), "docx_chars": len(out_n),
            "text_coverage": round(cov, 4)}


def verify(src_pdf: str, docx_path: str, out_dir: Optional[str] = None,
           backend=None):
    with tempfile.TemporaryDirectory() as td:
        pdf2 = docx_to_pdf(docx_path, td)
        if pdf2 is None:
            return {"available": False, "rows": []}
        rows = compare(src_pdf, pdf2, out_dir=out_dir, backend=backend)
        keep = os.path.join(out_dir, "converted.pdf") if out_dir else None
        if keep:
            import shutil
            shutil.copy(pdf2, keep)
    mean = sum(r.get("ssim", 0) for r in rows) / max(1, len(rows))
    return {"available": True, "rows": rows, "mean_ssim": round(mean, 4)}
