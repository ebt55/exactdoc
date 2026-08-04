"""Font mapping: PDF font names -> Google Docs-safe font families."""
import re

# Families Google Docs renders natively (safe to pass through)
GDOCS_NATIVE = {
    "arial", "times new roman", "courier new", "georgia", "verdana", "tahoma",
    "trebuchet ms", "impact", "comic sans ms", "roboto", "roboto mono",
    "open sans", "lato", "montserrat", "merriweather", "source code pro",
    "source sans pro", "playfair display", "oswald", "raleway", "pt serif",
    "pt sans", "nunito", "inconsolata", "eb garamond", "lora", "poppins",
    "inter", "work sans", "rubik", "quicksand", "josefin sans", "libre baskerville",
    "crimson text", "dm sans", "dm serif display", "space grotesk", "space mono",
    "ibm plex sans", "ibm plex serif", "ibm plex mono", "fira sans", "fira code",
    "jetbrains mono", "karla", "mulish", "manrope", "figtree", "outfit", "sora",
    "bitter", "cabin", "barlow", "archivo", "heebo", "noto sans", "noto serif",
}

# Exact-name mappings for common PDF-producer fonts
_MAP = {
    "helvetica": "Arial", "helv": "Arial", "arialmt": "Arial", "arial": "Arial",
    "liberationsans": "Arial", "nimbussans": "Arial", "dejavusans": "Arial",
    "segoeui": "Arial", "calibri": "Carlito", "carlito": "Carlito",
    "times": "Times New Roman", "timesroman": "Times New Roman",
    "timesnewroman": "Times New Roman", "timesnewromanpsmt": "Times New Roman",
    "liberationserif": "Times New Roman", "nimbusroman": "Times New Roman",
    "dejavuserif": "Times New Roman", "cambria": "Georgia",
    "computermodern": "Times New Roman", "cmr": "Times New Roman",
    "courier": "Courier New", "couriernew": "Courier New",
    "couriernewpsmt": "Courier New", "liberationmono": "Courier New",
    "dejavusansmono": "Courier New", "consolas": "Courier New", "menlo": "Courier New",
    "symbol": "Arial", "zapfdingbats": "Arial",
}

_STYLE_RE = re.compile(
    r"[-_ ,]?(bold|black|heavy|semibold|demibold|medium|light|thin|extralight|"
    r"ultralight|italic|oblique|regular|roman|book|normal|condensed|narrow|"
    r"expanded|ps?mt|mt|ps)$", re.IGNORECASE)


# --- measured advance widths -----------------------------------------------
# Average advance width per character at 1pt, measured from the font files
# themselves (advance widths are a property of the file, so this is a
# measurement and not a guess), together with the family's class.
#
#   reference string: METRIC_REFERENCE below -- fixed and committed so the
#   table is reproducible; representative English prose rather than a pangram,
#   because letter frequency is what decides how much text fits on a line.
#   method: fitz.Font(fontfile=...).text_length(REF, fontsize=1.0) / len(REF)
#
# The table exists because the writer cannot shape text at run time: metrics
# are NullMetrics by default (see exactdoc/metrics.py -- MuPDF's base-14 tables
# are AGPL and deliberately not vendored). So the ratio has to arrive as a
# measured constant, the same way NATURAL_FACTORS carries Docs' line heights.
#
# A family that is absent here is UNMEASURED, which is not the same as
# "deviation zero": `metric_fit` declines to act on it rather than guessing.
# 23 of the 45 corpus documents fall in that category and are left alone.
#
# Validation: DejaVu Serif / Times New Roman predicts a packing ratio of 1.2758,
# against 1.2950 actually observed in Google's own export of l1_word_native --
# 1.5% apart, on a document where 85 source characters per line became 105.
METRIC_REFERENCE = (
    "The quick brown fox jumps over the lazy dog. Modern inference workloads "
    "exhibit sharply bimodal traffic patterns, with sustained baseline demand "
    "punctuated by bursts that exceed steady-state volume by an order of "
    "magnitude; provisioning for peak wastes capacity, and provisioning for "
    "baseline degrades latency guarantees precisely when demand is highest.")

