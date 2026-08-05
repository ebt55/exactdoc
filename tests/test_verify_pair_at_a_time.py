"""`verify.compare` scores one page pair at a time, not both documents at once.

It used to rasterise every page of the source and every page of the render
before comparing any of them, releasing nothing until the loop ended -- so the
cost was (src_pages + out_pages) x 20.7 MB held simultaneously, a property of
the documents rather than of the comparison, which only ever looks at page i
against page i.

`testkit/harness.py` carried the identical shape and was fixed in b0762a2,
where it had been OOM-killed on a 126-page source against a 591-page render
after asking for 19.5 GB. The difference is that this module SHIPS: it is what
`--verify` runs for a user on their own document.

The numbers must not move. These tests pin the rows against a reference
implementation of the old whole-document shape, and pin the lifetime change
separately by watching the order of renders and comparisons.

    python tests/test_verify_pair_at_a_time.py
"""
import io
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np                                            # noqa: E402

from exactdoc import verify                                   # noqa: E402


def _png(w, h, shade):
    import PIL.Image as Image
    buf = io.BytesIO()
    Image.fromarray(np.full((h, w, 3), shade, dtype=np.uint8)).save(buf, "PNG")
    return buf.getvalue()


class FakeBackend:
    """Two documents of arbitrary length, with a recorded event log.

    `refuse` makes render_page return nothing from that page on, which is the
    other way `_page_arrays` used to end a document.
    """

    def __init__(self, pages, refuse=None, size=(24, 32)):
        self.pages = dict(pages)          # path -> page count
        self.refuse = refuse or {}        # path -> first refused index
        self.size = size
        self.events = []

    def page_lines(self, path):
        return [[] for _ in range(self.pages[path])]

    def render_page(self, path, page_no, dpi=96):
        i = page_no - 1
        r = self.refuse.get(path)
        if r is not None and i >= r:
            return None
        self.events.append(("render", path, i))
        shade = 40 if path.endswith("src.pdf") else 200
        return _png(self.size[0], self.size[1], shade + (i % 3))


def _reference_rows(src, out, backend, dpi=96):
    """The shape the module had before: materialise both, then compare."""
    A = verify._page_arrays(src, dpi, backend=backend)
    B = verify._page_arrays(out, dpi, backend=backend)
    rows = []
    for i in range(max(len(A), len(B))):
        a = A[i] if i < len(A) else None
        b = B[i] if i < len(B) else None
        if a is None or b is None:
            rows.append({"page": i + 1, "ssim": 0.0,
                         "note": "page count mismatch"})
            continue
        h = max(a.shape[0], b.shape[0])
        w = max(a.shape[1], b.shape[1])
        a2, b2 = verify._pad_to(a, h, w), verify._pad_to(b, h, w)
        rows.append({"page": i + 1, "ssim": round(verify.ssim(a2, b2), 4),
                     "mad": round(float(np.abs(a2 - b2).mean()), 2)})
    return rows


SRC, OUT = "/x/src.pdf", "/x/out.pdf"


class TheNumbersDoNotMove(unittest.TestCase):
    """Same arrays, same order, same rows -- only the lifetime changed."""

    def _both(self, pages, refuse=None):
        a = FakeBackend(pages, refuse)
        b = FakeBackend(pages, refuse)
        return (verify.compare(SRC, OUT, backend=a),
                _reference_rows(SRC, OUT, b))

    def test_equal_page_counts(self):
        got, want = self._both({SRC: 5, OUT: 5})
        self.assertEqual(got, want)
        self.assertEqual(len(got), 5)

    def test_render_longer_than_source(self):
        got, want = self._both({SRC: 2, OUT: 6})
        self.assertEqual(got, want)
        self.assertEqual([r["page"] for r in got], [1, 2, 3, 4, 5, 6])
        self.assertEqual([r.get("note") for r in got[2:]],
                         ["page count mismatch"] * 4)

    def test_source_longer_than_render(self):
        got, want = self._both({SRC: 6, OUT: 2})
        self.assertEqual(got, want)

    def test_a_backend_that_stops_rendering_mid_document(self):
        # `_page_arrays` broke at the first refusal, which truncated that
        # document. Each side must still end on its own refusal.
        got, want = self._both({SRC: 6, OUT: 6}, refuse={OUT: 3})
        self.assertEqual(got, want)
        self.assertEqual(len(got), 6)

    def test_both_sides_refuse(self):
        got, want = self._both({SRC: 6, OUT: 6}, refuse={SRC: 2, OUT: 4})
        self.assertEqual(got, want)

    def test_a_single_page_document(self):
        got, want = self._both({SRC: 1, OUT: 1})
        self.assertEqual(got, want)

    def test_an_empty_document_produces_no_rows(self):
        self.assertEqual(verify.compare(SRC, OUT,
                                        backend=FakeBackend({SRC: 0, OUT: 0})),
                         [])


class TheLifetimeChanged(unittest.TestCase):
    """The point of the change, asserted rather than described."""

    def _trace(self, pages):
        bk = FakeBackend(pages)
        real = verify.ssim

        def spy(a, b):
            bk.events.append(("compare", None, None))
            return real(a, b)

        verify.ssim = spy
        try:
            verify.compare(SRC, OUT, backend=bk)
        finally:
            verify.ssim = real
        return [e[0] for e in bk.events]

    def test_renders_and_comparisons_interleave(self):
        kinds = self._trace({SRC: 8, OUT: 8})
        # Before: eight renders, eight renders, then eight comparisons.
        self.assertEqual(kinds,
                         ["render", "render", "compare"] * 8)

    def test_at_most_one_pair_is_rendered_before_the_first_comparison(self):
        kinds = self._trace({SRC: 40, OUT: 40})
        self.assertEqual(kinds.index("compare"), 2,
                         "a whole document was rasterised before scoring "
                         "anything again")

    def test_the_page_count_is_read_once_per_document(self):
        # _page_count goes through page_lines, which extracts text for the
        # WHOLE document. Calling it per page would trade memory for a far
        # worse cost.
        calls = []
        bk = FakeBackend({SRC: 12, OUT: 12})
        real = bk.page_lines
        bk.page_lines = lambda p: (calls.append(p), real(p))[1]
        verify.compare(SRC, OUT, backend=bk)
        self.assertEqual(sorted(calls), [OUT, SRC])


class WholeDocumentHelperStillWorks(unittest.TestCase):
    """`_page_arrays` is kept for callers that want a short document at once."""

    def test_it_returns_every_page(self):
        bk = FakeBackend({SRC: 4, OUT: 4})
        self.assertEqual(len(verify._page_arrays(SRC, 96, backend=bk)), 4)

    def test_it_still_stops_at_the_first_refusal(self):
        bk = FakeBackend({SRC: 9, OUT: 9}, refuse={SRC: 5})
        self.assertEqual(len(verify._page_arrays(SRC, 96, backend=bk)), 5)


if __name__ == "__main__":
    unittest.main()
