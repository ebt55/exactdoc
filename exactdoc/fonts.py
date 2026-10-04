"""Font mapping: PDF font names -> the family each output profile writes.

A PDF names its fonts by PostScript name -- `NimbusRomNo9L-Regu`, `CMTT10`,
`HelveticaNeueLTStd-Roman`, `ABCDEF+Calibri-Bold` -- and the writer has to turn
that into a family the reader's renderer actually has. Two facts decide it: the
face's CLASS (serif, sans, mono), which is what keeps code monospace and body
text in the right typeface, and its METRICS, which decide whether the text
re-wraps onto the source's line breaks (THEORY 3.6).

**The family table below is the authority, and the descriptor flags are not.**
This module used to know about two dozen names and hand everything else to a
heuristic driven by the FontDescriptor's Serif/FixedPitch bits. Those bits are
unreliable in exactly the producers that dominate real documents. Measured over
both corpora (57 documents, `scratchpad/audit/font_census.json`):

  * pdfTeX writes Type 1 descriptors with neither bit set. FIPS 197 (y03) set
    98.9% of its characters through the heuristic: `NimbusRomNo9L-Regu` -- the
    URW clone of Times, metric-identical by design -- became Arial, 8.5% wider,
    and the document rendered 1.54x its pages; its `NimbusMonL` code became
    proportional Arial. TeX by Topic (y25) and the Bash manual (y26) did the
    same to `CMTT10`, and lshort's `CMUTypewriter` became Times New Roman.
  * The descriptor bits can also be set WRONG: `CMUSansSerif` arrives with the
    Serif bit on, `CMUTypewriter-Light` with Serif on and FixedPitch off.
  * EUR-Lex (y18) sets 100% of its text in `EUAlbertina`, a serif with no
    serif bit, which became Arial (+9.6% wide).

So every family the corpus (and the world's common producers) use is named
here with its class and the target each output profile writes. The heuristic
remains for names nobody has seen, and the parser now takes its serif/mono/
bold/italic evidence from `font_traits` before it falls back to the flags.

**Per output profile.** The standard profile (Word, LibreOffice) writes Office
families under their own names: a Word user has Calibri and Cambria, not their
Carlito/Caladea clones, and LibreOffice's own replacement table substitutes the
clones where they are installed. The gdocs profile keeps what it wrote before
for those families -- Carlito and Georgia -- because no live pass has yet
graded what Google Docs does with a declared Calibri or Cambria, and a proxy
render does not predict Docs (THEORY 6; CHANGELOG #4 is the precedent: Consolas
was switched only after Docs' own export showed it honoured).

**What the canonical renderer has.** The gate container's pinned fontconfig
(`scripts/fonts.conf`) holds Liberation, DejaVu, FreeFont, WenQuanYi and IPA
Gothic only, and every other family -- Calibri, Cambria, Consolas, Noto Serif,
Georgia -- renders there as FreeSerif (probed 2026-10-04 with a DOCX naming 61
families: LibreOffice ignores the fontTable's family/pitch/altName hints when
it falls back). That is why core targets stay Arial / Times New Roman /
Courier New wherever a class decision is involved: they are the only families
whose rendering every reader, including the measurement, agrees on.
"""
import functools
import re
from typing import NamedTuple, Optional

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
    "consolas", "ubuntu",
}

TNR, ARIAL, COURIER = "Times New Roman", "Arial", "Courier New"


class Family(NamedTuple):
    """One row of the family table.

    `cls` is serif / sans / mono / symbol. `standard` is the family the
    standard profile writes; `gdocs` is what the Google Docs profile writes
    when that differs (None = same). `bold` / `italic` are what the NAME says
    about the face when the PostScript name encodes it in a code rather than a
    word -- CMBX is Computer Modern Bold Extended, CMSL is slanted -- so a
    heading in CMBX12 stays bold although nothing in its name reads "bold".
    `medium_bold` marks the one URW naming in which "Medi" is the bold face
    (NimbusRomNo9L-Medi is Times-Bold's clone; Roboto-Medium is not bold).
    `ea` names a CJK face for the run's East Asian font slot, with its OOXML
    charset; see `east_asian_family`.
    """
    cls: str
    standard: str
    gdocs: Optional[str] = None
    bold: bool = False
    italic: bool = False
    medium_bold: bool = False
    ea: Optional[tuple] = None


def _serif(std=TNR, gdocs=None, **kw):
    return Family("serif", std, gdocs, **kw)


def _sans(std=ARIAL, gdocs=None, **kw):
    return Family("sans", std, gdocs, **kw)


def _mono(std=COURIER, gdocs=None, **kw):
    return Family("mono", std, gdocs, **kw)


def _symbol(std=ARIAL, gdocs=None, **kw):
    return Family("symbol", std, gdocs, **kw)


