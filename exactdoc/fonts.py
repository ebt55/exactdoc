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


def base_family(pdf_font: str) -> str:
    """Strip style suffixes from a PDF font name -> base family guess."""
    name = re.sub(r"^[A-Z]{6}\+", "", pdf_font or "").strip()
    # split CamelCase preserved; strip trailing style tokens repeatedly
    prev = None
    while prev != name:
        prev = name
        name = _STYLE_RE.sub("", name).strip()
    return name


def map_font(pdf_font: str, mono: bool = False, serif: bool = False) -> str:
    base = base_family(pdf_font)
    key = re.sub(r"[^a-z]", "", base.lower())
    if key in _MAP:
        return _MAP[key]
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
