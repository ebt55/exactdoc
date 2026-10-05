"""Read a long PDF's text lines with several worker processes.

The refine loop reads every render back (`PdfiumBackend.page_lines`), and
that read became the largest single cost of a product conversion once the
writer was fast: on y13 (31 pages, rendered as 58) 33s of a 66s conversion,
y12 56s of 97s (WP20c, serial, canonical container). PDFium is not
thread-safe and the work is Python-heavy, so threads cannot help; separate
processes can, because a page's lines depend on that page alone.

**Deterministic by construction.** Pages are split into contiguous slices,
each worker returns its slice's lines (strings and floats, pickled exactly),
and the parent joins the slices in page order -- the list the serial reader
returns, element for element. Any worker failure (a frozen application with
no `-m`, a crash, a timeout) falls back to the serial read; the answer never
depends on which path ran.

**Safe on every platform.** Workers are plain `python -m
exactdoc._pagelines_worker` subprocesses, not multiprocessing: no fork of a
process that may hold threads (the CLI's progress line is a thread), and no
re-import of the caller's main script, which is what makes spawn unsafe for
an unguarded script calling `convert()`.

`EXACTDOC_READ_WORKERS` sets the number of workers; 1 turns the pool off.
Unset, a document gets one worker per `PAGES_PER_WORKER` pages, at most
`MAX_WORKERS` and one fewer than the machine's CPUs.
"""
import os
import pickle
import subprocess
import sys

# A worker costs ~0.35s to start (interpreter + pypdfium2 import, measured on
# a Windows desktop 2026-10-05) and reads ~7 rendered pages a second, so below
# ~16 pages the pool cannot win; four workers hold most of the gain on a
# tester's laptop without swamping a machine that converts several documents
# at once.
MIN_PAGES = 16
PAGES_PER_WORKER = 8
MAX_WORKERS = 4
WORKER_TIMEOUT_S = 600


def read_workers(pages: int) -> int:
    env = os.environ.get("EXACTDOC_READ_WORKERS", "").strip()
    if env:
        try:
            return max(1, int(env))
        except ValueError:
            return 1
    if pages < MIN_PAGES:
        return 1
    cpus = os.cpu_count() or 1
    return max(1, min(MAX_WORKERS, cpus - 1, pages // PAGES_PER_WORKER))


def _slices(pages: int, workers: int):
    base, extra = divmod(pages, workers)
    out, start = [], 0
    for k in range(workers):
        stop = start + base + (1 if k < extra else 0)
        if stop > start:
            out.append((start, stop))
        start = stop
    return out


def _page_count(path: str) -> int:
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(path)
    try:
        return len(doc)
    finally:
        doc.close()


def _child_env():
    """The worker imports the same exactdoc as this process."""
    import exactdoc
    pkg_parent = os.path.dirname(os.path.dirname(os.path.abspath(exactdoc.__file__)))
    env = dict(os.environ)
    env["PYTHONPATH"] = pkg_parent + (os.pathsep + env["PYTHONPATH"]
                                      if env.get("PYTHONPATH") else "")
    env["EXACTDOC_READ_WORKERS"] = "1"
    return env


def page_lines_parallel(path: str, pages: int, workers: int):
    """The lines of every page, read by `workers` processes; None on any failure."""
    path = os.path.abspath(path)
    env = _child_env()
    procs = []
    try:
        for start, stop in _slices(pages, workers):
            procs.append(subprocess.Popen(
                [sys.executable, "-m", "exactdoc._pagelines_worker", path,
                 str(start), str(stop)],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, env=env))
        out = []
        for proc in procs:
            data, _ = proc.communicate(timeout=WORKER_TIMEOUT_S)
            if proc.returncode != 0:
                return None
            out.extend(pickle.loads(data))
        return out if len(out) == pages else None
    except Exception:
        return None
    finally:
        for proc in procs:
            if proc.poll() is None:
                try:
                    proc.kill()
                    proc.wait(timeout=30)
                except Exception:
                    pass


def page_lines(path: str):
    from .parse_pdfium import page_lines_range
    pages = _page_count(path)
    workers = read_workers(pages)
    if workers > 1:
        got = page_lines_parallel(path, pages, workers)
        if got is not None:
            return got
    return page_lines_range(path, 0, pages)