# The family table. Keys are `_key` forms: lower case, letters only (digits
# are dropped, so CMR10, CMR12 and CMR17 are all "cmr"). A key of five or more
# letters also matches as a PREFIX of a longer name, longest key first --
# "helvetica" covers HelveticaNeueLTStd and HelveticaWorld -- so an entry that
# must not be swallowed by a shorter one is listed explicitly ("centurygothic"
# is a sans; "century" is a serif). Keys under five letters match exactly.
#
# Metric notes are the average advance over METRIC_REFERENCE at 1pt, measured
# from the font files (fitz.Font.text_length), unless stated otherwise.
_FAMILY_TABLE = {
    # --- Times and its metric clones -> Times New Roman --------------------
    # Liberation Serif, Tinos, Nimbus Roman, TeX Gyre Termes and FreeSerif are
    # drawn on Times metrics: Liberation Serif measures 0.408307 against Times
    # New Roman's 0.408307, FreeSerif 0.403895 (FreeSerif is URW's Nimbus Roman
    # extended; the 1.1% is its italic-heavy reference string, not its widths).
    "times": _serif(), "timesroman": _serif(), "timesnewroman": _serif(),
    "timesnewromanpsmt": _serif(), "timesten": _serif(), "tinos": _serif(),
    "liberationserif": _serif(), "freeserif": _serif(), "termes": _serif(),
    "nimbusroman": _serif(), "nimbusromnol": _serif(medium_bold=True),
    "nimbusromannol": _serif(medium_bold=True), "texgyretermes": _serif(),
    "stixgeneral": _serif(), "stixtwotext": _serif(), "stix": _serif(),
    # DejaVu Serif is NOT Times-metric (0.5209, +27.6%); the standard profile
    # has always written Times New Roman for it and the gdocs profile's
    # metric_fit substitutes from there (see FAMILY_METRICS).
    "dejavuserif": _serif(), "bitstreamveraserif": _serif(),
    "droidserif": _serif(),
    # --- serif families with no metric clone among the core three ----------
    # Class is what these rows assert; the core serif is the target because it
    # is the one every renderer has (module docstring). EU Albertina, the EU
    # Publications Office face, measures within 1% of Times New Roman on its
    # own drawn widths (census: Arial/Albertina = 1.096, TNR/Arial = 0.906).
    "albertina": _serif(), "eualbertina": _serif(),
    # URW's 2017 base-35 renames C059 (Century Schoolbook) and P052 (Palatino)
    # reduce to the one-letter keys "c" and "p" once digits are dropped; keys
    # under five letters only ever match exactly, so nothing else reaches them.
    "century": _serif(), "centuryschoolbook": _serif(),
    "centuryschl": _serif(), "newcenturyschlbk": _serif(), "c": _serif(),
    "texgyreschola": _serif(), "centuryexpanded": _serif(),
    "palatino": _serif(), "palatinolinotype": _serif(), "bookantiqua": _serif(),
    "urwpalladiol": _serif(), "urwpalladio": _serif(), "p": _serif(),
    "texgyrepagella": _serif(), "pagella": _serif(),
    "bookman": _serif(), "bookmanoldstyle": _serif(), "urwbookmanl": _serif(),
    "urwbookman": _serif(), "itcbookman": _serif(), "texgyrebonum": _serif(),
    "garamond": _serif(), "adobegaramond": _serif(), "garamondpremr": _serif(),
    "garamondpremier": _serif(), "stempelgaramond": _serif(),
    "itcgaramond": _serif(), "minion": _serif(), "minionpro": _serif(),
    "caslon": _serif(), "adobecaslon": _serif(), "bigcaslon": _serif(),
    "baskerville": _serif(), "newbaskerville": _serif(), "didot": _serif(),
    "bodoni": _serif(), "sabon": _serif(), "plantin": _serif(),
    "perpetua": _serif(), "goudy": _serif(), "goudyoldstyle": _serif(),
    "bembo": _serif(), "janson": _serif(), "galliard": _serif(),
    "utopia": _serif(), "charter": _serif(), "bitstreamcharter": _serif(),
    "xcharter": _serif(), "charis": _serif(), "calluna": _serif(),
    "rockwell": _serif(), "clarendon": _serif(), "lucidabright": _serif(),
    "sourceserif": _serif(), "sourceserifpro": _serif(),
    "cmuserif": _serif(), "cmuconcrete": _serif(), "cmuclassicalserif": _serif(),
    "lmroman": _serif(), "latinmodernroman": _serif(),
    "lmromanslant": _serif(italic=True), "lmromancaps": _serif(),
    "lmromandemi": _serif(bold=True), "lmromandunh": _serif(),
    "lmromanunsl": _serif(),
    # Linux Libertine, the ACM template's face (acmart sets it by default), in
    # its Type 1 names (LinLibertineT/TB/TI/TBI, TZ the semibold) and its
    # OpenType ones (LinLibertine_R/RB/RI/RBI/RZ); Libertinus is its fork.
    # The weight and slant live in a suffix with no separator, so the styled
    # names are listed. Nothing named it and no descriptor bit said serif:
    # y42_arxiv_acmart's 23k characters of body text were written as Arial,
    # ~10% wider than the Times New Roman a serif face maps to.
    "linlibertine": _serif(), "linlibertinet": _serif(),
    "linlibertinetb": _serif(bold=True), "linlibertineti": _serif(italic=True),
    "linlibertinetbi": _serif(bold=True, italic=True),
    "linlibertinetz": _serif(bold=True),
    "linlibertinetzi": _serif(bold=True, italic=True),
    "linlibertiner": _serif(), "linlibertinerb": _serif(bold=True),
    "linlibertineri": _serif(italic=True),
    "linlibertinerbi": _serif(bold=True, italic=True),
    "linlibertinerz": _serif(bold=True),
    "linlibertinerzi": _serif(bold=True, italic=True),
    "libertinus": _serif(), "libertinusserif": _serif(),
    "libertinemath": _serif(), "libertinusmath": _serif(),
    # MathTime (MTMI/MTSY/MTEX, MathTime Pro's RMTMI) and txfonts' maths
    # faces set the maths of Times-bodied journals (y39 Copernicus, y40
    # Frontiers, y42's txmia); like CMMI/CMSY they are the body's serif.
    "mtmi": _serif(italic=True), "mtmib": _serif(bold=True, italic=True),
    "mtsy": _serif(), "mtsyn": _serif(), "mtex": _serif(),
    "rmtmi": _serif(italic=True), "rmtmib": _serif(bold=True, italic=True),
    "txmi": _serif(italic=True), "txmia": _serif(italic=True),
    "txsy": _serif(), "txsys": _serif(), "txsyc": _serif(), "txex": _serif(),
    # --- Office families: their own names in the standard profile ---------
    # Calibri/Carlito and Cambria/Caladea are metric clones (checked glyph by
    # glyph over WinAnsi: Carlito == Calibri on 215 of 216 codepoints, the odd
    # one U+0192; Caladea == Cambria to its 1000-unit rounding). The audit
    # measured Calibri 0.415097 == Carlito 0.415097, Cambria 0.434926 vs
    # Georgia 0.448221 (+3.1%).
    "calibri": _sans("Calibri", "Carlito"),
    "carlito": _sans("Calibri", "Carlito"),
    "calibrilight": _sans("Calibri Light", "Carlito"),
    "cambria": _serif("Cambria", "Georgia"),
    "caladea": _serif("Cambria", "Georgia"),
    "candara": _sans("Candara", ARIAL),
    "corbel": _sans("Corbel", ARIAL),
    "constantia": _serif("Constantia", TNR),
    # Consolas maps to itself, not to Courier New: 0.550em against Courier
    # New's 0.600em, so the substitution widened every inline-code run by
    # 9% and wrapped those lines a word early. Live-verified in Google
    # Docs on a real Chrome-printed report: rFonts "Consolas" plus a
    # fontTable entry is rendered as Consolas in the export's own spans
    # (defect catalogue #4); Courier New is the fallback only when the
    # source font itself is unavailable to name.
    "consolas": _mono("Consolas"),
    # --- Helvetica and its clones -> Arial ---------------------------------
    "helvetica": _sans(), "helv": _sans(), "arial": _sans(), "arialmt": _sans(),
    "arimo": _sans(), "liberationsans": _sans(), "nimbussans": _sans(),
    "nimbussanl": _sans(), "texgyreheros": _sans(), "freesans": _sans(),
    "heros": _sans(), "dejavusans": _sans(), "bitstreamverasans": _sans(),
    "droidsans": _sans(), "segoeui": _sans(), "segoe": _sans(),
    "arialnarrow": _sans(), "helveticanarrow": _sans(),
    # --- sans families with no clone among the core three -> Arial --------
    "univers": _sans(), "frutiger": _sans(), "myriad": _sans(),
    "myriadpro": _sans(), "gotham": _sans(), "franklingothic": _sans(),
    "itcfranklingothic": _sans(), "newsgothic": _sans(),
    "tradegothic": _sans(), "akzidenzgrotesk": _sans(), "avenir": _sans(),
    "futura": _sans(), "gillsans": _sans(), "gillsansmt": _sans(),
    "lucidasans": _sans(), "lucidagrande": _sans(), "optima": _sans(),
    "centurygothic": _sans(), "avantgarde": _sans(), "itcavantgarde": _sans(),
    "urwgothic": _sans(), "urwgothicl": _sans(), "texgyreadventor": _sans(),
    "callunasans": _sans(), "proximanova": _sans(), "sourcesans": _sans(),
    "sfprotext": _sans(), "sfprodisplay": _sans(), "sanfrancisco": _sans(),
    "cmusansserif": _sans(), "cmubright": _sans(), "lmsans": _sans(),
    # Linux Biolinum, Libertine's sans companion (acmart's headings).
    "linbiolinum": _sans(), "linbiolinumt": _sans(),
    "linbiolinumtb": _sans(bold=True), "linbiolinumti": _sans(italic=True),
    "linbiolinumto": _sans(italic=True),
    "linbiolinumtbi": _sans(bold=True, italic=True),
    "linbiolinumr": _sans(), "linbiolinumrb": _sans(bold=True),
    "linbiolinumri": _sans(italic=True), "libertinussans": _sans(),
    "lmsansdemicond": _sans(bold=True), "lmsansquot": _sans(),
    # --- Courier and its clones, and every monospace face -> Courier New ---
    # Monospace stays monospace whatever its width: code is aligned on the
    # character grid, and a proportional substitute destroys that even where
    # it happens to wrap better. CMTT measures 0.525em against Courier New's
    # 0.600 -- the widening is the price of keeping columns aligned, and it
    # is reported rather than hidden (CHANGELOG).
    "courier": _mono(), "couriernew": _mono(), "couriernewpsmt": _mono(),
    "cousine": _mono(), "liberationmono": _mono(), "nimbusmono": _mono(),
    "nimbusmonl": _mono(), "nimbusmonops": _mono(), "texgyrecursor": _mono(),
    "cursor": _mono(), "freemono": _mono(), "dejavusansmono": _mono(),
    "bitstreamverasansmono": _mono(), "droidsansmono": _mono(),
    "notosansmono": _mono(), "menlo": _mono(), "monaco": _mono(),
    "sfmono": _mono(), "lucidaconsole": _mono(), "lucidasanstypewriter": _mono(),
    "lucidatypewriter": _mono(), "andalemono": _mono(), "ptmono": _mono(),
    "ubuntumono": _mono(), "hack": _mono(), "anonymouspro": _mono(),
    "lettergothic": _mono(), "ocra": _mono(), "ocrastd": _mono(),
    "ocrb": _mono(), "firamono": _mono(), "cascadiacode": _mono(),
    "cascadiamono": _mono(), "beramono": _mono(), "dejavumono": _mono(),
    "cmutypewriter": _mono(), "lmmono": _mono(), "lmmonolt": _mono(),
    "linlibertinemono": _mono(), "linlibertinemonot": _mono(),
    "libertinusmono": _mono(),
    "lmmonoltcond": _mono(), "lmmonoslant": _mono(italic=True),
    "lmmonocaps": _mono(), "lmmonolightcond": _mono(),
    # --- symbol and dingbat faces ------------------------------------------
    # Written as Arial, as they always were: the glyphs arrive as Unicode (or
    # as private-use codes no family carries), and the face's class says
    # nothing about the text around them.
    "symbol": _symbol(), "symbolmt": _symbol(), "standardsymbolsps": _symbol(),
    "standardsyml": _symbol(), "zapfdingbats": _symbol(), "dingbats": _symbol(),
    "wingdings": _symbol(), "webdings": _symbol(), "opensymbol": _symbol(),
    "mtextra": _symbol(), "universal": _symbol(), "universalstd": _symbol(),
    "mathematicalpi": _symbol(), "mozilla": _symbol(),
}