FAMILY_METRICS = {
    # key                 adv/char @1pt   class
    "dejavuserif":       (0.520900, "serif"),
    "dejavusans":        (0.515684, "sans"),
    "dejavusansmono":    (0.602051, "mono"),
    "liberationserif":   (0.408307, "serif"),
    "liberationsans":    (0.450660, "sans"),
    "liberationmono":    (0.600098, "mono"),
    "timesnewroman":     (0.408307, "serif"),
    "arial":             (0.450660, "sans"),
    "couriernew":        (0.600098, "mono"),
    "georgia":           (0.448221, "serif"),
    "notoserif":         (0.488144, "serif"),
    "notosans":          (0.480460, "sans"),
    "verdana":           (0.516962, "sans"),
}

# Substitution candidates, restricted to families already asserted as natively
# rendered by Google Docs (GDOCS_NATIVE) AND measured above.
_CANDIDATES = {
    "serif": ("Times New Roman", "Georgia", "Noto Serif"),
    "sans": ("Arial", "Verdana", "Noto Sans"),
    "mono": ("Courier New",),
}

# Act only on a deviation large enough to move line breaks, and substitute a
# family only when the gain is worth changing the typeface.
#
# Measured basis for the floor: the corpus's metric-compatible mappings sit at
# exactly 0.0% -- Liberation Serif/Sans/Mono against Times New Roman/Arial/
# Courier New all measure 1.000000, because they are metric clones by design.
# The largest honest residual among working documents is DejaVu Sans Mono ->
# Courier New at -0.32%. So anything under 2% is indistinguishable from the
# mappings that already work, and is also below the half-point font-size
# quantisation this writer already accepts (_quantised_size), which moves a
# line's advance by up to ~0.5% on its own.
METRIC_TRACK_DEV = 0.02
# 5% is where a family swap earns its visual cost: below it the residual
# tracking is under ~0.25pt at 11pt and closes the gap without changing the
# typeface at all.
METRIC_SUBSTITUTE_DEV = 0.05


def base_family(pdf_font: str) -> str:
    """Strip style suffixes from a PDF font name -> base family guess."""
    name = re.sub(r"^[A-Z]{6}\+", "", pdf_font or "").strip()
    # split CamelCase preserved; strip trailing style tokens repeatedly
    prev = None
    while prev != name:
        prev = name
        name = _STYLE_RE.sub("", name).strip()
    return name


def _key(name: str) -> str:
    return re.sub(r"[^a-z]", "", (name or "").lower())


def family_keys(pdf_font: str) -> list:
    """Lookup keys from the most specific name to the most stripped one.

    `base_family` strips trailing style tokens until nothing matches, and
    `roman` is one of those tokens -- correct for "Times-Roman", where Roman
    names the upright style, and wrong for "Times New Roman", where it is part
    of the family. "TimesNewRomanPSMT" lost "PSMT" and then "Roman" and arrived
    as "TimesNew", so `_MAP["timesnewroman"]` and `_MAP["timesnewromanpsmt"]`
    could never be reached by any input: both were dead entries.

    The cost was not a near-miss. With no map hit the lookup fell through to the
    serif/mono heuristic, and a span whose serif flag is not set maps to
    **Arial** -- so the most common serif font name in real-world PDFs rendered
    as a sans face. Measured on the expansion corpus: five NIST/IRS documents
    (y01, y06, y08, y09, y10) mapped TimesNewRomanPSMT and "Times New Roman" to
    Arial, which is also 10.4% wider than Times New Roman and so re-wrapped
    every paragraph on top of changing the typeface.

    Trying progressively stripped keys keeps the style stripping (a bold face
    must still find its family) while letting a fully-specified name match
    first. "TimesNewRomanPS-BoldMT" walks
    timesnewromanpsboldmt -> timesnewromanpsbold -> timesnewromanps ->
    timesnewroman, and stops at the entry that was previously unreachable.
    """
    name = re.sub(r"^[A-Z]{6}\+", "", pdf_font or "").strip()
    keys, seen = [], set()
    while True:
        k = _key(name)
        if k and k not in seen:
            seen.add(k)
            keys.append(k)
        nxt = _STYLE_RE.sub("", name).strip()
        if nxt == name or not nxt:
            break
        name = nxt
    return keys


