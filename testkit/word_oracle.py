"""Microsoft Word oracle: render DOCX to PDF through desktop Word, score it.

    python testkit/word_oracle.py sweep OUT --docx-dir RUNS/<name>.docx/raw --lane raw
    python testkit/word_oracle.py sweep OUT --profile raw          # convert locally
    python testkit/word_oracle.py summary OUT/rows.jsonl

Most people who open an exactdoc DOCX open it in Word, and until WP21 nothing
had measured Word at all: the gate measures LibreOffice and the live sweep
measures Google Docs. This is the third renderer, in the shape of the Google
Docs live sweep (one JSON line per document, the same keys, resumable), so a
reader of one lane reads all three.

**Windows only, never gating.** It drives Word through COM from a PowerShell
subprocess (pywin32 is not a dependency), so on any other platform, or where
Word is absent, `available()` is False and every entry point skips cleanly. The
Linux gate never imports it.

**Word belongs to the person at the keyboard.** The machine this runs on is a
personal one, and Word may be in use while a sweep runs. So the oracle:

  * creates its OWN Word instance and records that instance's process id: the
    WINWORD processes alive before `New-Object` are excluded, exactly one new
    one must appear, and the window of the first document it opens must belong
    to it (`GetWindowThreadProcessId`). An instance that cannot be proven ours
    is never killed -- only quit through COM;
  * opens documents read-only, not added to the recent-files list, with
    `DisplayAlerts` off and macros force-disabled (`AutomationSecurity` 3), and
    never changes `Options` (Word persists those);
  * touches only documents it opened: if a document it did not open appears in
    its instance (a double-clicked file routed there), the session stops, the
    instance is made visible and LEFT RUNNING for the user to save their work;
  * always quits in a `finally`, and a hung document has a hard timeout: the
    worker and the proven-ours instance are killed, any visible window titles of
    that instance are recorded (a dialog that needs a human -- activation,
    sign-in, file repair -- is reported, never clicked), and the remaining
    documents go to a fresh instance. A startup that fails twice running stops
    the sweep.

Documents are batched, many per Word session: starting Word costs ~3s and a
two-page document renders in ~1s.
"""
import argparse
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# The keys of a Google Docs live-sweep row (SCR/gdsweep/gdsweep.py), so a
# reader of that lane reads this one. Word-specific extras ride beside them.
ROW_KEYS = ("page_match", "src_pages", "out_pages", "word_recall", "doc_recall",
            "dx_p50", "dx_p90", "dy_p50", "dy_p90", "within2pt", "mean_ssim",
            "live_text_cov", "raster_frac")

# Timeouts. A 2-page document renders in 1.1s and the corpus's largest DOCX
# (240 pages) in well under a minute; five minutes is a hang, not a slow file.
DOC_TIMEOUT_S = 300
# `New-Object -ComObject Word.Application` took 2.9s on the owner's machine.
START_TIMEOUT_S = 90
# Between one document's DONE and the next BEGIN only a Close() runs.
GAP_TIMEOUT_S = 60
# After Quit() Word took ~2s to leave the process table (measured 2026-10-05).
QUIT_GRACE_S = 30
BATCH = 20
# What Word says when a file needs its repair pass ("Word found unreadable
# content ...", "... encountered an error trying to open the file", "the file
# is corrupt"). With alerts off it raises instead of asking; the row records
# that a person opening the file would have been asked.
_REPAIR = re.compile(r"unreadable content|repair|corrupt|problem with its contents", re.I)