# Computer Modern (Knuth's Type 1 names: CMR10, CMBX12, CMTT10 ...) and the
# EC/cm-super set (SFRM1095 ...), by shape code. Every TeX document in the
# corpus sets its body, headings and code in these, and none of their
# descriptors carries a usable Serif or FixedPitch bit: CMTT10 became Arial in
# TeX by Topic and the Bash manual, and CMBX12 headings became regular Arial.
# The math faces are serif-class so a stray math italic lands in the body's
# own face (CMMI is italic letters; CMSY/CMEX are symbols set in the body face).
for _code, _fam in (
        ("r", _serif()), ("b", _serif(bold=True)), ("bx", _serif(bold=True)),
        ("bxsl", _serif(bold=True, italic=True)),
        ("bxti", _serif(bold=True, italic=True)),
        ("sl", _serif(italic=True)), ("ti", _serif(italic=True)),
        ("u", _serif()), ("csc", _serif()), ("dunh", _serif()),
        ("fib", _serif()), ("ff", _serif()), ("fi", _serif(italic=True)),
        ("vtt", _serif()), ("mi", _serif(italic=True)),
        ("mib", _serif(bold=True, italic=True)), ("tex", _serif()),
        ("sy", _serif()), ("bsy", _serif(bold=True)), ("ex", _serif()),
        ("ss", _sans()), ("ssbx", _sans(bold=True)), ("ssi", _sans(italic=True)),
        ("ssdc", _sans(bold=True)), ("ssq", _sans()), ("ssqi", _sans(italic=True)),
        ("tt", _mono()), ("sltt", _mono(italic=True)), ("itt", _mono(italic=True)),
        ("tcsc", _mono())):
    _FAMILY_TABLE["cm" + _code] = _fam