def map_font(pdf_font: str, mono: bool = False, serif: bool = False) -> str:
    for key in family_keys(pdf_font):
        if key in _MAP:
            return _MAP[key]
    base = base_family(pdf_font)
    # try native pass-through: insert spaces between CamelCase words
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", base).strip()
    if spaced.lower() in GDOCS_NATIVE:
        return spaced.title() if spaced.islower() else spaced
    # heuristic fallback
    if mono:
        return "Courier New"
    if serif:
        return "Times New Roman"
    return "Arial"


def family_metrics(name):
    """(advance_per_char_at_1pt, class) for a family name, or None."""
    for key in family_keys(name):
        hit = FAMILY_METRICS.get(key)
        if hit is not None:
            return hit
    return None


def metric_fit(pdf_font: str, mono: bool = False, serif: bool = False):
    """Google Docs profile: (family, tracking_pt_per_pt_of_size).

    The standard mapping is metric-compatible by design -- Helvetica->Arial,
    Times->Times New Roman, and the Liberation faces measure *exactly* 1.000000
    against their Microsoft counterparts. Where it is not, the substitute's
    glyphs are a different width, the same text needs a different number of
    lines, every paragraph re-wraps, and words land nowhere near their source
    position. Measured on l1_word_native, whose DejaVu Serif source maps to a
    Times New Roman 21.6% narrower: 85 characters per line became 105, and the
    document scored dx_p50 63.65pt with dy_p50 19.35pt -- one root cause for
    both, since re-wrapping also drops whole lines.

    Two corrections, applied in order and each keyed on measured deviation
    rather than on any document:

    1.  If the mapped family deviates by more than METRIC_SUBSTITUTE_DEV, pick
        the candidate of the same class whose measured advance is closest to
        the source. DejaVu Serif goes Times New Roman (-21.6%) -> Noto Serif
        (-6.3%); DejaVu Sans goes Arial (-12.6%) -> Verdana (+0.2%).
    2.  Close whatever remains with run-level tracking, if it still exceeds
        METRIC_TRACK_DEV. For DejaVu Serif -> Noto Serif that is 0.360pt at
        11pt, or 33/1000 em -- ordinary loose tracking. Against unsubstituted
        Times New Roman it would have been 113/1000 em, conspicuously spaced,
        which is why the substitution comes first.

    Returns the unmodified mapping and no tracking whenever either side is
    unmeasured. An absent measurement is not a deviation of zero, and this is
    the same discipline `metrics.NullMetrics` applies: act only on a number you
    actually have.
    """
    mapped = map_font(pdf_font, mono=mono, serif=serif)
    src = family_metrics(pdf_font)
    cur = family_metrics(mapped)
    if src is None or cur is None:
        return mapped, 0.0
    src_adv, cls = src
    if not src_adv:
        return mapped, 0.0
    family, adv = mapped, cur[0]
    if abs(adv / src_adv - 1.0) > METRIC_SUBSTITUTE_DEV:
        for cand in _CANDIDATES.get(cls, ()):
            got = family_metrics(cand)
            if got is None:
                continue
            if abs(got[0] / src_adv - 1.0) < abs(adv / src_adv - 1.0):
                family, adv = cand, got[0]
    track = 0.0
    if abs(adv / src_adv - 1.0) > METRIC_TRACK_DEV:
        track = src_adv - adv
    return family, track