WORKER_PS1 = r"""
param([string]$Jobs)
$ErrorActionPreference = 'Stop'
function Say([string]$s) { [Console]::Out.WriteLine($s); [Console]::Out.Flush() }
Add-Type -TypeDefinition @"
using System; using System.Runtime.InteropServices;
public static class ExactdocWordOracle {
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
}
"@
# No @(...) here: Windows PowerShell 5.1 emits a parsed JSON array as ONE
# pipeline object, and wrapping it nests the whole job list in a 1-element array.
# Nor `$jobs`: variables are case-insensitive, and `$Jobs` is the [string]
# parameter, so assigning the list to it would turn the list into one string.
$joblist = (Get-Content -Raw -Encoding UTF8 -LiteralPath $Jobs | ConvertFrom-Json)
$before = @(Get-Process -Name WINWORD -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
$w = $null; $ours = 0; $verified = $false; $foreign = $false
try {
  $w = New-Object -ComObject Word.Application
  $new = @(Get-Process -Name WINWORD -ErrorAction SilentlyContinue | ForEach-Object { $_.Id } |
           Where-Object { $before -notcontains $_ })
  if ($new.Count -eq 1) { $ours = [int]$new[0]; Say ("PID " + $ours) }
  else { Say ("PIDAMBIGUOUS " + ($new -join ',')) }
  $w.Visible = $false
  $w.DisplayAlerts = 0
  $w.AutomationSecurity = 3
  Say ("ENV " + $w.Build + " addins=" + $w.AddIns.Count + " comaddins=" + $w.COMAddIns.Count)
  foreach ($j in $joblist) {
    if (Test-Path -LiteralPath ($Jobs + '.stop')) { Say "STOPPED"; break }
    if ($w.Documents.Count -ne 0) { $foreign = $true; Say "FOREIGN"; break }
    Say ("BEGIN " + $j.i)
    $t = [Diagnostics.Stopwatch]::StartNew()
    $d = $null
    try {
      $d = $w.Documents.Open([string]$j.docx, $false, $true, $false)
      # Open hands back nothing, rather than throwing, for a path over Word's
      # length limit (seen 2026-10-05 as "null-valued expression" failures)
      if ($d -eq $null) { throw "Word returned no document for this file" }
      Say ("OPENED " + $j.i + " " + $d.CompatibilityMode)
      if (-not $verified -and $ours -ne 0) {
        [uint32]$p = 0
        [void][ExactdocWordOracle]::GetWindowThreadProcessId([IntPtr]$d.ActiveWindow.Hwnd, [ref]$p)
        if ([int]$p -eq $ours) { $verified = $true; Say ("VERIFIED " + $ours) }
        else { Say ("MISMATCH " + $p); $ours = 0 }
      }
      $pages = $d.ComputeStatistics(2)
      if (Test-Path -LiteralPath $j.pdf) { Remove-Item -LiteralPath $j.pdf }
      # wdExportFormatPDF, print-optimised, whole document, content only,
      # tagged, BitmapMissingFonts OFF so text stays text for the scorer.
      $d.ExportAsFixedFormat([string]$j.pdf, 17, $false, 0, 0, 1, 1, 0, $true, $true, 0, $true, $false, $false)
      Say ("DONE " + $j.i + " " + $pages + " " + [int]$t.ElapsedMilliseconds)
    } catch {
      Say ("FAIL " + $j.i + " " + (($_.Exception.Message -replace '\s+', ' ').Trim()))
    } finally {
      if ($d -ne $null) {
        try { $d.Close([ref]0) } catch { }
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($d)
      }
    }
  }
} catch {
  Say ("SESSIONFAIL " + (($_.Exception.Message -replace '\s+', ' ').Trim()))
} finally {
  if ($w -ne $null) {
    $n = 0
    try { $n = $w.Documents.Count } catch { }
    if ($n -gt 0) { $foreign = $true }
    if ($foreign) {
      try { $w.Visible = $true } catch { }
      Say "FOREIGNKEPT"
    } else {
      try { $w.Quit([ref]0); Say "QUIT ok" }
      catch { Say ("QUITFAIL " + (($_.Exception.Message -replace '\s+', ' ').Trim())) }
    }
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($w)
  }
}
"""


class WordUnavailable(RuntimeError):
    """Not Windows, or no Word: the caller skips."""


class WordDialog(RuntimeError):
    """Word stopped on something a human must answer; the sweep stops."""


def winword_path():
    """WINWORD.EXE from the COM registration, or None."""
    if sys.platform != "win32":
        return None
    try:
        import winreg
        key = r"SOFTWARE\Classes\CLSID\{000209FF-0000-0000-C000-000000000046}\LocalServer32"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as k:
            cmd = winreg.QueryValue(k, None)
    except OSError:
        return None
    exe = cmd.split(" /")[0].strip().strip('"')
    return exe if os.path.exists(exe) else None


def available():
    return winword_path() is not None


# ------------------------------------------------------------ process helpers
def _pid_alive(pid):
    """True while process `pid` exists (Windows; never raises)."""
    if not pid or sys.platform != "win32":
        return False
    import ctypes
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x00100000 | 0x1000, False, int(pid))  # SYNCHRONIZE | QUERY_LIMITED
    if not h:
        return False
    try:
        return k32.WaitForSingleObject(h, 0) == 0x102            # WAIT_TIMEOUT
    finally:
        k32.CloseHandle(h)


def _kill_word_pid(pid):
    """Force-end OUR Word instance. The image-name filter means a recycled pid
    that now belongs to anything other than WINWORD is left alone."""
    subprocess.run(["taskkill", "/F", "/PID", str(int(pid)),
                    "/FI", "IMAGENAME eq WINWORD.EXE"],
                   capture_output=True, timeout=30)


def _window_titles(pid):
    """Visible top-level window titles of process `pid` (ours only)."""
    if not pid or sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes
    u32 = ctypes.windll.user32
    out = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        p = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid and u32.IsWindowVisible(hwnd):
            n = u32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            u32.GetWindowTextW(hwnd, buf, n + 1)
            out.append(buf.value)
        return True
    u32.EnumWindows(cb, 0)
    return out