for _code, _fam in (
        ("rm", _serif()), ("bx", _serif(bold=True)), ("sl", _serif(italic=True)),
        ("ti", _serif(italic=True)), ("bi", _serif(bold=True, italic=True)),
        ("bl", _serif(bold=True, italic=True)), ("cc", _serif()),
        ("xc", _serif(bold=True)), ("ss", _sans()), ("sx", _sans(bold=True)),
        ("si", _sans(italic=True)), ("so", _sans(bold=True, italic=True)),
        ("tt", _mono()), ("it", _mono(italic=True)), ("st", _mono(italic=True)),
        ("tc", _mono())):
    _FAMILY_TABLE["sf" + _code] = _fam
# LaTeX and AMS symbol faces (lasy, line, lcircle, logo, msam/msbm, Euler).
for _k in ("lasy", "lasyb", "line", "linew", "lcircle", "lcirclew", "logo",
           "logosl", "logobf", "msam", "msbm", "eufm", "eufb", "eurm", "eurb",
           "eusm", "eusb", "rsfs", "wasy", "stmary", "latinmodernmath",
           "texgyredejavumath", "cambriamath", "stixmath", "xitsmath"):
    _FAMILY_TABLE[_k] = _serif()

# CJK faces: the Latin slots get the class's core family as before, and the
# East Asian slot gets the face itself (east_asian_family). OOXML charset
# codes: 86 GB2312, 88 Big5, 80 Shift-JIS, 81 Hangul.
for _k, _name, _cls, _cs in (
        ("wenquanyizenhei", "WenQuanYi Zen Hei", "sans", "86"),
        ("wenquanyimicrohei", "WenQuanYi Micro Hei", "sans", "86"),
        ("notosanscjksc", "Noto Sans CJK SC", "sans", "86"),
        ("notosanscjktc", "Noto Sans CJK TC", "sans", "88"),
        ("notosanscjkjp", "Noto Sans CJK JP", "sans", "80"),
        ("notosanscjkkr", "Noto Sans CJK KR", "sans", "81"),
        ("notoserifcjksc", "Noto Serif CJK SC", "serif", "86"),
        ("notoserifcjktc", "Noto Serif CJK TC", "serif", "88"),
        ("notoserifcjkjp", "Noto Serif CJK JP", "serif", "80"),
        ("notoserifcjkkr", "Noto Serif CJK KR", "serif", "81"),
        ("sourcehansanssc", "Source Han Sans SC", "sans", "86"),
        ("sourcehansanscn", "Source Han Sans CN", "sans", "86"),
        ("sourcehansanstc", "Source Han Sans TC", "sans", "88"),
        ("sourcehansansjp", "Source Han Sans JP", "sans", "80"),
        ("sourcehansanskr", "Source Han Sans KR", "sans", "81"),
        ("sourcehanserifsc", "Source Han Serif SC", "serif", "86"),
        ("sourcehanserifcn", "Source Han Serif CN", "serif", "86"),
        ("sourcehanseriftc", "Source Han Serif TC", "serif", "88"),
        ("sourcehanserifjp", "Source Han Serif JP", "serif", "80"),
        ("sourcehanserifkr", "Source Han Serif KR", "serif", "81"),
        ("simsun", "SimSun", "serif", "86"), ("nsimsun", "NSimSun", "serif", "86"),
        ("simhei", "SimHei", "sans", "86"), ("dengxian", "DengXian", "sans", "86"),
        ("microsoftyahei", "Microsoft YaHei", "sans", "86"),
        ("kaiti", "KaiTi", "serif", "86"), ("fangsong", "FangSong", "serif", "86"),
        ("stsong", "STSong", "serif", "86"), ("stheiti", "STHeiti", "sans", "86"),
        ("adobesongstd", "Adobe Song Std", "serif", "86"),
        ("mingliu", "MingLiU", "serif", "88"), ("pmingliu", "PMingLiU", "serif", "88"),
        ("microsoftjhenghei", "Microsoft JhengHei", "sans", "88"),
        ("msmincho", "MS Mincho", "serif", "80"),
        ("mspmincho", "MS PMincho", "serif", "80"),
        ("msgothic", "MS Gothic", "sans", "80"),
        ("mspgothic", "MS PGothic", "sans", "80"),
        ("yugothic", "Yu Gothic", "sans", "80"), ("yumincho", "Yu Mincho", "serif", "80"),
        ("meiryo", "Meiryo", "sans", "80"), ("ipagothic", "IPAGothic", "sans", "80"),
        ("ipapgothic", "IPAPGothic", "sans", "80"),
        ("ipamincho", "IPAMincho", "serif", "80"),
        ("ipaexgothic", "IPAexGothic", "sans", "80"),
        ("ipaexmincho", "IPAexMincho", "serif", "80"),
        ("takaogothic", "TakaoGothic", "sans", "80"),
        ("hiraginosans", "Hiragino Sans", "sans", "80"),
        ("hirakakupron", "Hiragino Kaku Gothic ProN", "sans", "80"),
        ("hirakakupro", "Hiragino Kaku Gothic Pro", "sans", "80"),
        ("hiraminpron", "Hiragino Mincho ProN", "serif", "80"),
        ("hiraminpro", "Hiragino Mincho Pro", "serif", "80"),
        ("kozminpro", "Kozuka Mincho Pro", "serif", "80"),
        ("kozgopro", "Kozuka Gothic Pro", "sans", "80"),
        ("malgungothic", "Malgun Gothic", "sans", "81"),
        ("batang", "Batang", "serif", "81"), ("gulim", "Gulim", "sans", "81"),
        ("dotum", "Dotum", "sans", "81"), ("nanumgothic", "NanumGothic", "sans", "81"),
        ("nanummyeongjo", "NanumMyeongjo", "serif", "81"),
        ("arialunicodems", "Arial Unicode MS", "sans", "00")):
    _FAMILY_TABLE[_k] = Family(_cls, TNR if _cls == "serif" else ARIAL,
                               ea=(_name, _cs))

