"""Running-furniture evidence: printed page numbers and how they are counted.

`infer.detect_hf` decides which lines are running heads and footers. This
module answers the questions it asks about the NUMBERS on them, and nothing
else, so the rules can be read and tested in one place:

- which tokens of a line could be a page number (arabic digits, or a roman
  numeral written as a word of its own -- "PAGE vii");
- whether a token IS this page's number. That is a cross-page question: a
  digit is a page number only when it tracks the physical page index with a
  constant offset over a run of pages. "v3.2" never does. The rule used to
  demand offset 0 -- printed number == physical index -- and so classed every
  document with front matter as literal text: NIST SP 800-171 prints
  "PAGE vii" on its 10th page and "PAGE 28" on its 41st, and both arrived in
  the DOCX as the literal source number on every page (audit B3);
- where the numbering restarts or changes format, so the writer can open a
  section there with `w:pgNumType w:start/w:fmt` and keep a live PAGE field.

Pure functions over plain values; no IR types are imported.
"""
import re
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

DECIMAL, LOWER_ROMAN, UPPER_ROMAN = "decimal", "lowerRoman", "upperRoman"

# Strict roman numerals only: "MIX" and "CD" are numerals, "DID" and "LCD" are
# not. A roman token is only ever *believed* when it tracks the page index (see
# page_number_model), so a pronoun "I" or the "v." of a case name costs nothing.
_ROMAN_RE = re.compile(
    r"^(?=[MDCLXVI])M{0,4}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$")
# A digit group anywhere ("Page40", "[Page 40]"), or a whole alphabetic word
# delimited by non-alphanumerics -- the "v" of "v3.2" is glued to a digit and
# is not a word.
_TOKEN_RE = re.compile(r"\d+|(?<![A-Za-z0-9])[A-Za-z]+(?![A-Za-z0-9])")
_ROMAN_VAL = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}

# A non-zero offset (or a roman format) is believed only over this many pages.
# Three, not two: two consecutive pages whose stray numbers happen to step by
# one -- "Step 1" / "Step 2" in a top band -- are a coincidence a short
# document produces; three in a row at the same offset are a counter. Offset 0
# keeps its historical two-page bar (the cross-page rule
# docs/deep-dive/theory.md section 2 documents), so no existing PAGE field
# changes.
PN_RUN_MIN = 3
# A run may skip pages that print no number (a chapter opener, a full-page
# figure, a blank verso): up to two consecutive silent pages.
PN_RUN_GAP = 3
# The PDF's own /PageLabels, when they agree, lower the bar to two pages: the
# author's numbering scheme is then stated twice, once in the catalog and once
# on the page.
PN_RUN_MIN_LABELLED = 2


def roman_value(s: str) -> int:
    total = 0
    s = s.upper()
    for i, ch in enumerate(s):
        v = _ROMAN_VAL[ch]
        if i + 1 < len(s) and _ROMAN_VAL[s[i + 1]] > v:
            total -= v
        else:
            total += v
    return total


def num_tokens(text: str) -> List[Tuple[int, int, str, int]]:
    """[(start, end, fmt, value)] for every token that could be a page number.

    Every digit group is a token (exactly the groups the old `\\d+` rule saw,
    so role lists stay index-aligned for arabic text), plus every word that is a
    valid roman numeral written in one case.
    """
    out = []
    for m in _TOKEN_RE.finditer(text or ""):
        s = m.group()
        if s.isdigit():
            out.append((m.start(), m.end(), DECIMAL, int(s)))
        elif (s.islower() or s.isupper()) and _ROMAN_RE.match(s.upper()):
            out.append((m.start(), m.end(),
                        LOWER_ROMAN if s.islower() else UPPER_ROMAN,
                        roman_value(s)))
    return out


def parse_label(label: Optional[str]) -> Optional[Tuple[str, int]]:
    """A /PageLabels string as (fmt, value), or None when it is not a number."""
    if not label:
        return None
    toks = num_tokens(label.strip())
    if len(toks) != 1:
        return None
    s, e, fmt, v = toks[0]
    if s != 0 or e != len(label.strip()):
        return None
    return fmt, v


def _runs(pages: Iterable[int]) -> List[List[int]]:
    runs, cur = [], []
    for pg in sorted(set(pages)):
        if cur and pg - cur[-1] > PN_RUN_GAP:
            runs.append(cur)
            cur = []
        cur.append(pg)
    if cur:
        runs.append(cur)
    return runs


