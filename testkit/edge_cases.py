"""Robustness: does convert() survive degenerate / hostile inputs?"""
import _paths  # noqa: F401  (sets sys.path, finds soffice/chrome)
import os, sys, traceback
import fitz

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "edge")
os.makedirs(OUT, exist_ok=True)


def mk(name, fn):
    p = os.path.join(OUT, name + ".pdf")
    d = fitz.open()
    fn(d)
    d.save(p)
    d.close()
    return p


cases = {}
cases["empty_doc"] = mk("empty_doc", lambda d: d.new_page())
cases["no_text_only_image"] = mk("no_text_only_image", lambda d: (
    d.new_page().insert_image(fitz.Rect(50, 50, 550, 700),
                              pixmap=fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 400, 500)))))


def _landscape(d):
    pg = d.new_page(width=792, height=612)
    pg.insert_text((72, 100), "Landscape page with some body text on it.", fontsize=11)


cases["landscape"] = mk("landscape", _landscape)


def _mixed(d):
    a = d.new_page(width=612, height=792)
    a.insert_text((72, 100), "Portrait page one.", fontsize=11)
    b = d.new_page(width=792, height=612)
    b.insert_text((72, 100), "Landscape page two, different geometry.", fontsize=11)
    c = d.new_page(width=842, height=1191)
    c.insert_text((72, 100), "A3 page three.", fontsize=11)


cases["mixed_page_sizes"] = mk("mixed_page_sizes", _mixed)


def _rot(d):
    pg = d.new_page()
    pg.insert_text((72, 300), "Normal horizontal text baseline here.", fontsize=11)
    pg.insert_text((300, 600), "Rotated ninety degrees", fontsize=11, rotate=90)
    pg.insert_text((400, 400), "Upside down text", fontsize=11, rotate=180)


cases["rotated_text"] = mk("rotated_text", _rot)


def _tiny(d):
    pg = d.new_page(width=200, height=150)
    pg.insert_text((10, 30), "Tiny page", fontsize=8)


cases["tiny_page"] = mk("tiny_page", _tiny)


def _huge_text(d):
    pg = d.new_page()
    for i in range(220):
        pg.insert_text((40, 20 + i * 3.4), "dense line %d packed tightly" % i, fontsize=3)


cases["dense_tiny_type"] = mk("dense_tiny_type", _huge_text)

# encrypted
enc = os.path.join(OUT, "encrypted.pdf")
d = fitz.open()
pg = d.new_page()
pg.insert_text((72, 100), "Secret content behind a password.", fontsize=11)
d.save(enc, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="user")
d.close()
cases["encrypted"] = enc

# truncated / corrupt
corrupt = os.path.join(OUT, "corrupt.pdf")
with open(cases["landscape"], "rb") as f:
    data = f.read()
with open(corrupt, "wb") as f:
    f.write(data[:len(data) // 2])
cases["truncated"] = corrupt

from exactdoc.convert import convert
print("%-22s %s" % ("case", "result"))
for name, path in cases.items():
    try:
        o = convert(path, os.path.join(OUT, name + ".docx"))
        sz = os.path.getsize(o)
        import zipfile
        from lxml import etree
        W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        with zipfile.ZipFile(o) as z:
            root = etree.fromstring(z.read("word/document.xml"))
            ntxt = len("".join(t.text or "" for t in root.iter("{%s}t" % W)))
            nsect = len(root.findall(".//{%s}sectPr" % W))
        print("%-22s OK   %6d bytes, %4d chars, %d sect" % (name, sz, ntxt, nsect))
    except Exception as e:
        print("%-22s FAIL %s: %s" % (name, type(e).__name__, str(e)[:70]))