# Google Docs' native families pass through under their own names in both
# profiles, as they always have. Their class is stated so the parser and the
# font table can use it; matched exactly (never as a prefix), because short
# names like "lato" or "inter" are prefixes of unrelated families.
_NATIVE_SERIF = {"times new roman", "georgia", "merriweather", "playfair display",
                 "pt serif", "eb garamond", "lora", "libre baskerville",
                 "crimson text", "dm serif display", "ibm plex serif", "bitter",
                 "noto serif", "vollkorn"}
# Vollkorn and Ubuntu: Google Fonts the writer has mapped to themselves since
# the y20 work (a self-mapping needs no metric claim; metric_fit leaves an
# unmeasured family alone). Vollkorn is recorded there as an EXPERIMENT whose
# live word-ratio decides whether it stays.
_NATIVE_EXTRA = {"vollkorn": "Vollkorn"}


def _native_class(name: str) -> str:
    low = name.lower()
    if any(k in low for k in ("mono", "code", "consolas", "inconsolata", "courier")):
        return "mono"
    return "serif" if low in _NATIVE_SERIF else "sans"


_DISPLAY_WORD = {"pt": "PT", "dm": "DM", "eb": "EB", "ibm": "IBM", "ms": "MS",
                 "jetbrains": "JetBrains"}


def _display(name: str) -> str:
    """'trebuchet ms' -> 'Trebuchet MS': the family name a renderer looks up."""
    return " ".join(_DISPLAY_WORD.get(w, w.capitalize()) for w in name.split())


_NATIVE = {re.sub(r"[^a-z]", "", n): Family(_native_class(n), _display(n))
           for n in sorted(GDOCS_NATIVE)}
for _k, _disp in _NATIVE_EXTRA.items():
    _NATIVE[_k] = Family(_native_class(_disp), _disp)

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
# The table exists because these are not base-14 families and no table of
# advance widths covers them. `metrics.Base14Metrics` shapes Arial, Times New
# Roman and Courier New from the published Adobe metrics and answers None for
# everything else, which is exactly the set below -- Libre Baskerville, Noto
# Serif, the Docs-native faces. So the ratio has to arrive as a measured
# constant, the same way NATURAL_FACTORS carries Docs' line heights.
#
# (This comment used to say metrics were NullMetrics by default and that MuPDF's
# tables were AGPL and unvendorable. The second half conflated MuPDF's copy with
# the published data; see exactdoc/metrics.py. The first half is no longer true
# at all. Neither changes the case for this table.)
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
    # MEASURED DIFFERENTLY FROM EVERY ENTRY ABOVE, and the difference matters.
    #
    # Libre Baskerville is not installed here, so there is no file to read: this
    # number comes from testkit/probe_font_metrics.py in live pass 3, measured
    # inside Google Docs itself. The probe's raw reading was 0.527269 over its
    # concatenated segments; dividing by the +0.70% offset its three
    # offline-measurable controls showed in the same export, and rescaling from
    # the segments onto METRIC_REFERENCE, gives the value below.
    #
    # That calibration is checkable rather than asserted: Noto Serif, carried
    # through the identical arithmetic, lands at -6.30% against the -6.18% its
    # own font file gives.
    #
    # It is worth the unusual provenance because it is a near-exact match for
    # DejaVu Serif -- -0.04% against Noto Serif's -6.3% -- which is what l1's
    # remaining re-wrap costs. Docs rendered LibreBaskerville-Regular for all
    # 349 probe characters, so the family is genuinely present and not
    # substituted.
    "librebaskerville":  (0.520687, "serif"),
    # Consolas is a true monospace at 0.550em (every glyph's advance, read
    # from the font file itself: hhea upm 2048, advance 1126). Now that it
    # maps to itself this entry is what keeps `metric_fit` from measuring a
    # 0% deviation and leaving the family alone.
    "consolas":          (0.550000, "mono"),
    # NOT HERE, and the attempt is worth the record: Vollkorn and Ubuntu
    # were "measured" from the Typst specimen y20's own spans, and the two
    # passes disagreed by 12% and 35% depending on which lines were
    # sampled -- justified spans carry the justification stretch, and the
    # unstretched remainder of that document is letterspaced display text.
    # A document is not a font file; neither number was trustworthy, and an
    # absent measurement is not a deviation of zero. The honest route for
    # these families is a probe_font_metrics ride-along in a live pass
    # (the method that measured Libre Baskerville).
}

# Substitution candidates, restricted to families already asserted as natively
# rendered by Google Docs (GDOCS_NATIVE) AND measured above.
_CANDIDATES = {
    "serif": ("Times New Roman", "Georgia", "Noto Serif", "Libre Baskerville"),
    "sans": ("Arial", "Verdana", "Noto Sans"),
    "mono": ("Courier New",),
}