def page_number_model(evidence: Iterable[Tuple[int, str, int, bool]],
                      labels: Optional[Sequence[Optional[str]]] = None
                      ) -> Dict[int, Tuple[str, int]]:
    """{page: (fmt, offset)} -- the printed number of `page` is page + offset.

    `evidence` is (page, fmt, value, in_legacy_zone) for every numeric token on
    a furniture candidate line. A (fmt, offset) key is believed on a page when
    the page belongs to a run of pages carrying that key: PN_RUN_MIN pages, or
    PN_RUN_MIN_LABELLED when the PDF's page labels agree, or -- the historical
    rule, kept exact -- any two pages for offset 0 in the legacy bands.
    When a page could take two keys the longer run wins.
    """
    by_key: Dict[Tuple[str, int], set] = defaultdict(set)
    by_key_legacy: Dict[Tuple[str, int], set] = defaultdict(set)
    for pg, fmt, v, legacy in evidence:
        if v < 1:
            continue
        k = (fmt, v - pg)
        by_key[k].add(pg)
        if legacy:
            by_key_legacy[k].add(pg)
    lab = {}
    for i, label in enumerate(labels or ()):
        pv = parse_label(label)
        if pv is not None:
            lab[i + 1] = (pv[0], pv[1] - (i + 1))
    best: Dict[int, Tuple[Tuple[int, int], Tuple[str, int]]] = {}

    def offer(pg, k, strength):
        rank = (strength, 1 if k == (DECIMAL, 0) else 0)
        if pg not in best or rank > best[pg][0]:
            best[pg] = (rank, k)

    for k in sorted(by_key):
        for run in _runs(by_key[k]):
            agree = sum(1 for pg in run if lab.get(pg) == k)
            if len(run) >= PN_RUN_MIN or \
                    (len(run) >= PN_RUN_MIN_LABELLED and agree >= len(run)):
                for pg in run:
                    offer(pg, k, len(run))
    k0 = (DECIMAL, 0)
    legacy0 = by_key_legacy.get(k0, set())
    if len(legacy0) >= 2:
        # printed == physical: the original cross-page verification, which never
        # required the pages to be adjacent
        for pg in legacy0:
            offer(pg, k0, len(legacy0))
    out = {pg: k for pg, (_, k) in best.items()}
    if lab and out:
        # The labels carry a believed run across the pages around it that print
        # no number (a chapter opener, the last page of front matter), for as
        # long as they keep stating the same scheme. Measured on lshort: the
        # arabic count is printed from page 16 but labelled from page 15, its
        # chapter-one opener, which then starts the section where it should.
        believed = dict(out)
        for order in (range(1, len(labels) + 1), range(len(labels), 0, -1)):
            cur = None
            for pg in order:
                if pg in believed:
                    cur = believed[pg]
                elif cur is not None and lab.get(pg) == cur:
                    out.setdefault(pg, cur)
                else:
                    cur = None
    return out


def is_page_number(pn: Dict[int, Tuple[str, int]], pg: int, fmt: str,
                   value: int) -> bool:
    k = pn.get(pg)
    return k is not None and k == (fmt, value - pg)


def furniture_text(text: str, pn: Dict[int, Tuple[str, int]], pg: int) -> str:
    """Signature text: digit groups -> '#', and a roman word -> '#' only when it
    is this page's verified number (so "Part I" / "Part II" stay distinct)."""
    out, pos = [], 0
    for s, e, fmt, v in num_tokens(text):
        if fmt != DECIMAL and not is_page_number(pn, pg, fmt, v):
            continue
        out.append(text[pos:s])
        out.append("#")
        pos = e
    out.append(text[pos:])
    return "".join(out).strip()


def forward_keys(pn: Dict[int, Tuple[str, int]], n: int
                 ) -> Dict[int, Optional[Tuple[str, int]]]:
    """Each page's numbering key, a silent page continuing the one before it."""
    out, cur = {}, None
    for pg in range(1, n + 1):
        if pg in pn:
            cur = pn[pg]
        out[pg] = cur
    return out


def printed_parity(pn: Dict[int, Tuple[str, int]], n: int) -> Dict[int, int]:
    """1 for a page whose printed number is odd (a recto), else 0.

    Word decides which header a page gets from its page NUMBER, and the probe
    of LibreOffice in the canonical container showed it doing the same across a
    restart, so parity is taken from the printed number wherever the document
    states one, and from the physical index where it does not.
    """
    keys = forward_keys(pn, n)
    out = {}
    for pg in range(1, n + 1):
        k = keys[pg]
        out[pg] = (pg + k[1]) % 2 if k is not None else pg % 2
    return out


def numbering_sections(pn: Dict[int, Tuple[str, int]], n: int
                       ) -> List[Tuple[int, Optional[str], Optional[int]]]:
    """[(start_page, fmt, start_value)] -- one entry per numbering section.

    The first entry always starts at page 1; `fmt`/`start_value` None there
    means the leading pages print no number the evidence can extend back to
    (a cover and title page before roman front matter). Returns [] when the
    whole document is numbered 1..n in arabic, which needs no section at all.

    A change of key is a restart: front matter i..x then 1.., or a slip
    opinion whose every opinion restarts at 1. A run must be believed by
    `page_number_model` first, so a single stray page cannot open a section.
    """
    if not pn:
        return []
    first = min(pn)
    fmt0, off0 = pn[first]
    secs: List[Tuple[int, Optional[str], Optional[int]]] = []
    if 1 + off0 >= 1:
        secs.append((1, fmt0, 1 + off0))
    else:
        secs.append((1, None, None))
        secs.append((first, fmt0, first + off0))
    cur = pn[first]
    for pg in range(first + 1, n + 1):
        k = pn.get(pg)
        if k is None or k == cur:
            continue
        if pg + k[1] < 1:
            continue
        secs.append((pg, k[0], pg + k[1]))
        cur = k
    if len(secs) == 1 and secs[0][1:] == (DECIMAL, 1):
        return []
    return secs
