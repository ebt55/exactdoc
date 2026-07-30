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

## Two axes, because `target` was answering two questions

`target` meant both "how is this DOCX serialised?" and "which program renders it
during the feedback loop?", and those are independent. The consequence was not
cosmetic: there was no way to ask for **Google-Docs-safe OOXML produced
offline**, which is the configuration this project intends to ship. Wanting
Docs-shaped output implied wanting to upload the document to Google.

    output_profile   how the OOXML is written. Pure serialisation, offline,
                     deterministic, no network, no credentials.
    oracle           what renders the result during refinement. Costs a
                     subprocess or a network round trip; `none` is a real and
                     common answer.

`target=` is still accepted for one alpha cycle and maps onto the pair, with one
deliberate change of behaviour: **`target="gdocs"` now selects the Google-safe
*profile* and does not by itself authorise an upload.** Under the old field the
two were inseparable, so a caller asking for Docs-shaped formatting silently got
their document sent to a third party. Requesting the cloud *oracle* needs
`allow_cloud_upload=True`, per call, and no environment variable can grant it.
"""
import dataclasses
import warnings
from typing import Optional

from .errors import CloudConsentRequiredError, ConfigurationError

# Every backend name the seam accepts, and the one that ships. `pdfium` becomes
# the default in the permissive-runtime phase; it is a real option today so that
# the parity gate can select it without monkey-patching `convert.parse_pdf`,
# which it used to do -- and which meant the gate measured a module it had
# mutated rather than the product.
BACKENDS = ("pymupdf", "pdfium")

# How the OOXML is written. `standard` is the Office/LibreOffice-oriented output
# this project has always produced. It is deliberately NOT called "word": Word
# has never been independently measured here, and naming a profile after a
# renderer nobody has tested against is the kind of claim this repository keeps
# having to retract.
OUTPUT_PROFILES = ("standard", "gdocs")

# What renders the DOCX during refinement. `none` means no feedback loop and no
# external process at all -- the fastest, most deterministic, most private
# option, and the one the intended shipping profile uses.
ORACLES = ("none", "libreoffice", "gdocs")

# Retained so `TARGETS` importers keep working during the deprecation window.
TARGETS = ("none", "libreoffice", "gdocs")

_BACKEND_ALIASES = {"fitz": "pymupdf", "mupdf": "pymupdf", "default": "pymupdf",
                    "pypdfium2": "pdfium"}
_ORACLE_ALIASES = {"off": "none", "lo": "libreoffice", "soffice": "libreoffice",
                   "word": "libreoffice", "google": "gdocs",
                   "googledocs": "gdocs", "google-docs": "gdocs"}
_PROFILE_ALIASES = {"office": "standard", "libreoffice": "standard",
                    "default": "standard", "google": "gdocs",
                    "googledocs": "gdocs", "google-docs": "gdocs"}

# How a legacy `target=` becomes the pair. `gdocs` maps to the PROFILE only:
# formatting is not consent.
_LEGACY_TARGET = {
    "none": ("standard", "none"),
    "libreoffice": ("standard", "libreoffice"),
    "gdocs": ("gdocs", "none"),
}


def _canon(name, table, allowed, what):
    n = (name or "").strip().lower()
    n = table.get(n, n)
    if n not in allowed:
        raise ConfigurationError(
            "unknown %s %r; choose from %s" % (what, name, ", ".join(allowed)))
    return n


def canonical_backend(name: str) -> str:
    return _canon(name, _BACKEND_ALIASES, BACKENDS, "backend")


def canonical_output_profile(name: str) -> str:
    return _canon(name, _PROFILE_ALIASES, OUTPUT_PROFILES, "output profile")


def canonical_oracle(name: str) -> str:
    return _canon(name, _ORACLE_ALIASES, ORACLES, "oracle")


def canonical_target(name: str) -> str:
    """Deprecated. Kept so external callers do not break mid-cycle."""
    return _canon(name, _ORACLE_ALIASES, TARGETS, "target")


def split_target(target: str):
    """A legacy `target=` -> (output_profile, oracle). Raises on an unknown name."""
    return _LEGACY_TARGET[canonical_target(target)]


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
    output_profile: str = "standard"
    oracle: str = "libreoffice"
    refine_rounds: int = 3
    dpi: int = 240
    ladder: bool = False
    verbose: bool = False
    #: Per-call consent for an oracle that sends the document to a third party.
    #: Never read from the environment: an exported variable must not be able to
    #: authorise an upload on a caller's behalf.
    allow_cloud_upload: bool = False

    def __post_init__(self):
        object.__setattr__(self, "backend", canonical_backend(self.backend))
        object.__setattr__(self, "output_profile",
                           canonical_output_profile(self.output_profile))
        object.__setattr__(self, "oracle", canonical_oracle(self.oracle))
        if not isinstance(self.refine_rounds, int) or self.refine_rounds < 0:
            raise ConfigurationError(
                "refine_rounds must be a non-negative int, got %r"
                % (self.refine_rounds,))
        if not isinstance(self.dpi, int) or not (36 <= self.dpi <= 1200):
            raise ConfigurationError(
                "dpi must be an int in 36..1200, got %r" % (self.dpi,))

        # Refinement without a renderer is not refinement. This used to resolve
        # itself silently: the loop asked for a renderer, got None, and the
        # conversion continued open-loop with the message printed only under
        # --verbose. The caller received a different product under the same exit
        # code, which is how a published number came to describe a profile no
        # surface ran.
        if self.refine_rounds > 0 and self.oracle == "none":
            raise ConfigurationError(
                "refine_rounds=%d requires an oracle to refine against, but "
                "oracle='none'. Either set oracle='libreoffice' (or 'gdocs' with "
                "allow_cloud_upload=True), or set refine_rounds=0 to convert "
                "open-loop deliberately." % self.refine_rounds)

        # Consent is per call and cannot come from the environment.
        if self.oracle == "gdocs" and not self.allow_cloud_upload:
            raise CloudConsentRequiredError(
                "oracle='gdocs' uploads the document to Google Drive, converts "
                "it, exports it and deletes the temporary copy. That requires "
                "explicit consent: pass allow_cloud_upload=True (API) or "
                "--allow-cloud-upload (CLI). Selecting output_profile='gdocs' "
                "does NOT require this -- Google-Docs-safe formatting is "
                "produced entirely offline.")

    # --- legacy `target` --------------------------------------------------

    @property
    def target(self) -> str:
        """The nearest legacy name for this pair. Read-only.

        Lossy by construction -- that is the point. `standard`+`gdocs`-oracle and
        `gdocs`-profile+`none` are both real configurations that the single field
        could not express.
        """
        if self.oracle != "none":
            return self.oracle
        return "gdocs" if self.output_profile == "gdocs" else "none"

    def replace(self, **kw) -> "ConversionOptions":
        """A new options object with `kw` overridden. Revalidates.

        Accepts a legacy `target=` and translates it, so existing callers keep
        working for one alpha cycle.
        """
        if "target" in kw:
            target = kw.pop("target")
            if target is not None:
                warnings.warn(
                    "target= is deprecated and will be removed before 1.0; it "
                    "conflated output_profile (how the DOCX is written) with "
                    "oracle (what renders it during refinement). "
                    "target=%r means output_profile=%r, oracle=%r. Note that "
                    "target='gdocs' no longer authorises a cloud upload on its "
                    "own." % ((target,) + split_target(target)),
                    DeprecationWarning, stacklevel=2)
                profile, oracle = split_target(target)
                for key, value in (("output_profile", profile),
                                   ("oracle", oracle)):
                    if key in kw and kw[key] is not None and kw[key] != value:
                        raise ConfigurationError(
                            "conflicting arguments: target=%r implies %s=%r but "
                            "%s=%r was also given. Pass the new arguments only."
                            % (target, key, value, key, kw[key]))
                    kw[key] = value
        return dataclasses.replace(self, **kw)

    def profile_id(self) -> str:
        """Short stable name for reports: what was actually measured.

        Names both axes. The old form collapsed them into one slot, so an
        evidence artifact could not distinguish output written for Docs from
        output refined against Docs.
        """
        return "%s/%s/%s/refine%d@%ddpi" % (
            self.backend, self.output_profile, self.oracle,
            self.refine_rounds, self.dpi)

    def as_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["profile_id"] = self.profile_id()
        return d


# The shipped configuration. This is the profile the README's numbers describe,
# the profile the CI "product" lane measures, and the profile a bare
# `convert(pdf)` or `exactdoc file.pdf` runs.
#
# `standard` + `libreoffice` is exactly what `target="libreoffice"` meant, so
# splitting the field moved nothing. The intended shipping profile --
# pdfium/gdocs/none/refine0 -- is a CANDIDATE and is not adopted until the
# protected Google Docs qualification gate passes (plan GDOCS-05).
PRODUCT = ConversionOptions()

# The uncontaminated comparison lane: no closed loop, so no chance of the
# oracle being memorised. Not a fallback and not a fast mode -- a control.
#
# `oracle="none"` as well as `refine_rounds=0`: naming a renderer it will never
# call made the raw lane look like it had one.
RAW = PRODUCT.replace(refine_rounds=0, oracle="none")

# Kept for callers that want the name rather than the object.
DEFAULT_OPTIONS = PRODUCT
DEFAULT_BACKEND = PRODUCT.backend
DEFAULT_OUTPUT_PROFILE = PRODUCT.output_profile
DEFAULT_ORACLE = PRODUCT.oracle
DEFAULT_TARGET = PRODUCT.target          # deprecated
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