# Substitute a family only when the gain is worth changing the typeface.
#
# Measured basis: the corpus's metric-compatible mappings sit at exactly 0.0% --
# Liberation Serif/Sans/Mono against Times New Roman/Arial/Courier New all
# measure 1.000000, because they are metric clones by design. The largest
# honest residual among working documents is DejaVu Sans Mono -> Courier New at
# -0.32%. 5% is comfortably clear of both, and of the half-point font-size
# quantisation this writer already accepts (_quantised_size), which moves a
# line's advance by up to ~0.5% on its own.
METRIC_SUBSTITUTE_DEV = 0.05

# Run-level tracking (w:spacing on rPr) was the second half of this fix and is
# RETIRED: Google Docs discards it on import.
#
# Measured in live pass 2. The file emitted 7 twips of tracking per run on
# l1_word_native, which would have brought its packing ratio to 1.0018. The
# export came back at 1.0637 -- within 0.3% of the 1.067 predicted for "family
# honoured, spacing dropped", and nowhere near 1.0018. Docs rendered
# NotoSerif-Regular, so the substitution took effect and only the tracking was
# ignored. The two mechanisms were deliberately chosen to fail independently,
# and this is exactly that: one worked, one did not.
#
# So the residual 6.3% between DejaVu Serif and the closest family Docs is known
# to render is currently irreducible, and is what still moves l1's later line
# breaks. Closing it needs a family closer than Noto Serif, which needs a Docs
# font-metrics probe of candidates whose files are not available to measure
# offline -- the same ride-along probe pattern testkit/probe_cover_band.py used.
GDOCS_HONOURS_RUN_TRACKING = False


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


_SUBSET_RE = re.compile(r"^[A-Z]{6}\+")
# A key this short is matched exactly and never as a prefix: "cmr", "helv",
# "c" and "p" would otherwise swallow unrelated families.
_PREFIX_MIN = 5


def _split_name(pdf_font: str):
    """'ABCDEF+NimbusRomNo9L-Regu-Slant_167' -> ('NimbusRomNo9L', 'Regu-Slant_167').

    The family is what precedes the first hyphen or comma -- the PostScript
    convention (`Family-Style`) and Acrobat's (`Family,Style`). A name with no
    separator is all family, and its trailing style words are stripped by
    `family_keys` instead ("FreeSerifBold", "TimesNewRomanPSMT").
    """
    name = _SUBSET_RE.sub("", pdf_font or "").strip()
    m = re.match(r"^([^-,]+)[-,](.*)$", name)
    if m and m.group(1).strip():
        return m.group(1).strip(), m.group(2)
    return name, ""


def _candidate_keys(pdf_font: str) -> list:
    """The full name's keys, then the family part's -- specific to general."""
    fam, _ = _split_name(pdf_font)
    keys = family_keys(pdf_font)
    for k in family_keys(fam):
        if k not in keys:
            keys.append(k)
    return keys


@functools.lru_cache(maxsize=4096)
def lookup_family(pdf_font: str) -> Optional[Family]:
    """The family-table row for a PDF font name, or None for an unknown face.

    Exact keys first, most specific first (the table row and then Google Docs'
    native set); then the longest table key of at least `_PREFIX_MIN` letters
    that prefixes a candidate -- which is how "HelveticaNeueLTStd-Roman" and
    "HelveticaWorld-Bold" reach `helvetica` without a row each.
    """
    keys = _candidate_keys(pdf_font)
    for k in keys:
        hit = _FAMILY_TABLE.get(k) or _NATIVE.get(k)
        if hit is not None:
            return hit
    best = None
    for k in keys:
        for tk, fam in _FAMILY_TABLE.items():
            if len(tk) >= _PREFIX_MIN and k.startswith(tk) and \
                    (best is None or len(tk) > len(best[0])):
                best = (tk, fam)
    return best[1] if best else None


# Weight and slant words as they appear in the STYLE part of a PostScript name,
# abbreviations included: URW's base 35 (Regu, Medi, Ital, Obli, Demi), Linotype
# (Bd, BdCn, It, BlkCn, BdOu) and the rest. Matched as whole tokens of the style
# part, never as substrings of the family -- "it" inside "Summit" is not italic.
_BOLD_WORDS = {"bold", "bd", "black", "blk", "heavy", "hv", "demi", "demibold",
               "semibold", "semibd", "smbd", "sembd", "extrabold", "xbold", "xbd",
               "ultrabold", "extrablack", "fat"}
_LIGHT_WORDS = {"light", "lt", "thin", "hairline", "ligh", "extralight",
                "ultralight", "semilight"}
_ITALIC_WORDS = {"italic", "ital", "it", "ita", "oblique", "obli", "obl",
                 "slant", "slanted", "kursiv", "inclined"}