def _spawn(script, jobs_file):
    return subprocess.Popen(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", script, "-Jobs", jobs_file],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


class _Hooks:
    """The side effects, injectable so the batching/cleanup logic is testable
    with COM mocked out."""
    spawn = staticmethod(_spawn)
    kill_pid = staticmethod(_kill_word_pid)
    pid_alive = staticmethod(_pid_alive)
    window_titles = staticmethod(_window_titles)
    clock = staticmethod(time.monotonic)
    sleep = staticmethod(time.sleep)


def _reader(stream, q):
    for line in stream:
        q.put(line.rstrip("\r\n"))
    q.put(None)


# --------------------------------------------------------------- the renderer
def render(pairs, work_dir, doc_timeout=DOC_TIMEOUT_S, start_timeout=START_TIMEOUT_S,
           batch=BATCH, on_result=None, hooks=_Hooks, log=None):
    """Render [(docx, pdf)] through Word. Returns {docx: result}.

    result: {"pdf", "pages", "render_s"} on success, else {"error"}; a hang is
    {"error": "timeout ...", "hang": True}. `on_result(docx, result)` fires as
    each document finishes, so scoring can overlap rendering.
    Raises WordDialog when Word needs a human, WordUnavailable when it cannot
    start at all; every instance this function created is gone (or, holding a
    document it did not open, visible and deliberately left) when it returns.
    """
    log = log or (lambda s: None)
    os.makedirs(work_dir, exist_ok=True)
    script = os.path.join(work_dir, "word_worker.ps1")
    with open(script, "w", encoding="utf-8-sig") as f:   # BOM: PS 5.1 reads UTF-8
        f.write(WORKER_PS1)
    results = {}
    pending = [(os.path.abspath(d), os.path.abspath(p)) for d, p in pairs]
    start_failures = 0
    session_no = 0
    while pending:
        chunk, pending = pending[:batch], pending[batch:]
        session_no += 1
        jobs_file = os.path.join(work_dir, "jobs_%03d.json" % session_no)
        with open(jobs_file, "w", encoding="utf-8") as f:
            json.dump([{"i": i, "docx": d, "pdf": p} for i, (d, p) in enumerate(chunk)], f)
        out = _session(script, jobs_file, chunk, doc_timeout, start_timeout, hooks, log)
        for docx, res in out["results"].items():
            results[docx] = res
            if on_result:
                on_result(docx, res)
        if out["dialog"]:
            raise WordDialog(out["dialog"])
        if out["foreign"]:
            raise WordDialog("a document this oracle did not open appeared in its Word "
                             "instance; the instance was left visible and running")
        # A session that finished nothing (Word would not start, or died
        # before its first document) twice running means Word is unusable
        # here; retrying forever would only start instance after instance.
        if not out["results"]:
            start_failures += 1
            if start_failures >= 2:
                raise WordUnavailable("Word made no progress twice running: %s"
                                      % (out["note"] or "no output"))
        else:
            start_failures = 0
        # whatever the session did not reach goes to a fresh instance
        pending = [c for c in chunk if c[0] not in results] + pending
    return results


def _session(script, jobs_file, chunk, doc_timeout, start_timeout, hooks, log):
    """One Word instance over `chunk`. Never raises for Word's own failures;
    a failure on this side (a bug, Ctrl-C) still ends the worker and the
    instance before it propagates."""
    proc = hooks.spawn(script, jobs_file)
    q = queue.Queue()
    threading.Thread(target=_reader, args=(proc.stdout, q), daemon=True).start()
    st = {"ours": 0, "verified": False, "started": False, "foreign": False,
          "current": None, "note": "", "eof": False, "expired": False}
    results = {}
    dialog = None
    try:
        _drive(q, st, results, chunk, doc_timeout, start_timeout, hooks, log)
    finally:
        if not st["eof"] and not st["expired"]:
            # This side failed (a bug, Ctrl-C) while Word was healthy. Ask the
            # worker to stop after the current document; it then quits Word
            # itself, which is the only clean ending for an instance not yet
            # proven ours. Killing the worker here would orphan it.
            try:
                open(jobs_file + ".stop", "w").close()
                st["note"] = "stopped by the caller"
                _drive(q, st, {}, chunk, doc_timeout, doc_timeout + QUIT_GRACE_S,
                       hooks, log, rearm=False)
            except BaseException:
                pass
        proven = st["ours"] if st["verified"] else 0
        if not st["eof"]:
            # A hang (or this side failed). Record what Word is showing, then
            # end the worker and the instance -- the instance only if it is
            # proven ours. The instance runs with Visible = False, so ANY
            # visible window it owns is a dialog waiting for a person: that
            # stops the sweep instead of being retried.
            # Titles are read from the new instance even before its window
            # proved it ours (a startup dialog comes before any document);
            # killing still needs the proof.
            titles = hooks.window_titles(proven or st["ours"]) if (proven or st["ours"]) else []
            if st["ours"] and not proven:
                st["note"] = ("instance %d not proven ours, left for a person to close; "
                              % st["ours"]) + st["note"]
            current = st["current"]
            what = ("document %s" % os.path.basename(current)) if current else (
                "startup" if not st["started"] else "quit")
            if current:
                results[current] = {"error": "timeout after %ds in Word%s" % (
                    doc_timeout, (" (windows: %s)" % "; ".join(titles)) if titles else ""),
                    "hang": True}
            st["note"] = st["note"] or "hang during %s" % what
            if titles:
                dialog = "Word showed a window titled %r during %s" % ("; ".join(titles), what)
            try:
                proc.kill()
            except OSError:
                pass
            if proven and not st["foreign"]:
                hooks.kill_pid(proven)
        try:
            proc.wait(timeout=QUIT_GRACE_S)
        except Exception:
            try:
                proc.kill()
            except OSError:
                pass
        if proven and not st["foreign"]:
            t_end = hooks.clock() + QUIT_GRACE_S
            while hooks.pid_alive(proven) and hooks.clock() < t_end:
                hooks.sleep(0.5)
            if hooks.pid_alive(proven):
                log("word: instance %d outlived Quit(); ending it" % proven)
                hooks.kill_pid(proven)
        elif st["started"] and not proven:
            log("word: instance not proven ours; quit through COM only, never killed")
    return {"results": results, "started": st["started"], "foreign": st["foreign"],
            "note": st["note"], "dialog": dialog, "pid": st["ours"],
            "verified": st["verified"]}


def _drive(q, st, results, chunk, doc_timeout, start_timeout, hooks, log, rearm=True):
    """Follow the worker's protocol lines until it exits (st['eof']) or a
    deadline passes (st['expired']). A deadline is armed for startup, for every
    document and for each gap between documents, so nothing can wait forever.
    With `rearm` False the first deadline is the only one (draining a worker
    that was asked to stop)."""
    deadline = hooks.clock() + start_timeout

    def arm(seconds):
        return hooks.clock() + seconds if rearm else deadline
    while True:
        try:
            line = q.get(timeout=min(max(0.05, deadline - hooks.clock()), 1.0))
        except queue.Empty:
            line = ""
        if line is None:
            st["eof"] = True
            return
        if not line:
            if hooks.clock() >= deadline:
                st["expired"] = True
                return
            continue
        log("word: " + line)
        head, _, rest = line.partition(" ")
        if head == "PID":
            st["ours"] = int(rest)
        elif head in ("PIDAMBIGUOUS", "MISMATCH"):
            st["ours"], st["verified"] = 0, False
        elif head == "VERIFIED":
            st["verified"] = st["ours"] != 0 and int(rest) == st["ours"]
        elif head == "ENV":
            st["started"] = True
            st["version"] = rest.split(" ")[0]
            deadline = arm(GAP_TIMEOUT_S)
        elif head == "BEGIN":
            st["started"] = True
            st["current"] = chunk[int(rest)][0]
            st["opened"] = None
            deadline = arm(doc_timeout)
        elif head == "OPENED":
            i, _, mode = rest.partition(" ")
            st["opened"] = int(mode) if mode.strip().lstrip("-").isdigit() else 0
        elif head == "DONE":
            i, pages, ms = rest.split()
            docx, pdf = chunk[int(i)]
            results[docx] = {"pdf": pdf, "pages": int(pages),
                             "render_s": round(int(ms) / 1000.0, 2),
                             "opened": True, "compat_mode": st.get("opened"),
                             "word_version": st.get("version"),
                             "repair_prompt": False}
            st["current"] = None
            deadline = arm(GAP_TIMEOUT_S)
        elif head == "FAIL":
            i, _, msg = rest.partition(" ")
            results[chunk[int(i)][0]] = {
                "error": "word: " + msg[:300], "opened": st.get("opened") is not None,
                "compat_mode": st.get("opened"), "word_version": st.get("version"),
                "repair_prompt": bool(_REPAIR.search(msg))}
            st["current"] = None
            deadline = arm(GAP_TIMEOUT_S)
        elif head == "SESSIONFAIL":
            st["note"] = rest
        elif head in ("FOREIGN", "FOREIGNKEPT"):
            st["foreign"] = True


# ------------------------------------------------------- fonts a tester has
# What a stock Windows + Office machine can render: the ratified beta bar's
# own list (testkit/beta_readiness.py, criterion 10), so the Word lane and the
# bar cannot disagree about which family a tester lacks. The machine this runs
# on is not stock -- it holds 310 families, Carlito, Caladea, Liberation,
# DejaVu and Noto among them (LibreOffice installs them) -- so a Word render
# here can be kinder than a tester's; `stock_view` takes that kindness away.
def _stock_fonts():
    import beta_readiness
    return frozenset(s.lower() for s in beta_readiness.STOCK_FONTS)


STOCK_FONTS = _stock_fonts()
_FONT_PARTS = ("word/document.xml", "word/styles.xml", "word/numbering.xml",
               "word/footnotes.xml", "word/endnotes.xml")
_FONT_ATTRS = ("ascii", "hAnsi", "cs", "eastAsia")


def _font_parts(names):
    import re
    return [n for n in names if n in _FONT_PARTS
            or re.match(r"word/(header|footer)\d*\.xml$", n)]


def _slot(ch):
    """The rFonts slot Word draws `ch` with: complex scripts (Hebrew, Arabic,
    Indic, Thai) take cs, CJK takes eastAsia, everything else ascii/hAnsi."""
    o = ord(ch)
    if 0x0590 <= o <= 0x08FF or 0x0900 <= o <= 0x0DFF or 0x0E00 <= o <= 0x0EFF \
            or 0xFB1D <= o <= 0xFDFF or 0xFE70 <= o <= 0xFEFF:
        return "cs"
    if 0x2E80 <= o <= 0x9FFF or 0xAC00 <= o <= 0xD7AF or 0xF900 <= o <= 0xFAFF \
            or 0xFF00 <= o <= 0xFFEF or 0x20000 <= o <= 0x2FFFF:
        return "eastAsia"
    return "ascii"


def declared_fonts(docx_path):
    """{family: characters set in it} for every family the DOCX names.

    Each character is counted against the slot Word draws it with (`_slot`);
    a family named only in a style, an unused slot or the font table counts 0
    but is still listed, because Word still has to resolve it."""
    import zipfile
    from lxml import etree
    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    out = {}
    with zipfile.ZipFile(docx_path) as z:
        names = z.namelist()
        for part in _font_parts(names):
            root = etree.fromstring(z.read(part))
            for rf in root.iter(W + "rFonts"):
                for a in _FONT_ATTRS:
                    v = rf.get(W + a)
                    if v:
                        out.setdefault(v, 0)
            for r in root.iter(W + "r"):
                rpr = r.find(W + "rPr")
                rf = rpr.find(W + "rFonts") if rpr is not None else None
                if rf is None:
                    continue
                for t in r.iter(W + "t"):
                    for ch in t.text or "":
                        face = rf.get(W + _slot(ch)) or rf.get(W + "ascii")
                        if face:
                            out[face] = out.get(face, 0) + 1
        if "word/fontTable.xml" in names:
            for f in etree.fromstring(z.read("word/fontTable.xml")).iter(W + "font"):
                out.setdefault(f.get(W + "name"), 0)
    return out


def absent_fonts(fonts):
    """The families of `fonts` a stock Windows + Office machine does not have."""
    return sorted(f for f in fonts if f and f.lower() not in STOCK_FONTS)


def absent_name(family):
    """The name a stock view gives `family`: one no installed font can match.

    Word's font lookup is looser than an exact name. "Noto Serif (absent)"
    and "David (absent)" were both drawn in the installed Noto Serif and
    David (Word 16.0.20430, 2026-10-05), so the suffix simulated nothing; the
    name must share no prefix with any real family."""
    import zlib
    return "XQZ%08X" % (zlib.crc32(family.encode("utf-8")) & 0xFFFFFFFF)


def stock_view(docx_in, docx_out):
    """A copy of the DOCX as a stock machine resolves it.

    Every family outside STOCK_FONTS is renamed (`absent_name`) in the runs,
    styles, numbering, notes, headers, footers and font table. The font
    table keeps its family / pitch / charset hints, which are what Word's
    substitution reads when a face is missing -- so Word here picks the
    substitute a tester's Word would, whatever this machine has installed.
    Returns the renamed families."""
    import zipfile
    from lxml import etree
    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    absent = set(absent_fonts(declared_fonts(docx_in)))
    with zipfile.ZipFile(docx_in) as zi, zipfile.ZipFile(docx_out, "w",
                                                         zipfile.ZIP_DEFLATED) as zo:
        parts = set(_font_parts(zi.namelist())) | {"word/fontTable.xml"}
        for item in zi.infolist():
            data = zi.read(item.filename)
            if absent and item.filename in parts:
                root = etree.fromstring(data)
                for rf in root.iter(W + "rFonts"):
                    for a in _FONT_ATTRS:
                        v = rf.get(W + a)
                        if v in absent:
                            rf.set(W + a, absent_name(v))
                for f in root.iter(W + "font"):
                    if f.get(W + "name") in absent:
                        for alt in f.findall(W + "altName"):
                            f.remove(alt)        # an alias would find it again
                        f.set(W + "name", absent_name(f.get(W + "name")))
                data = etree.tostring(root, xml_declaration=True, encoding="UTF-8",
                                      standalone=True)
            zo.writestr(item, data)
    return sorted(absent)


def with_compat_mode(docx_in, docx_out, mode):
    """A copy with w:compatSetting compatibilityMode set to `mode` (an A/B
    knob: Word lays a mode-14 document out by Word 2010's rules)."""
    import re
    import zipfile
    with zipfile.ZipFile(docx_in) as zi, zipfile.ZipFile(docx_out, "w",
                                                         zipfile.ZIP_DEFLATED) as zo:
        for item in zi.infolist():
            data = zi.read(item.filename)
            if item.filename == "word/settings.xml":
                data = re.sub(rb'(w:name="compatibilityMode"[^>]*w:val=")\d+(")',
                              rb"\g<1>%d\g<2>" % mode, data)
            zo.writestr(item, data)


# ---------------------------------------------------------------- the sweep
def _score(args):
    """Score one Word render (runs in a worker process)."""
    src, docx, pdf, work = args
    import harness
    import quality_sweep as qs
    row = {}
    res = harness.evaluate(src, docx, work, save_images=False, rendered_pdf=pdf)
    if "error" in res:
        row["error"] = res["error"]
        return row
    row.update({k: res.get(k) for k in ROW_KEYS})
    row["char_recall"], row["char_doc_recall"] = qs.char_recall(src, pdf)
    row["page_dy_p90"] = res.get("page_dy_p90")
    row["scorer"] = harness.HARNESS_READING      # the reading, as rescore.py records it
    return row


def _docx_for(docx_dir, stem):
    for cand in (os.path.join(docx_dir, stem, stem + ".docx"),
                 os.path.join(docx_dir, stem + ".docx")):
        if os.path.exists(cand):
            return cand
    return None


# ------------------------------------------------------------ one batch at a time
# Two Word batches on one machine fight over Word itself (and over the person
# at the keyboard). Agents agreed on C:\lotmp\word.lock by hand; WP43 makes it
# the oracle's own job: a named kernel mutex held for the whole batch, plus the
# old lock file, still honoured and still written, for agents on older trees.
WORD_MUTEX = "Global\\exactdoc-word-oracle"
WORD_LOCK_FILE = os.environ.get("EXACTDOC_WORD_LOCK", r"C:\lotmp\word.lock")
LOCK_FRESH_S = 30 * 60          # a lock file younger than this is honoured
LOCK_WAIT_S = float(os.environ.get("EXACTDOC_WORD_LOCK_WAIT_S", 3 * 3600))
LOCK_POLL_S = 15


class WordBusy(RuntimeError):
    """Another Word batch holds the machine, and it did not finish in time."""


class WordBatchLock(object):
    """`with WordBatchLock(): ...` -- exclusive use of Word for one batch.

    * The mutex (Windows CreateMutexW; `Global\\` namespace, `Local\\` if that
      is refused) is held for the whole batch; a process that dies holding it
      abandons it, and the next waiter takes it.
    * The lock file is for agents that only know the file: one that exists,
      is younger than LOCK_FRESH_S and is not ours is waited for; then ours is
      written (our token inside). On exit it is deleted only if it still holds
      our token -- a lock file someone else created is never deleted.
    Waits up to LOCK_WAIT_S in all, then raises WordBusy. `clock`, `sleep` and
    `say` are for tests.
    """

    def __init__(self, path=None, mutex=WORD_MUTEX, wait_s=None, poll_s=LOCK_POLL_S,
                 fresh_s=LOCK_FRESH_S, clock=time.time, sleep=time.sleep, say=print):
        self.path = path or WORD_LOCK_FILE
        self.mutex_name, self.wait_s = mutex, LOCK_WAIT_S if wait_s is None else wait_s
        self.poll_s, self.fresh_s = poll_s, fresh_s
        self.clock, self.sleep, self.say = clock, sleep, say
        self.token = "word_oracle pid=%d token=%s" % (os.getpid(), os.urandom(6).hex())
        self._handle = None
        self.wrote_file = False

    # -- the mutex
    def _kernel32(self):
        if os.name != "nt" or not self.mutex_name:
            return None
        import ctypes
        from ctypes import wintypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateMutexW.restype = wintypes.HANDLE
        k.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
        k.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        k.ReleaseMutex.argtypes = (wintypes.HANDLE,)
        k.CloseHandle.argtypes = (wintypes.HANDLE,)
        return k

    def _acquire_mutex(self, deadline):
        k = self._kernel32()
        if k is None:
            return
        handle = k.CreateMutexW(None, False, self.mutex_name)
        if not handle and self.mutex_name.startswith("Global\\"):
            self.mutex_name = "Local\\" + self.mutex_name[len("Global\\"):]
            handle = k.CreateMutexW(None, False, self.mutex_name)
        if not handle:
            raise OSError("CreateMutexW(%s) failed" % self.mutex_name)
        said = False
        while True:
            left = max(0, deadline - self.clock())
            r = k.WaitForSingleObject(handle, int(min(left, self.poll_s) * 1000))
            if r in (0x0, 0x80):             # WAIT_OBJECT_0, WAIT_ABANDONED
                self._handle = (k, handle)
                return
            if self.clock() >= deadline:
                k.CloseHandle(handle)
                raise WordBusy("another Word batch holds %s" % self.mutex_name)
            if not said:
                self.say("waiting for another Word batch (mutex %s)" % self.mutex_name)
                said = True

    def _release_mutex(self):
        if self._handle:
            k, handle = self._handle
            k.ReleaseMutex(handle)
            k.CloseHandle(handle)
            self._handle = None

    # -- the file
    def _read(self):
        try:
            with open(self.path, encoding="utf-8", errors="replace") as fh:
                return fh.read().strip()
        except OSError:
            return None

    def _acquire_file(self, deadline):
        said = False
        while True:
            try:
                age = self.clock() - os.path.getmtime(self.path)
            except OSError:
                age = None                                  # no lock file
            held = self._read()
            if age is None or age >= self.fresh_s or held == self.token:
                break
            if self.clock() >= deadline:
                raise WordBusy("%s is held (%s, %.0f s old)" % (self.path, held, age))
            if not said:
                self.say("waiting for %s (%s, %.0f s old)" % (self.path, held, age))
                said = True
            self.sleep(self.poll_s)
        d = os.path.dirname(self.path)
        if d:
            os.makedirs(d, exist_ok=True)
        tmp = "%s.%d.tmp" % (self.path, os.getpid())
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(self.token + "\n")
        os.replace(tmp, self.path)
        self.wrote_file = True

    def _release_file(self):
        if self.wrote_file and self._read() == self.token:
            try:
                os.remove(self.path)
            except OSError:
                pass
        self.wrote_file = False

    def __enter__(self):
        deadline = self.clock() + self.wait_s
        self._acquire_mutex(deadline)
        try:
            self._acquire_file(deadline)
        except BaseException:
            self._release_mutex()
            raise
        return self

    def __exit__(self, *exc):
        try:
            self._release_file()
        finally:
            self._release_mutex()
        return False


def sweep(out, docx_dir=None, profile=None, lane=None, corpus="both", only=None,
          include_unsupported=False, jobs=4, doc_timeout=DOC_TIMEOUT_S, batch=BATCH,
          stock_fonts=False, compat_mode=None, lock=None):
    """`_sweep` holding Word for the whole batch (WordBatchLock, WP43): the
    named mutex and C:\\lotmp\\word.lock. `lock` is for tests."""
    if not available():
        raise WordUnavailable("Microsoft Word is not available on this machine")
    with (lock if lock is not None else WordBatchLock()):
        return _sweep(out, docx_dir=docx_dir, profile=profile, lane=lane, corpus=corpus,
                      only=only, include_unsupported=include_unsupported, jobs=jobs,
                      doc_timeout=doc_timeout, batch=batch, stock_fonts=stock_fonts,
                      compat_mode=compat_mode)


def _sweep(out, docx_dir=None, profile=None, lane=None, corpus="both", only=None,
           include_unsupported=False, jobs=4, doc_timeout=DOC_TIMEOUT_S, batch=BATCH,
           stock_fonts=False, compat_mode=None):
    """Render every selected document's DOCX in Word and score it.

    DOCX come from `docx_dir` (a quality_sweep KEEP_DOCX tree, so Word sees the
    very bytes the canonical LibreOffice lane measured) or are converted here
    with `profile`. `stock_fonts` renders each through `stock_view` -- what a
    tester without this machine's extra families sees; `compat_mode` renders
    each with that compatibility mode (an A/B knob). Every row carries the
    font census (`fonts_absent`, `absent_char_frac`). Rows go to
    OUT/rows.jsonl as each document finishes; documents already there are
    skipped, so an interrupted sweep resumes.
    """
    from concurrent.futures import ProcessPoolExecutor
    import quality_sweep as qs
    if not available():
        raise WordUnavailable("Microsoft Word is not available on this machine")
    os.makedirs(out, exist_ok=True)
    rows_path = os.path.join(out, "rows.jsonl")
    done = set()
    if os.path.exists(rows_path):
        with open(rows_path, encoding="utf-8") as f:
            done = {json.loads(l)["doc"] for l in f if l.strip()}
    docs = [d for d in qs.select(corpus, only, include_unsupported) if d[0] not in done]
    lane = lane or profile or "docx"
    variant_dir = os.path.join(out, "_docx")
    os.makedirs(variant_dir, exist_ok=True)
    rows, pairs, meta = [], [], {}
    for doc_id, path, tier, _dialect in docs:
        stem = os.path.splitext(doc_id)[0]
        # "lane": "word" is how testkit/beta_readiness.py tells a Word row from
        # a Google Docs one; the DOCX flavour rides beside it
        row = {"doc": doc_id, "tier": tier, "lane": "word", "flavour": lane,
               "renderer": "word", "opened": False, "repair_prompt": False}
        t0 = time.monotonic()
        if docx_dir:
            docx = _docx_for(docx_dir, stem)
            row["convert_s"] = None
            if not docx:
                row["error"] = "no DOCX in the supplied tree (refused or failed upstream)"
                rows.append(row)
                continue
        else:
            from exactdoc.convert import convert
            from exactdoc.errors import ExactdocError
            docx = os.path.join(variant_dir, stem + ".docx")
            try:
                convert(path, docx, options=qs._profile(profile), max_pages=0)
            except ExactdocError as e:
                row["refused"] = type(e).__name__
                rows.append(row)
                continue
            except Exception as e:
                row["error"] = "convert %s: %s" % (type(e).__name__, str(e)[:200])
                rows.append(row)
                continue
            row["convert_s"] = round(time.monotonic() - t0, 1)
        fonts = declared_fonts(docx)
        gone = absent_fonts(fonts)
        row["fonts_absent"] = gone
        total = sum(fonts.values())
        row["absent_char_frac"] = round(sum(fonts[f] for f in gone) / total, 4) if total else 0.0
        # Word is handed a copy under OUT, never the source tree's own path:
        # Word refuses a path over ~218 characters ("Sorry, we couldn't find
        # your file ... .doc", the name cut short), and a KEEP_DOCX tree under
        # a scratch directory reaches 250 (2026-10-05, 5 of 93 product DOCX).
        rendered = os.path.join(variant_dir, stem + ".word-in.docx")
        if compat_mode:
            with_compat_mode(docx, rendered, compat_mode)
        else:
            shutil.copyfile(docx, rendered)
        if stock_fonts:
            tmp = rendered + ".tmp.docx"
            stock_view(rendered, tmp)
            os.replace(tmp, rendered)
        pdf = os.path.join(out, stem + ".word.pdf")
        pairs.append((rendered, pdf))
        meta[os.path.abspath(rendered)] = (row, path, docx, t0)

    def write(row):
        with open(rows_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        print(row["doc"], {k: row.get(k) for k in (
            "src_pages", "out_pages", "word_recall", "char_recall", "within2pt", "error")},
            flush=True)

    def collect(futures, block):
        for fut in [f for f in futures if block or f.done()]:
            row, t0 = futures.pop(fut)
            try:
                row.update(fut.result())
            except Exception as e:
                row["error"] = "score %s: %s" % (type(e).__name__, str(e)[:200])
                row["trace"] = traceback.format_exc()[-600:]
            row["total_s"] = round(time.monotonic() - t0, 1)
            write(row)

    for row in rows:
        write(row)
    futures = {}
    work = os.path.join(out, "_work")
    with ProcessPoolExecutor(max_workers=jobs) as ex:
        def on_result(rendered, res):
            row, src, docx, t0 = meta[rendered]
            for k in ("opened", "repair_prompt", "compat_mode", "word_version"):
                if k in res:
                    row[k] = res[k]
            if "error" in res:
                row["error"] = res["error"]
                if res.get("hang"):
                    row["hang"] = True
                row["total_s"] = round(time.monotonic() - t0, 1)
                write(row)
            else:
                row["word_pages"] = res["pages"]
                row["render_s"] = res["render_s"]
                # scored against the DOCX as written: live text is a property
                # of the conversion, not of the font names Word was handed
                futures[ex.submit(_score, (src, docx, res["pdf"],
                                           os.path.join(work, row["doc"])))] = (row, t0)
            collect(futures, block=False)
        try:
            render(pairs, os.path.join(out, "_word"), doc_timeout=doc_timeout,
                   batch=batch, on_result=on_result, log=lambda s: None)
        finally:
            collect(futures, block=True)
    return rows_path


# ------------------------------------------------------------- the beta bar
def load_rows(path):
    with open(path, encoding="utf-8") as f:
        rows = [json.loads(l) for l in f if l.strip()]
    last = {}
    for r in rows:                      # a re-run row supersedes an earlier one
        last[r["doc"]] = r
    return [last[k] for k in sorted(last)]


def summarise(rows, worst=8):
    """The beta-bar shape: ordinary_digital page-exact, the share of documents
    with char_recall >= 0.95, the worst documents, and crashes/hangs."""
    ok = [r for r in rows if "src_pages" in r and r.get("src_pages")]
    od = [r for r in ok if r.get("tier", "ordinary_digital") == "ordinary_digital"]
    cr = [r for r in ok if r.get("char_recall") is not None]
    s = {"documents": len(rows), "measured": len(ok),
         "errors": sum(1 for r in rows if "error" in r and not r.get("hang")),
         "hangs": sum(1 for r in rows if r.get("hang")),
         "refused": sum(1 for r in rows if "refused" in r),
         "page_exact": sum(1 for r in ok if r["src_pages"] == r["out_pages"]),
         "ordinary_digital": len(od),
         "ordinary_digital_page_exact": sum(1 for r in od if r["src_pages"] == r["out_pages"]),
         "char_recall_ge_095": sum(1 for r in cr if r["char_recall"] >= 0.95),
         "char_recall_measured": len(cr)}
    s["char_recall_ge_095_share"] = round(s["char_recall_ge_095"] / max(1, len(cr)), 3)
    for k in ("word_recall", "char_recall", "within2pt", "mean_ssim"):
        v = [r[k] for r in ok if r.get(k) is not None]
        if v:
            s["mean_" + k.replace("mean_", "")] = round(sum(v) / len(v), 4)
    s["sum_abs_page_err"] = round(sum(abs(r["out_pages"] / r["src_pages"] - 1) for r in ok), 3)
    bad = sorted(ok, key=lambda r: ((r.get("char_recall") or 0)
                                    - abs(r["out_pages"] / r["src_pages"] - 1)))
    s["worst"] = [{"doc": r["doc"], "pages": "%d/%d" % (r["out_pages"], r["src_pages"]),
                   "char_recall": r.get("char_recall")} for r in bad[:worst]]
    s["failed"] = [{"doc": r["doc"], "error": r["error"][:120]} for r in rows if "error" in r]
    return s


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sw = sub.add_parser("sweep", help="render and score a corpus through Word")
    sw.add_argument("out")
    src = sw.add_mutually_exclusive_group(required=True)
    src.add_argument("--docx-dir", help="a quality_sweep KEEP_DOCX profile tree")
    src.add_argument("--profile", choices=("raw", "product", "gdocs"),
                     help="convert here with this profile instead")
    sw.add_argument("--lane", default=None, help="label written into each row")
    sw.add_argument("--corpus", choices=("gated", "expansion", "both"), default="both")
    sw.add_argument("--only", nargs="+", default=None)
    sw.add_argument("--include-unsupported", action="store_true",
                    help="also the documents the converter must refuse (as quality_sweep)")
    sw.add_argument("--jobs", type=int, default=4, help="scoring processes")
    sw.add_argument("--timeout", type=int, default=DOC_TIMEOUT_S, help="per document, s")
    sw.add_argument("--batch", type=int, default=BATCH, help="documents per Word session")
    sw.add_argument("--stock-fonts", action="store_true",
                    help="render as a stock Windows + Office machine resolves fonts")
    sw.add_argument("--compat-mode", type=int, default=None,
                    help="render with this w:compatibilityMode (A/B)")
    sm = sub.add_parser("summary", help="the beta-bar numbers of a rows.jsonl")
    sm.add_argument("rows")
    a = ap.parse_args(argv)
    if a.cmd == "summary":
        print(json.dumps(summarise(load_rows(a.rows)), indent=1))
        return 0
    if not available():
        print("word_oracle: SKIP -- Microsoft Word is not available here "
              "(Windows with desktop Word only)")
        return 0
    tmp = os.environ.get("EXACTDOC_WORD_TMP")
    if tmp:                              # keep LibreOffice's profile path short
        os.makedirs(tmp, exist_ok=True)
        os.environ["TEMP"] = os.environ["TMP"] = tmp
        tempfile.tempdir = tmp
    try:
        path = sweep(a.out, docx_dir=a.docx_dir, profile=a.profile, lane=a.lane,
                     corpus=a.corpus, only=a.only, jobs=a.jobs, doc_timeout=a.timeout,
                     batch=a.batch, stock_fonts=a.stock_fonts, compat_mode=a.compat_mode,
                     include_unsupported=a.include_unsupported)
    except WordDialog as e:
        print("word_oracle: STOPPED -- Word needs a human: %s" % e)
        return 3
    print(json.dumps(summarise(load_rows(path)), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
