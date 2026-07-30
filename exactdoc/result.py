"""What a conversion actually did, as opposed to what was asked of it.

`convert()` returned the output path. That is enough to find the file and not
enough to trust it, because the most important thing a caller can learn is
whether the conversion it *got* is the conversion it *requested*:

    requested   backend=pdfium  oracle=libreoffice  refine_rounds=3
    resolved    backend=pdfium  oracle=none         refine_rounds=0

Both produce a DOCX. Only one of them ran the feedback loop. Under the old
contract those two runs were indistinguishable to a caller and to a log, and
LibreOffice being absent turned a refined conversion into an open-loop one with
no signal anywhere -- which is how a published fidelity number came to describe
a profile no surface actually ran.

So the result carries **requested and resolved side by side, always**, and a
caller comparing them is doing the check that used to be impossible. `warnings`
carries the same information in a form a human reads.

Everything here is content-safe: hashes, counts, durations, option names. No
source text, no credentials, no remote document identifiers, and no absolute
paths beyond the output the caller already named.
"""
import dataclasses
import hashlib
import os
from typing import Any, Dict, Optional, Tuple


def sha256_file(path, _chunk=1 << 16):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(_chunk), b""):
            h.update(block)
    return h.hexdigest()


@dataclasses.dataclass(frozen=True)
class ConversionWarning:
    """Something the caller should know that did not stop the conversion.

    A warning is not a shrug. Each one names the stage it came from so that
    "the figure on page 3 was rasterised" and "your renderer was missing" cannot
    be read as the same class of event.
    """

    code: str
    message: str
    stage: str = "convert"
    detail: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        d = {"code": self.code, "stage": self.stage, "message": self.message}
        if self.detail:
            d["detail"] = self.detail
        return d


@dataclasses.dataclass(frozen=True)
class OracleRun:
    """One pass through a render oracle.

    `cleanup_ok` is not decoration. For a cloud oracle it answers "is the
    caller's document still sitting in somebody else's storage?", and a run that
    rendered perfectly and failed to delete is a privacy failure, not a success
    with a footnote.
    """

    oracle: str
    ok: bool
    round_index: int = 0
    rendered_sha256: Optional[str] = None
    duration_ms: int = 0
    attempts: int = 1
    cleanup_ok: bool = True
    stage_failed: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class ConversionResult:
    """The stable return value of `convert()`."""

    output_path: str
    output_sha256: str
    requested_options: Any
    resolved_options: Any
    refine_rounds_completed: int = 0
    oracle_runs: Tuple[OracleRun, ...] = ()
    warnings: Tuple[ConversionWarning, ...] = ()
    timings_ms: Dict[str, int] = dataclasses.field(default_factory=dict)

    @property
    def degraded(self) -> bool:
        """True when what ran is not what was asked for.

        The single question the old contract could not answer. A caller that
        checks nothing else should check this.
        """
        req, res = self.requested_options, self.resolved_options
        for field in ("backend", "output_profile", "oracle", "refine_rounds"):
            if getattr(req, field, None) != getattr(res, field, None):
                return True
        return False

    @property
    def cleanup_ok(self) -> bool:
        """False if any oracle left remote state behind."""
        return all(r.cleanup_ok for r in self.oracle_runs)

    def as_dict(self) -> Dict[str, Any]:
        def opts(o):
            return o.as_dict() if hasattr(o, "as_dict") else o

        return {
            "output_path": self.output_path,
            "output_name": os.path.basename(self.output_path),
            "output_sha256": self.output_sha256,
            "requested_options": opts(self.requested_options),
            "resolved_options": opts(self.resolved_options),
            "degraded": self.degraded,
            "refine_rounds_completed": self.refine_rounds_completed,
            "oracle_runs": [r.as_dict() for r in self.oracle_runs],
            "cleanup_ok": self.cleanup_ok,
            "warnings": [w.as_dict() for w in self.warnings],
            "timings_ms": dict(self.timings_ms),
        }