def _style_words(pdf_font: str) -> set:
    fam, style = _split_name(pdf_font)
    words = set()
    for part in re.split(r"[^A-Za-z0-9]+", style):
        words.update(w.lower() for w in
                     re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+", part))
    # trailing style words glued to the family: FreeSerifBold, ArialItalicMT
    name = fam
    while True:
        m = _STYLE_RE.search(name)
        if not m:
            break
        words.add(m.group(1).lower())
        name = name[:m.start()]
    return words


class Traits(NamedTuple):
    """What a font NAME says about the face. None = the name does not say."""
    cls: Optional[str]
    bold: bool
    italic: bool


@functools.lru_cache(maxsize=4096)
def font_traits(pdf_font: str) -> Traits:
    """Class, weight and slant evidence carried by the PostScript name.

    The parser ORs this with the descriptor flags for bold and italic, and
    prefers it to them for class -- see the module docstring for why the
    flags cannot be trusted in either direction. Measured on the corpus
    census: CMBX12 headings (y26), NimbusRomNo9L-Medi (y03/y25, Times-Bold's
    clone), HelveticaNeueLTStd-Bd/-BdCn (IRS forms), HelveticaLTStd-Blk and
    ITCFranklinGothicStd-Demi all arrived NOT bold; EUAlbertina-ReguItal
    arrived not italic.
    """
    fam = lookup_family(pdf_font)
    words = _style_words(pdf_font)
    bold = bool(words & _BOLD_WORDS) and not (words & _LIGHT_WORDS and
                                              "bold" not in words)
    if fam is not None and fam.medium_bold and words & {"medi", "medium"}:
        bold = True
    italic = bool(words & _ITALIC_WORDS)
    if fam is not None:
        bold = bold or fam.bold
        italic = italic or fam.italic
    return Traits(fam.cls if fam is not None else None, bold, italic)


def map_font(pdf_font: str, mono: bool = False, serif: bool = False,
             profile: str = "standard") -> str:
    """The family the given output profile writes for a PDF font.

    `mono`/`serif` are the parser's flags and only decide a name the family
    table does not know. `profile` is "standard" or "gdocs"; anything else is
    treated as standard.
    """
    fam = lookup_family(pdf_font)
    if fam is not None:
        if profile == "gdocs" and fam.gdocs:
            return fam.gdocs
        return fam.standard
    # heuristic fallback
    if mono:
        return "Courier New"
    if serif:
        return "Times New Roman"
    return "Arial"


def _is_east_asian(ch: str) -> bool:
    o = ord(ch)
    return (0x2E80 <= o <= 0x303F or 0x3040 <= o <= 0x33FF or
            0x3400 <= o <= 0x4DBF or 0x4E00 <= o <= 0x9FFF or
            0xA000 <= o <= 0xA4CF or 0xAC00 <= o <= 0xD7AF or
            0xF900 <= o <= 0xFAFF or 0xFE30 <= o <= 0xFE4F or
            0xFF00 <= o <= 0xFFEF)


def east_asian_family(pdf_font: str, text: str,
                      profile: str = "standard") -> Optional[str]:
    """The run's w:eastAsia family, or None to keep the Latin family there.

    Every run used to carry its Latin family in all four rFonts slots, so a
    CJK run set in WenQuanYi Zen Hei asked for Arial in the slot Word and
    LibreOffice consult for CJK characters, and the renderer fell back to
    whatever covered the glyph. Measured in the canonical container on
    c4_i18n: LibreOffice resolved the Japanese line to IPAPGothic rather
    than the source's WenQuanYi, and naming the source face moved the page
    from within2pt 0.440 to 0.621 and dy_p50 0.80 -> 0.15pt.

    Only for a run that contains East Asian text AND whose source face is a
    CJK family the table knows: the face itself is then the exact answer,
    and Word substitutes its own East Asian default where it is missing.

    `w:cs` is not this function's: see complex_script_family, which names a
    complex-script run's face once the run is in logical order (WP14).
    Standard profile only; what Google Docs does with a declared East Asian
    face has not been graded live.
    """
    if profile != "standard" or not text:
        return None
    fam = lookup_family(pdf_font)
    if fam is None or fam.ea is None:
        return None
    if not any(_is_east_asian(ch) for ch in text):
        return None
    return fam.ea[0]


# Complex scripts: the characters Word sets from a run's complex-script slot
# (rFonts/@cs, szCs, bCs, iCs, lang/@bidi) and LibreOffice from its CTL
# attributes, rather than from the Latin ones. A run that carries such text and
# only the Latin size is set at the renderer's DEFAULT complex-script size: on
# c4_i18n the Arabic and Hebrew lines came out of LibreOffice visibly smaller
# than the 11pt they were asked for, and the Hebrew re-wrapped onto two lines.
# (lo, hi, language tag for lang/@bidi, right-to-left)
_COMPLEX_SCRIPTS = (
    (0x0590, 0x05FF, "he-IL", True), (0xFB1D, 0xFB4F, "he-IL", True),
    (0x0600, 0x06FF, "ar-SA", True), (0x0750, 0x077F, "ar-SA", True),
    (0x08A0, 0x08FF, "ar-SA", True), (0xFB50, 0xFDFF, "ar-SA", True),
    (0xFE70, 0xFEFF, "ar-SA", True), (0x0700, 0x074F, "syr-SY", True),
    (0x0780, 0x07BF, "dv-MV", True),
    (0x0900, 0x097F, "hi-IN", False), (0x0980, 0x09FF, "bn-IN", False),
    (0x0A00, 0x0A7F, "pa-IN", False), (0x0A80, 0x0AFF, "gu-IN", False),
    (0x0B00, 0x0B7F, "or-IN", False), (0x0B80, 0x0BFF, "ta-IN", False),
    (0x0C00, 0x0C7F, "te-IN", False), (0x0C80, 0x0CFF, "kn-IN", False),
    (0x0D00, 0x0D7F, "ml-IN", False), (0x0D80, 0x0DFF, "si-LK", False),
    (0x0E00, 0x0E7F, "th-TH", False), (0x0E80, 0x0EFF, "lo-LA", False),
    (0x0F00, 0x0FFF, "bo-CN", False), (0x1000, 0x109F, "my-MM", False),
    (0x1780, 0x17FF, "km-KH", False),
)
# Letters only Persian writes in the Arabic block (peh, tcheh, jeh, gaf,
# keheh, Farsi yeh): their presence makes a run Persian, not Arabic.
_PERSIAN = frozenset("پچژگکی")


def complex_script(text: str):
    """(language tag or None, has RTL letters) for a run's text.

    The tag is the first complex script the text contains, which is what
    lang/@bidi declares for the run; None when it holds no complex script.
    """
    lang, rtl = None, False
    for ch in text or "":
        o = ord(ch)
        if o < 0x0590:
            continue
        for lo, hi, tag, is_rtl in _COMPLEX_SCRIPTS:
            if lo <= o <= hi:
                if lang is None:
                    lang = tag
                rtl = rtl or is_rtl
                break
    if lang == "ar-SA" and any(ch in _PERSIAN for ch in text):
        lang = "fa-IR"
    return lang, rtl


_CS_STYLE_TAIL = re.compile(
    r"(?:[,\-](?:bold|italic|oblique|regular|roman|medium|semibold|light|"
    r"bolditalic|boldoblique|book|mt|psmt))+$|(?<=[a-z])(?:bold|italic)$",
    re.I)


def complex_script_family(pdf_font: str, profile: str = "standard") -> Optional[str]:
    """The run's w:cs family, or None to keep the Latin mapping there.

    A complex-script face the family table does not know -- Word's own David
    and Mangal, Persian B Nazanin, WeasyPrint's Noto Naskh -- used to be
    replaced in the complex-script slot by the Latin heuristic, Arial. For
    Hebrew that is a different design 12.5% wider: measured over y49's first
    six pages, Arial's Hebrew (Liberation Sans in the canonical renderer)
    against David's own advances in the PDF, 10,105 characters; every line
    re-wrapped longer and the document doubled. Naming the source face is the
    exact answer where it is installed (David, Mangal and Simplified Arabic
    ship with Windows), and where it is not, the renderer falls back to a face
    covering the script -- the pinned LibreOffice resolves an unknown name to
    FreeSerif for Hebrew, Arabic, Devanagari and Thai alike (probed: 9 names),
    2.6% wider than David.

    A family the table knows keeps its mapping (Arial, Times New Roman,
    Tahoma all carry Hebrew and Arabic in Word) -- except the open faces in
    _CS_FAMILY_NAMES, whose PostScript names do not spell their family. WP3
    measured naming c4_i18n's DejaVu Sans here as a regression (dy_p90 2.2 ->
    13.6pt), but on runs in visual order in left-to-right paragraphs; with the
    runs in logical order under w:bidi the same naming renders the source's
    own face and wraps where it wrapped: c4 within2pt 0.621 -> 0.872, dy_p90
    2.2 -> 0.8pt, both lanes' gate numbers otherwise inside tolerance.
    Standard profile only.
    """
    if profile != "standard" or not pdf_font:
        return None
    name = _CS_STYLE_TAIL.sub("", pdf_font.strip())
    known = _CS_FAMILY_NAMES.get(re.sub(r"[\s_-]", "", name).lower())
    if known:
        return known
    if lookup_family(pdf_font) is not None:
        return None
    name = name.replace("-", " ").strip()
    return name or None


# Open faces with complex-script coverage whose PostScript names do not spell
# their family names: what the complex-script slot must say for the renderer
# that has them (the canonical one has DejaVu and FreeFont) to find them.
_CS_FAMILY_NAMES = {
    "dejavusans": "DejaVu Sans", "dejavuserif": "DejaVu Serif",
    "dejavusanscondensed": "DejaVu Sans Condensed",
    "freeserif": "FreeSerif", "freesans": "FreeSans",
    "notonaskharabic": "Noto Naskh Arabic", "notonaskh": "Noto Naskh Arabic",
    "notosansarabic": "Noto Sans Arabic", "notosanshebrew": "Noto Sans Hebrew",
    "notoserifhebrew": "Noto Serif Hebrew",
    "notosansdevanagari": "Noto Sans Devanagari", "notosansthai": "Noto Sans Thai",
}


# fontTable descriptors by class: what Word itself writes for these families,
# and what its substitution reads when the reader lacks the face.
_CLASS_DESC = {"serif": ("roman", "variable"), "sans": ("swiss", "variable"),
               "mono": ("modern", "fixed")}


def font_table_desc(family: str):
    """(w:family, w:pitch, w:charset) for a written family name.

    ("auto", "variable", "00") for a family the table does not know -- what
    Word writes for a family it has no opinion about.
    """
    fam = lookup_family(family)
    if fam is None:
        return ("auto", "variable", "00")
    desc = _CLASS_DESC.get(fam.cls, ("auto", "variable"))
    return desc + ((fam.ea[1] if fam.ea else "00"),)


def family_metrics(name):
    """(advance_per_char_at_1pt, class) for a family name, or None."""
    for key in family_keys(name):
        hit = FAMILY_METRICS.get(key)
        if hit is not None:
            return hit
    return None


def metric_fit(pdf_font: str, mono: bool = False, serif: bool = False):
    """Google Docs profile: the family whose advance width fits the source.

    The standard mapping is metric-compatible by design -- Helvetica->Arial,
    Times->Times New Roman, and the Liberation faces measure *exactly* 1.000000
    against their Microsoft counterparts. Where it is not, the substitute's
    glyphs are a different width, the same text needs a different number of
    lines, every paragraph re-wraps, and words land nowhere near their source
    position. Measured on l1_word_native, whose DejaVu Serif source maps to a
    Times New Roman 21.6% narrower: 85 characters per line became 105, and the
    document scored dx_p50 63.65pt with dy_p50 19.35pt -- one root cause for
    both, since re-wrapping also drops whole lines.

    If the mapped family deviates by more than METRIC_SUBSTITUTE_DEV, pick the
    candidate of the same class whose measured advance is closest to the
    source. DejaVu Serif goes Times New Roman (-21.6%) -> Noto Serif (-6.3%);
    DejaVu Sans goes Arial (-12.6%) -> Verdana (+0.2%). Live pass 2 confirmed
    Docs renders the substituted family: l1_word_native's packing ratio went
    1.2935 -> 1.0637 and its first body line wrapped exactly as the source did.

    Returns the unmodified mapping whenever either side is unmeasured. An
    absent measurement is not a deviation of zero, and this is the same
    discipline `metrics.NullMetrics` applies: act only on a number you actually
    have.

    A substituted family MUST also have a `docxout.NATURAL_FACTORS` entry.
    Swapping in a family without one silently reuses NATURAL_DEFAULT for the
    exact->multiple line-height translation, and Noto Serif's natural height is
    1.360 against that default's 1.144: pass 2 rendered l1 at a 17.48pt pitch
    where the source used 14.70. Fixing the advance width while breaking the
    line height trades one drift for another. `tests/test_font_metric_fit.py`
    holds the two tables together.
    """
    mapped = map_font(pdf_font, mono=mono, serif=serif, profile="gdocs")
    src = family_metrics(pdf_font)
    cur = family_metrics(mapped)
    if src is None or cur is None:
        return mapped
    src_adv, cls = src
    if not src_adv:
        return mapped
    family, adv = mapped, cur[0]
    if abs(adv / src_adv - 1.0) > METRIC_SUBSTITUTE_DEV:
        for cand in _CANDIDATES.get(cls, ()):
            got = family_metrics(cand)
            if got is None:
                continue
            if abs(got[0] / src_adv - 1.0) < abs(adv / src_adv - 1.0):
                family, adv = cand, got[0]
    return family
