"""The indexed line grouping returns exactly what the quadratic one did.

`_baseline_rows` and `_absorb_script_rows` were rewritten for speed (audit B21:
the refine loop spent 58s of y01's 87s reading text back out of PDFs, and these
two scans were most of it). A faster parser that groups one character
differently moves every downstream number, so the contract is equality, not
similarity: the original algorithms are kept below verbatim as references and
both versions run over randomised pages built to stress the edges -- baselines
inside and on the tolerance, scripts beside and between hosts, ties in score.

The corpus-level check (page_lines and the parsed IR of all 56 fixtures
fingerprint-identical before and after) is recorded in the CHANGELOG entry.
"""
import copy
import random
import unittest

from exactdoc import parse_pdfium as P


def _old_baseline_rows(chars):
    rows = []
    for c in sorted(chars, key=lambda c: (round(c.oy, 1), c.ox)):
        placed = False
        for r in rows:
            if abs(c.oy - r[0].oy) <= max(P.BASELINE_TOL, 0.12 * c.size):
                r.append(c)
                placed = True
                break
        if not placed:
            rows.append([c])
    return rows


def _old_absorb_script_rows(vis_rows):
    rows = [(ri, row) for ri, row in vis_rows if row]
    absorbed = set()
    for i, (frag_ri, frag) in enumerate(rows):
        fsz = max(c.size for c in frag)
        fx0 = min(c.x0 for c in frag)
        fb = frag[0].oy
        best = None
        for j, (host_ri, host) in enumerate(rows):
            if j == i or j in absorbed or host_ri == frag_ri:
                continue
            hsz = max(c.size for c in host)
            dy = fb - host[0].oy
            if abs(dy) > P.SCRIPT_BASE_EM * hsz:
                continue
            hx0, hx1 = P._row_span(host)
            if fx0 <= hx0 or fx0 > hx1 + P.SCRIPT_REACH_EM * hsz:
                continue
            # WP10's rules, unoptimised: a script is smaller than the glyph it
            # attaches to; a full-size glyph or two set into the word joins it.
            inset = fsz >= P.SCRIPT_SIZE_FRAC * P._attach_size(host, fx0, hsz)
            if inset and not P._set_into(frag, host, hsz):
                continue
            if inset and abs(dy) > P.INSET_DY_EM * hsz:
                continue
            score = (max(0.0, fx0 - hx1), abs(dy))
            if best is None or score < best[0]:
                best = (score, j, hsz, inset)
        if best is None:
            continue
        _, j, hsz, inset = best
        host = rows[j][1]
        if not inset and fb < host[0].oy - P.SCRIPT_RAISE_EM * hsz:
            for c in frag:
                c.sup = True
        host.extend(frag)
        host.sort(key=lambda c: c.x0)
        absorbed.add(i)
    return [row for i, (_, row) in enumerate(rows) if i not in absorbed]


# _Char has __slots__; the test subclass carries an identity for comparing
# groupings.
class _TChar(P._Char):
    __slots__ = ("k",)


def _mk(u, x0, oy, size, k):
    c = _TChar()
    c.u = u
    c.x0, c.x1 = x0, x0 + 0.5 * size
    c.oy = oy
    c.y0, c.y1 = oy - 0.8 * size, oy + 0.2 * size
    c.ox = x0
    c.size = size
    c.font, c.flags, c.color, c.gen = "Helvetica", 0, "#000000", False
    c.k = k
    return c


def _page(rng):
    """A shuffled page: rows of characters whose baselines jitter around and
    exactly onto the grouping tolerance, with small script fragments raised,
    lowered and pushed out of reach beside their hosts."""
    chars, k = [], 0
    y = 60.0
    for _ in range(rng.randint(5, 40)):
        size = rng.choice([7.0, 8.0, 9.5, 10.0, 10.0, 12.0, 18.0])
        x = 72.0
        for _ in range(rng.randint(1, 30)):
            jitter = rng.choice([0.0, 0.0, 0.3, -0.3, 1.0, 1.2, -1.2,
                                 0.12 * size, -0.12 * size])
            chars.append(_mk("a", x, y + jitter, size, k))
            k += 1
            x += 0.5 * size + rng.choice([0.0, 0.5, 2.0, 12.0, 40.0])
            if rng.random() < 0.15:
                ssz = size * rng.choice([0.6, 0.7, 0.9, 0.95])
                oy = y + rng.choice([-0.4, -0.3, 0.2, 0.75, -0.75]) * size
                chars.append(_mk("1", x, oy, ssz, k))
                k += 1
                x += 0.5 * ssz + 0.3
        y += rng.choice([0.6, 2.0, 8.0, 12.0, 14.0, 30.0])
    rng.shuffle(chars)
    return chars


def _keys(rows):
    return [[c.k for c in row] for row in rows]


class GroupingEquivalenceTests(unittest.TestCase):
    def test_baseline_rows_match_the_quadratic_scan(self):
        rng = random.Random(20261004)
        for _ in range(300):
            chars = _page(rng)
            self.assertEqual(_keys(P._baseline_rows(list(chars))),
                             _keys(_old_baseline_rows(list(chars))))

    def test_script_absorption_matches_the_quadratic_scan(self):
        rng = random.Random(1004)
        for _ in range(300):
            chars = _page(rng)
            rows = _old_baseline_rows(chars)
            # fragments as _split_rows produces them: x-sorted, row-indexed,
            # sometimes split in two at a gap
            vis = []
            for ri, row in enumerate(rows):
                row.sort(key=lambda c: c.x0)
                if len(row) > 3 and rng.random() < 0.3:
                    cut = rng.randint(1, len(row) - 1)
                    vis += [(ri, row[:cut]), (ri, row[cut:])]
                else:
                    vis.append((ri, row))
            a = copy.deepcopy(vis)
            b = copy.deepcopy(vis)
            got = P._absorb_script_rows(a)
            want = _old_absorb_script_rows(b)
            self.assertEqual(_keys(got), _keys(want))
            self.assertEqual([[c.sup for c in r] for r in got],
                             [[c.sup for c in r] for r in want])


if __name__ == "__main__":
    unittest.main()
