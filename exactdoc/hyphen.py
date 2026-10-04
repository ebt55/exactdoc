"""Is a line-end hyphen a word break or part of the word? Ask the document.

A hyphen at the end of a line followed by a lowercase continuation is one of
two things: a DISCRETIONARY hyphen the typesetter inserted to break a word
(`Con-` / `gress`), which must be deleted when the lines are joined, or a
LEXICAL hyphen that belongs to the text (`single-` / `corpus`), which must be
kept. Getting either wrong corrupts a word the reader will search for.

Geometry cannot tell them apart, and the previous rule was geometry only:
dehyphenate when the paragraph is justified and the line reaches the column
edge. Measured over the real-world corpus that rule was wrong both ways --
464 discretionary hyphens kept mid-word on IRS Pub 501 (ragged-right, so it
never qualified), 205 on the Supreme Court opinion (justified, but its lines
fail the edge test), and lexical hyphens deleted on a justified paper that
never auto-hyphenates (`singlecorpus`, `nationstates`).

The code point cannot tell them apart either, at least not through PDFium. The
Supreme Court opinion and FIPS 197 draw their breaks as U+00AD (PyMuPDF reads
354 of them in the opinion), every other producer as U+002D -- but PDFium
reports BOTH as U+0002 with FPDFText_IsHyphen set, and does the same to the
lexical hyphens of the paper that never hyphenates (5 of 5). Censused over 57
documents: every line-end hyphen PDFium recognises comes back as U+0002, so
the code point carries the line position and nothing about the word.

The document's own vocabulary can tell them apart, and does so decisively:

  * the JOINED form occurring elsewhere, unbroken (`Congress` mid-line), says
    the hyphen was a break;
  * the HYPHENATED form occurring elsewhere (`middle-income` mid-line, or
    inside a longer compound) says it is part of the word.

Censused per document over consecutive lines of one block: hyphenating
producers resolve overwhelmingly to the joined form (SCOTUS 785 joined : 4
compound, Pub 501 445 : 0, LuaTeX 277 : 1, texinfo 317 : 19), and documents
set without hyphenation resolve to the compound (RFC 9110 0 : 36, SP 800-63B
1 : 17, the owner's paper 0 : 3). Where neither form occurs, that document-
level balance is the prior: a fragment that is not a word (`Ham-` + `ilton`)
in a hyphenating document is a break; in a document that does not hyphenate
it is a compound nobody else in the document spelled out. A pair of two real
words is the hard case: in the opinion `up-side`, `along-side`, `which-ever`
were breaks and `self-serving`, `well-known` compounds. What separates them
is whether this document builds hyphenated compounds from either word at all
(`self-` heads four, `which-` none). Scored by hand over the 18 genuine
two-word pairs of the opinion (its U+00AD readings as truth), Pub 501, the
1040 instructions and the WDR, that rule errs on 5 where keeping them all errs
on 12; a document that does not hyphenate keeps them. Only when the document
has too little evidence either way does the old geometry verdict decide.

The evidence is built once per document by `infer` and reached by
`infer._soft_join` through a context variable, so the many paragraph builders
that join lines need no new parameter, and a join made outside a conversion
(unit tests, tools) keeps the geometry verdict it always had.
"""
import contextvars
import re
from collections import Counter
from typing import Optional

_LETTERS = "A-Za-zÀ-ɏ"
_TOKEN = re.compile(r"[%s]+(?:-[%s]+)*" % (_LETTERS, _LETTERS))
_TAIL = re.compile(r"([%s]+)-$" % _LETTERS)
_HEAD = re.compile(r"([a-zß-öø-ÿ][%s]*)" % _LETTERS)

# Hyphenation engines leave at least two letters on each side of a break (TeX's
# \lefthyphenmin is 2 and \righthyphenmin 3; Word and LibreOffice default to 2),
# so a one-letter side is a compound (`e-mail`, `x-ray`), never a break.
MIN_SIDE = 2
# How much attested evidence a document needs before its balance is a prior,
# and how lopsided that balance has to be. Three decisions is the corpus's
# smallest unambiguous case (the paper: 0 joined : 3 compound); 2:1 separates
# every document censused with a wide margin -- the closest hyphenating
# documents are the World Development Report at 125:25 and the pandoc manual
# at 69:20, the closest non-hyphenating one SP 800-63B at 1:17.
MIN_EVIDENCE = 3
DOMINANCE = 2.0

_CURRENT = contextvars.ContextVar("exactdoc_hyphen_evidence", default=None)


def current() -> Optional["HyphenEvidence"]:
    return _CURRENT.get()


def activate(ev: Optional["HyphenEvidence"]):
    """Make `ev` the evidence for joins in this context; returns a reset token."""
    return _CURRENT.set(ev)


