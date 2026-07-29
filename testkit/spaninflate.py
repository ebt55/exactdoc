"""Per source page: how much taller is its content in the render?

No classification, no buckets -- deliberately. Its predecessor, heightdiff's
--summary, bucketed each injection by whichever construct sat in the interval
and reported "65% between paragraphs (space_before)". That was wrong: it
labels WHERE a paragraph boundary is, not the MECHANISM, and the space_before
values in those intervals turned out to be 0-10pt. A crude measurement that
names a cause is worse than one that only names a location.

This one measures the thing itself: first and last matched line of each source
page, source span vs rendered span (continuous scroll). A page whose content
grows past the usable height overflows, and with a hard break per source page
each overflow costs a whole page.

CAVEAT, and it matters: a rendered span far larger than a page height means
the matcher paired lines across distant pages -- repeated running heads,
reordered content -- not that the page grew that much. On nist_ai_rmf this
produces 46,000pt "inflation" which is pure artifact. Trust rows whose
rendered span is within ~2 page heights; treat the rest as unmeasured.
"""
import os, sys
from collections import Counter
import _paths  # noqa: F401

import fitz
from heightdiff import doc_lines

TK = os.path.dirname(os.path.abspath(__file__))

for name in ("arxiv_transformer", "arxiv_bert", "nist_ai_rmf"):
    src = os.path.join(TK, "real", name + ".pdf")
    ren = os.path.join(TK, "hdiff", name + ".pdf")
    if not os.path.exists(ren):
        print("missing", ren); continue
    sp, SH = doc_lines(src)
    op, OH = doc_lines(ren)
    oc = Counter(t for pg in op for t, _, _ in pg)
    pos = {}
    for ri, pg in enumerate(op):
        for t, y0, _ in pg:
            if oc[t] == 1:
                pos[t] = ri * OH + y0
    print("\n=== %s (source %d pages -> render %d) ===" % (name, len(sp), len(op)))
    over = 0
    for i, lines in enumerate(sp, 1):
        sc = Counter(t for t, _, _ in lines)
        m = [(y0, pos[t]) for t, y0, _ in lines if sc[t] == 1 and t in pos]
        if len(m) < 5:
            continue
        m.sort()
        s_span = m[-1][0] - m[0][0]
        o_span = m[-1][1] - m[0][1]
        if s_span < 50:
            continue
        infl = o_span - s_span
        if infl > 8:
            over += 1
            print("  p%-3d source span %6.1f -> render %7.1f   +%6.1fpt (%+.0f%%)"
                  % (i, s_span, o_span, infl, 100 * infl / s_span))
    print("  %d/%d pages inflate by >8pt" % (over, len(sp)))
