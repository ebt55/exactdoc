"""Independent fidelity harness for PDF->DOCX converters.

Deliberately shares no code with the converter under test.

Metrics
-------
page_match        pages(src) == pages(rendered)
live_text_cov     3-gram coverage of ALL source text by DOCX *live text*
                  (no figure-region exclusion -- rasterized text counts as LOST)
raster_frac       fraction of source text chars that are NOT live in the docx
word_recall       fraction of source words matched in the render-back PDF
dy_p50/p90        vertical drift of matched words (pt)
dx_p50/p90        horizontal drift
within2/within5   fraction of matched words placed within 2pt / 5pt (euclid)
ssim              8x8 window SSIM at 110 dpi
ink_iou           intersection-over-union of binarized ink pixels
"""
import _paths  # noqa: F401  (sets sys.path, finds soffice/chrome)
import os, re, io, sys, json, shutil, subprocess, tempfile, difflib
from collections import Counter

import fitz
import numpy as np

from _paths import SOFFICE


# ---------------------------------------------------------------- render-back
# One shared LO profile for the whole session: soffice refuses rapid restarts
# with differing profiles and silently exits 0 without writing output.
_PROFILE = os.path.join(tempfile.gettempdir(), "exactdoc_loprof")


def _soffice(args, timeout=900):
    cmd = [SOFFICE, "--headless", "--norestore", "--invisible", "--nolockcheck",
           "-env:UserInstallation=file:///" + _PROFILE.replace("\\", "/")] + args
    return subprocess.run(cmd, capture_output=True, timeout=timeout)


def _pdf_for(docx_path, out_dir):
    return os.path.join(out_dir,
                        os.path.splitext(os.path.basename(docx_path))[0] + ".pdf")


def _is_stale(docx_path, pdf_path):
    """A render is only reusable if it is NEWER than the DOCX it came from.

    Reusing an existing PDF unconditionally silently reports the previous
    run's results after a code change -- which looked exactly like 'the fix
    changed nothing'. Never cache on existence alone.
    """
    if not os.path.exists(pdf_path):
        return True
    return os.path.getmtime(pdf_path) <= os.path.getmtime(docx_path)


def batch_docx_to_pdf(docx_paths, out_dir):
    """Convert many DOCX in one soffice call. Returns {docx: pdf|None}."""
    os.makedirs(out_dir, exist_ok=True)
    todo = list(docx_paths)
    for d in todo:                       # drop stale renders up front
        p = _pdf_for(d, out_dir)
        if os.path.exists(p) and _is_stale(d, p):
            os.remove(p)
    for _ in range(3):
        pending = [d for d in todo if _is_stale(d, _pdf_for(d, out_dir))]
        if not pending:
            break
        _soffice(["--convert-to", "pdf", "--outdir", out_dir] + pending)
    return {d: (None if _is_stale(d, _pdf_for(d, out_dir)) else _pdf_for(d, out_dir))
            for d in todo}