def deactivate(token) -> None:
    _CURRENT.reset(token)


def split_pair(prev_text: str, next_text: str):
    """(x, y) for a candidate break `...x-` / `y...`, or None.

    x is the letters directly before the hyphen (after any earlier hyphen of a
    compound), y the leading lowercase word of the continuation.
    """
    m = _TAIL.search(prev_text.rstrip())
    n = _HEAD.match(next_text.lstrip())
    if not (m and n):
        return None
    return m.group(1), n.group(1)


class HyphenEvidence:
    """A document's vocabulary, and what it says about its line-end hyphens."""

    def __init__(self, lines_by_block):
        """`lines_by_block`: iterable of blocks, each a list of line texts in
        reading order. Line-end fragments are not words and are left out."""
        self.words = Counter()
        self.compounds = Counter()
        # How often a word starts / ends a hyphenated compound in this
        # document: `self-` and `well-` do, `which-` and `along-` do not.
        self.heads = Counter()
        self.tails = Counter()
        blocks = [list(b) for b in lines_by_block]
        for lines in blocks:
            for i, text in enumerate(lines):
                toks = _TOKEN.findall(text)
                if toks and text.rstrip().endswith("-"):
                    toks = toks[:-1]           # `Con-` is half a word
                if toks and i > 0 and lines[i - 1].rstrip().endswith("-"):
                    toks = toks[1:]            # ...and `gress` the other half
                for tok in toks:
                    parts = tok.lower().split("-")
                    self.words.update(parts)
                    for a, b in zip(parts, parts[1:]):
                        self.compounds[(a, b)] += 1
                        self.heads[a] += 1
                        self.tails[b] += 1
        joined = compound = 0
        for lines in blocks:
            for a, b in zip(lines, lines[1:]):
                pair = split_pair(a, b)
                if pair is None:
                    continue
                verdict = self.attested(*pair)
                if verdict is True:
                    joined += 1
                elif verdict is False:
                    compound += 1
        self.joined, self.compound = joined, compound
        if joined + compound < MIN_EVIDENCE:
            self.hyphenates = None
        elif joined >= DOMINANCE * compound:
            self.hyphenates = True
        elif compound >= DOMINANCE * joined:
            self.hyphenates = False
        else:
            self.hyphenates = None

    @classmethod
    def from_ir(cls, ir) -> "HyphenEvidence":
        return cls([ln.text for ln in b.lines] for p in ir.pages for b in p.blocks)

    def attested(self, x: str, y: str) -> Optional[bool]:
        """True: the joined form occurs and outnumbers the compound. False: the
        compound does. None: the document never spelled out either."""
        x, y = x.lower(), y.lower()
        j, c = self.words[x + y], self.compounds[(x, y)]
        if j > c:
            return True
        if c > j:
            return False
        return None

    def is_break(self, x: str, y: str, at_edge: bool) -> bool:
        """Delete the hyphen between `x-` and `y`? `at_edge` is the geometry
        verdict (a justified line at its wrap edge), consulted last."""
        verdict = self.attested(x, y)
        if verdict is not None:
            return verdict
        if len(x) < MIN_SIDE or len(y) < MIN_SIDE:
            return False
        xl, yl = x.lower(), y.lower()
        if self.words[xl] and self.words[yl]:
            # Two words. In a document that does not hyphenate, a compound. In
            # one that does, a compound only if this document actually builds
            # hyphenated compounds from either word; otherwise the hyphenator
            # simply broke a closed word at a morpheme (`which-ever`,
            # `along-side`, `net-working`).
            if self.hyphenates and not (self.heads[xl] or self.tails[yl]):
                return True
            return False
        if self.hyphenates is not None:
            return self.hyphenates
        return at_edge


def mark_unhyphenated(lay) -> int:
    """In a hyphenating document, say which paragraphs must not hyphenate.

    `autoHyphenation` is a document setting, and Word and LibreOffice apply it
    to every paragraph that does not opt out with `w:suppressAutoHyphens`. The
    source hyphenated its running text, not its titles: the renders showed
    `Withdrawn NIST Technical Series Publica-tion`, `Digital Identity
    Guide-lines` and `The Middle In-come` on covers and headings. Headings,
    centred or right-aligned lines and paragraphs the source set on one line
    never wrapped there, so there is no evidence they were ever hyphenated --
    they opt out. Returns how many were marked; marks nothing in a document
    that does not hyphenate, so its paragraphs stay byte-identical.
    """
    from .layout import iter_paras
    if not getattr(lay, "hyphenated", False):
        return 0
    n = 0
    for p in iter_paras(lay):
        if p.heading or p.align in ("center", "right") or (p.src_lines or 1) <= 1:
            p.no_hyphenation = True
            n += 1
    return n
