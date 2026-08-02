"""Focused safety checks for open-loop bottom-margin relief.

    python tests/test_bottom_margin_relief.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from exactdoc.backend import get_backend  # noqa: E402
from exactdoc.infer import _can_relax_bottom_margin, infer  # noqa: E402

FAILED = []


def check(name, condition, detail=""):
    print("  %-4s %s%s" % ("ok" if condition else "FAIL", name,
                           "" if condition else "   <-- " + detail))
    if not condition:
        FAILED.append(name)


def layout(name):
    path = os.path.join(ROOT, "testkit", "fixtures", name + ".pdf")
    return infer(get_backend("pdfium").parse_pdf(path, keep_image_data=True))


def test_plain_flow_documents_receive_relief():
    for name in ("c1_whitepaper", "c2_paper2col"):
        lay = layout(name)
        check("%s is safe plain flow" % name, _can_relax_bottom_margin(lay))
        check("%s uses the bounded 14pt reserve" % name,
              lay.margin_b == 14.0, str(lay.margin_b))


def test_graphic_overlap_documents_keep_inferred_margin():
    for name in ("c3_tables", "c5_graphics"):
        lay = layout(name)
        check("%s graphic overlap disables relief" % name,
              not _can_relax_bottom_margin(lay))
        check("%s retains more than 14pt reserve" % name,
              lay.margin_b > 14.0, str(lay.margin_b))


def main():
    tests = [value for key, value in sorted(globals().items())
             if key.startswith("test_")]
    print("bottom-margin relief tests (%d)" % len(tests))
    for test in tests:
        print("\n%s" % test.__name__)
        test()
    print("\n%s" % ("all clear" if not FAILED else "%d FAILED: %s" %
                       (len(FAILED), ", ".join(FAILED))))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