def docx_to_pdf(docx_path, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    out = _pdf_for(docx_path, out_dir)
    if not _is_stale(docx_path, out):
        return out
    if os.path.exists(out):
        os.remove(out)
    for _ in range(3):
        _soffice(["--convert-to", "pdf", "--outdir", out_dir, docx_path])
        if os.path.exists(out):
            return out
    raise RuntimeError("LibreOffice produced no PDF for %s" % docx_path)


# ------------------------------------------------------------------ text side
def docx_live_text(docx_path):
    """All *live* text in a docx: paragraphs, tables (recursive), headers/footers.

    Reads the XML directly so nothing is missed and no library semantics are
    assumed.
    """
    import zipfile
    from lxml import etree
    NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    parts, imgs = [], []
    with zipfile.ZipFile(docx_path) as z:
        names = z.namelist()
        for n in names:
            if n.startswith("word/media/"):
                imgs.append((n, z.getinfo(n).file_size))
        for n in names:
            if not (n == "word/document.xml" or
                    re.match(r"word/(header|footer|footnotes|endnotes)\d*\.xml$", n)):
                continue
            root = etree.fromstring(z.read(n))
            for t in root.iter("{%s}t" % NS["w"]):
                parts.append(t.text or "")
    return "".join(parts), imgs


def pdf_text(pdf_path):
    doc = fitz.open(pdf_path)
    out = []
    for p in doc:
        out.append(p.get_text("text"))
    doc.close()
    return "".join(out)


def norm(t):
    return re.sub(r"\s+", "", t or "")


def gram_cov(src, out, k=3):
    s, o = norm(src), norm(out)
    if len(s) < k:
        return 1.0
    g1 = Counter(s[i:i + k] for i in range(len(s) - k + 1))
    g2 = Counter(o[i:i + k] for i in range(len(o) - k + 1))
    inter = sum(min(c, g2[g]) for g, c in g1.items())
    return inter / max(1, sum(g1.values()))


# ------------------------------------------------------------- geometry side
# Chinese, Japanese and Korean are written without spaces, so a whitespace
# tokeniser returns one "word" per rendered LINE -- up to 32 characters on the
# corpus i18n page. Re-wrap that line one character earlier and the token no
# longer matches anything, although every character survived: c4_i18n scored
# doc_recall 0.8298 on Linux and passed on Windows purely because the two
# renderers broke the line in different places. Measured before the fix: 16 of
# 94 source tokens unmatched, all 16 Hangul/CJK/Kana, zero Latin, zero Arabic,
# zero Hebrew (Arabic and Hebrew DO use spaces and never had the problem).
#
# So runs in these scripts are tokenised per character, with the run's box
# divided evenly across them. It is not a leniency: it counts the same content
# the writer emitted, in the unit that script actually has.
_CONTINUA = ((0x3040, 0x30FF),    # Hiragana + Katakana
             (0x3400, 0x4DBF),    # CJK ext A
             (0x4E00, 0x9FFF),    # CJK unified
             (0xAC00, 0xD7AF),    # Hangul syllables
             (0xF900, 0xFAFF))    # CJK compatibility


def _is_continua(ch):
    o = ord(ch)
    return any(lo <= o <= hi for lo, hi in _CONTINUA)


def _split_continua(text, x0, y0, x1, y1):
    """One token per character when the run has no word boundaries of its own."""
    if not any(_is_continua(c) for c in text):
        return [(text, x0, y0, x1, y1)]
    step = (x1 - x0) / max(1, len(text))
    return [(c, x0 + i * step, y0, x0 + (i + 1) * step, y1)
            for i, c in enumerate(text) if not c.isspace()]


def page_words(pdf_path):
    """[(page_idx, text, x0, y0, x1, y1)] in reading order per page."""
    doc = fitz.open(pdf_path)
    pages = []
    for p in doc:
        ws = p.get_text("words")           # x0,y0,x1,y1,word,block,line,wordno
        ws.sort(key=lambda w: (round(w[1], 1), w[0]))
        out = []
        for w in ws:
            out.extend(_split_continua(w[4], w[0], w[1], w[2], w[3]))
        pages.append(out)
    doc.close()
    return pages


def match_words(src_pages, out_pages):
    """Positional matching, page by page.

    Reading-order alignment breaks on multi-column pages (sorting by y
    interleaves the columns, and a small y shift flips the interleave). So
    match each source word to the *nearest* output word carrying identical
    text, greedily by ascending distance, without replacement.
    """
    drifts, matched, total = [], 0, 0
    for i, sp in enumerate(src_pages):
        total += len(sp)
        if i >= len(out_pages):
            continue
        by_text = {}
        for j, o in enumerate(out_pages[i]):
            by_text.setdefault(o[0], []).append(j)
        cands = []
        for si, s in enumerate(sp):
            for oj in by_text.get(s[0], ()):
                o = out_pages[i][oj]
                d = abs(o[2] - s[2]) * 3 + abs(o[1] - s[1])   # weight dy
                cands.append((d, si, oj))
        cands.sort()
        used_s, used_o = set(), set()
        for d, si, oj in cands:
            if si in used_s or oj in used_o:
                continue
            used_s.add(si); used_o.add(oj)
            s, o = sp[si], out_pages[i][oj]
            matched += 1
            drifts.append((o[1] - s[1], o[2] - s[2], i + 1, s[0]))
    return drifts, matched, total


def doc_word_recall(src_pages, out_pages):
    """Page-agnostic content recall: is the text present anywhere in the doc?"""
    a = Counter(w[0] for p in src_pages for w in p)
    b = Counter(w[0] for p in out_pages for w in p)
    inter = sum(min(c, b[t]) for t, c in a.items())
    return inter / max(1, sum(a.values()))


# --------------------------------------------------------------- pixel side
def page_arrays(pdf_path, dpi=110):
    doc = fitz.open(pdf_path)
    out = []
    for p in doc:
        pix = p.get_pixmap(dpi=dpi, alpha=False)
        a = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        out.append(a[:, :, :3].astype(np.float64))
    doc.close()
    return out


def pad_to(a, h, w):
    o = np.full((h, w, a.shape[2]), 255.0)
    o[:min(h, a.shape[0]), :min(w, a.shape[1]), :] = a[:h, :w, :]
    return o


def ssim(a, b):
    ga, gb = a.mean(2), b.mean(2)
    k = 8
    H, W = (ga.shape[0] // k) * k, (ga.shape[1] // k) * k
    ga = ga[:H, :W].reshape(H // k, k, W // k, k).transpose(0, 2, 1, 3).reshape(-1, k * k)
    gb = gb[:H, :W].reshape(H // k, k, W // k, k).transpose(0, 2, 1, 3).reshape(-1, k * k)
    ma, mb = ga.mean(1), gb.mean(1)
    va, vb = ga.var(1), gb.var(1)
    cov = ((ga - ma[:, None]) * (gb - mb[:, None])).mean(1)
    C1, C2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    s = ((2 * ma * mb + C1) * (2 * cov + C2)) / ((ma ** 2 + mb ** 2 + C1) * (va + vb + C2))
    return float(s.mean())


def ink_iou(a, b, thr=200):
    ga, gb = a.mean(2) < thr, b.mean(2) < thr
    inter = np.logical_and(ga, gb).sum()
    union = np.logical_or(ga, gb).sum()
    return float(inter / max(1, union))


# ------------------------------------------------------------------- runner
def evaluate(src_pdf, docx_path, work_dir, save_images=True, dpi=110, img_dir=None,
             rendered_pdf=None):
    """Score a conversion.

    `rendered_pdf` lets a caller supply a render from somewhere other than the
    LibreOffice proxy -- notably the Google Docs oracle, which is the renderer
    the product actually targets.
    """
    os.makedirs(work_dir, exist_ok=True)
    img_dir = img_dir or work_dir
    if save_images:
        os.makedirs(img_dir, exist_ok=True)
    res = {"src": os.path.basename(src_pdf), "docx": os.path.basename(docx_path)}
    res["docx_bytes"] = os.path.getsize(docx_path)

    live, imgs = docx_live_text(docx_path)
    src_t = pdf_text(src_pdf)
    res["src_chars"] = len(norm(src_t))
    res["live_chars"] = len(norm(live))
    res["live_text_cov"] = round(gram_cov(src_t, live), 4)
    res["raster_frac"] = round(1 - res["live_text_cov"], 4)
    res["n_media"] = len(imgs)
    res["media_bytes"] = sum(s for _, s in imgs)

    try:
        rpdf = rendered_pdf or docx_to_pdf(docx_path, work_dir)
    except Exception as e:
        res["error"] = str(e)[:300]
        return res
    res["render_pdf"] = rpdf
    res["renderer"] = "supplied" if rendered_pdf else "libreoffice"

    s_doc, r_doc = fitz.open(src_pdf), fitz.open(rpdf)
    res["src_pages"], res["out_pages"] = s_doc.page_count, r_doc.page_count
    res["page_match"] = s_doc.page_count == r_doc.page_count
    res["src_pagesize"] = [round(s_doc[0].rect.width, 1), round(s_doc[0].rect.height, 1)]
    res["out_pagesize"] = [round(r_doc[0].rect.width, 1), round(r_doc[0].rect.height, 1)]
    s_doc.close(); r_doc.close()

    sw, ow = page_words(src_pdf), page_words(rpdf)
    drifts, matched, total = match_words(sw, ow)
    res["src_words"] = total
    res["word_recall"] = round(matched / max(1, total), 4)      # right page
    res["doc_recall"] = round(doc_word_recall(sw, ow), 4)       # anywhere
    if drifts:
        dx = np.array([d[0] for d in drifts])
        dy = np.array([d[1] for d in drifts])
        eu = np.hypot(dx, dy)
        res["dx_p50"] = round(float(np.percentile(np.abs(dx), 50)), 2)
        res["dx_p90"] = round(float(np.percentile(np.abs(dx), 90)), 2)
        res["dy_p50"] = round(float(np.percentile(np.abs(dy), 50)), 2)
        res["dy_p90"] = round(float(np.percentile(np.abs(dy), 90)), 2)
        res["within2pt"] = round(float((eu <= 2).mean()), 4)
        res["within5pt"] = round(float((eu <= 5).mean()), 4)
        # worst pages by drift
        bad = {}
        for x, y, pg, w in drifts:
            bad.setdefault(pg, []).append(abs(y))
        res["page_dy_p90"] = {p: round(float(np.percentile(v, 90)), 1)
                              for p, v in sorted(bad.items())}

    A, B = page_arrays(src_pdf, dpi), page_arrays(rpdf, dpi)
    rows = []
    for i in range(max(len(A), len(B))):
        if i >= len(A) or i >= len(B):
            rows.append({"page": i + 1, "ssim": 0.0, "iou": 0.0, "note": "missing"})
            continue
        h = max(A[i].shape[0], B[i].shape[0]); w = max(A[i].shape[1], B[i].shape[1])
        a, b = pad_to(A[i], h, w), pad_to(B[i], h, w)
        rows.append({"page": i + 1, "ssim": round(ssim(a, b), 4),
                     "iou": round(ink_iou(a, b), 4),
                     "mad": round(float(np.abs(a - b).mean()), 2)})
        if save_images:
            import PIL.Image as Image
            gap = 10
            canvas = np.full((h, w * 2 + gap, 3), 180.0)
            canvas[:, :w] = a; canvas[:, w + gap:] = b
            Image.fromarray(canvas.astype(np.uint8)).save(
                os.path.join(img_dir, "cmp_p%02d.png" % (i + 1)))
    res["pages"] = rows
    res["mean_ssim"] = round(float(np.mean([r["ssim"] for r in rows])), 4)
    res["mean_iou"] = round(float(np.mean([r["iou"] for r in rows])), 4)
    return res


def brief(res):
    if "error" in res:
        return "%-34s ERROR %s" % (res["src"], res["error"][:90])
    return ("%-30s pg %s/%s %-4s | live %.3f | keep %.3f | place %.3f | "
            "dy50 %5.1f dy90 %6.1f | <2pt %.2f | ssim %.3f iou %.3f | img %d" % (
                res["src"][:30], res["src_pages"], res["out_pages"],
                "ok" if res["page_match"] else "BAD",
                res["live_text_cov"], res.get("doc_recall", 0),
                res.get("word_recall", 0),
                res.get("dy_p50", -1), res.get("dy_p90", -1),
                res.get("within2pt", 0), res["mean_ssim"], res["mean_iou"],
                res["n_media"]))


if __name__ == "__main__":
    src, docx, work = sys.argv[1], sys.argv[2], sys.argv[3]
    r = evaluate(src, docx, work)
    print(json.dumps({k: v for k, v in r.items() if k != "pages"}, indent=1))
    for row in r.get("pages", []):
        print("  p%-3d ssim %.3f iou %.3f mad %.1f" %
              (row["page"], row["ssim"], row["iou"], row.get("mad", 0)))
    print(brief(r))
