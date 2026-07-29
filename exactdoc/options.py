"""One product profile, shared by the API, the CLI, CI, the docs and the evidence.

There used to be three defaults, and none of them was the one the numbers came
from:

    Python API `convert()`      0 refine rounds
    console CLI                 2 refine rounds
    CI "refined/shipped" lane   3 refine rounds

The README quoted the three-round lane as the shipped default. So the published
0.529 within-2pt was measured on a profile that neither surface actually ran,
and "reproduce it with `convert()`" produced 0.366 -- the raw number -- with no
error anywhere to say why. A measurement that describes no shipping
configuration is not evidence, it is a coincidence.

`PRODUCT` below is that one configuration. Every surface resolves its defaults
from it; the gate measures it by name; the docs quote its numbers. `RAW` is the
deliberate zero-refine sibling, kept because `refine()` tunes against the same
renderer the gate then measures with, so a refined-only figure can improve
because the loop memorised the oracle rather than because the converter got
better. Only the pair is meaningful, which is why both are named here rather
than passed as a number at three call sites.

Changing `PRODUCT.refine_rounds` changes what users get AND what the published
numbers mean. Re-record the gate baseline in the same commit.
"""
import dataclasses
from typing import Optional

# Every backend name the seam accepts, and the one that ships. `pdfium` becomes
# the default in the permissive-runtime phase; it is a real option today so that
# the parity gate can select it without monkey-patching `convert.parse_pdf`,
# which it used to do -- and which meant the gate measured a module it had
# mutated rather than the product.
BACKENDS = ("pymupdf", "pdfium")
TARGETS = ("none", "libreoffice", "gdocs")

# Aliases accepted from users and environment variables. Kept narrow and
# explicit: a silently-unrecognised backend name would fall back to the default
# and report numbers for the wrong parser.
_BACKEND_ALIASES = {"fitz": "pymupdf", "mupdf": "pymupdf", "default": "pymupdf",
                    "pypdfium2": "pdfium"}
_TARGET_ALIASES = {"off": "none", "lo": "libreoffice", "soffice": "libreoffice",
                   "word": "libreoffice", "google": "gdocs",
                   "googledocs": "gdocs", "google-docs": "gdocs"}


def canonical_backend(name: str) -> str:
    n = (name or "").strip().lower()
    n = _BACKEND_ALIASES.get(n, n)
    if n not in BACKENDS:
        raise ValueError("unknown backend %r; choose from %s"
                         % (name, ", ".join(BACKENDS)))
    return n


def canonical_target(name: str) -> str:
    n = (name or "").strip().lower()
    n = _TARGET_ALIASES.get(n, n)
    if n not in TARGETS:
        raise ValueError("unknown target %r; choose from %s"
                         % (name, ", ".join(TARGETS)))
    return n


@dataclasses.dataclass(frozen=True)
class ConversionOptions:
    """Immutable, validated conversion settings.

    Frozen on purpose. The writer's target mode used to be a module global that
    `write_docx` set and restored, so two concurrent conversions with different
    targets could each observe the other's encoding. Options that cannot be
    mutated after validation are the first half of fixing that; passing them
    down instead of reading a global is the second.
    """

    backend: str = "pymupdf"
    target: str = "libreoffice"
    refine_rounds: int = 3
    dpi: int = 240
    ladder: bool = False
    verbose: bool = False

    def __post_init__(self):
        object.__setattr__(self, "backend", canonical_backend(self.backend))
        object.__setattr__(self, "target", canonical_target(self.target))
        if not isinstance(self.refine_rounds, int) or self.refine_rounds < 0:
            raise ValueError("refine_rounds must be a non-negative int, got %r"
                             % (self.refine_rounds,))
        if not isinstance(self.dpi, int) or not (36 <= self.dpi <= 1200):
            raise ValueError("dpi must be an int in 36..1200, got %r" % (self.dpi,))

    def replace(self, **kw) -> "ConversionOptions":
        """A new options object with `kw` overridden. Revalidates."""
        return dataclasses.replace(self, **kw)

    def profile_id(self) -> str:
        """Short stable name for reports: what was actually measured."""
        return "%s/%s/refine%d@%ddpi" % (self.backend, self.target,
                                         self.refine_rounds, self.dpi)

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


# The shipped configuration. This is the profile the README's numbers describe,
# the profile the CI "product" lane measures, and the profile a bare
# `convert(pdf)` or `exactdoc file.pdf` runs.
PRODUCT = ConversionOptions()

# The uncontaminated comparison lane: no closed loop, so no chance of the
# oracle being memorised. Not a fallback and not a fast mode -- a control.
RAW = PRODUCT.replace(refine_rounds=0)

# Kept for callers that want the name rather than the object.
DEFAULT_OPTIONS = PRODUCT
DEFAULT_BACKEND = PRODUCT.backend
DEFAULT_TARGET = PRODUCT.target
DEFAULT_REFINE_ROUNDS = PRODUCT.refine_rounds
DEFAULT_DPI = PRODUCT.dpi

# Lane names. The gate, the baseline file and the evidence artifact all key on
# these, so they live with the profiles they describe rather than being spelled
# out as string literals in three files.
LANES = {"raw": RAW, "product": PRODUCT}


def resolve(options: Optional[ConversionOptions] = None, **overrides
            ) -> ConversionOptions:
    """The one place a surface turns partial arguments into full options.

    `None` overrides are dropped, so a CLI or API caller can pass every
    argument it has and let the profile supply the rest. That is what keeps the
    three surfaces from drifting apart again: none of them writes a default
    value of its own.
    """
    base = options if options is not None else PRODUCT
    kw = {k: v for k, v in overrides.items() if v is not None}
    return base.replace(**kw) if kw else base
