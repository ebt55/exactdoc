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
    for name in ("c2_paper2col",):
        lay = layout(name)
        check("%s is safe plain flow" % name, _can_relax_bottom_margin(lay))
        check("%s uses the bounded 14pt reserve" % name,
              lay.margin_b == 14.0, str(lay.margin_b))


def test_cover_band_documents_keep_inferred_margin():
    """c1 declines relief BECAUSE IT HAS A COVER BAND, and that is intended.

    This test used to assert the opposite: that c1 was safe plain flow and took
    the 14pt reserve. `8c79574` ("A band inset by 7pt is still a band, so stop
    requiring it to be flush") changed that, and the expectation here is what
    went stale. Measured at that commit and its parent:

        c9d36df   margin_b 14.0   relax True    cover_band False
        8c79574   margin_b 50.8   relax False   cover_band True, cover_top 7.2

    c1's band is inset by 7.2pt rather than flush to the page edge, so before
    that commit it was not recognised as a band at all. Once it is, the FIRST
    arm of `_can_relax_bottom_margin` declines -- not the graphic-overlap arm,
    which is measured here as not firing on c1 at all. That arm exists because a
    cover has its own vertical coordinate system, so a global bottom-margin
    change is not a safe way to recover ordinary text overflow.

    The 50.8 behaviour is the validated one, not a regression to be undone:
    recognising the band is what made c1 pass live validation (`1f0a27e`,
    "Evidence: live pass 7 passes, and c1's blocker was the band after all"),
    and the canonical gate is green with it. So the contract is pinned in its
    current form, and c2 keeps asserting the relief side so the mechanism stays
    pinned from both directions rather than only from the declining one.
    """
    lay = layout("c1_whitepaper")
    check("c1_whitepaper is recognised as a cover-band document",
          lay.cover_band is not None)
    check("c1_whitepaper declines relief for the cover band",
          not _can_relax_bottom_margin(lay))
    check("c1_whitepaper keeps its inferred bottom margin",
          lay.margin_b > 14.0, str(lay.margin_b))


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
