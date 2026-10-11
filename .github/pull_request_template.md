<!--
Thank you for contributing. CONTRIBUTING.md explains each item below.
Never attach a confidential or personal PDF, DOCX or screenshot: a pull
request is public, for ever.
-->

## What changes

<!-- One or two sentences: what a user sees differently. -->

## The mechanism

<!--
What the PDF does, and what the converter did wrong, in terms that apply to
any document ("a right-aligned tab stop on the baseline of left text is read
as a second column"), not to one file. Link the issue if there is one.
Documentation-only: write "n/a".
-->

## The fixture

<!--
The test that generates the smallest PDF showing the mechanism (reportlab, at
test time), and its control: the similar page whose output must not change.
-->

## Quality check

<!--
bash scripts/dev/quality_check.sh --corpus both
Paste report.json below (or at least its "verdict", "gate" and "lanes").
Documentation-only: write "n/a".
-->

Verdict: <!-- LIFTS / NEUTRAL / REGRESSES / UNMEASURED -->

<details><summary>report.json</summary>

```json

```

</details>

## Checklist

- [ ] One focused change: one mechanism, its fixture, its test.
- [ ] The mechanism is named above, and the change helps more than the document it was found in.
- [ ] A synthetic fixture and a control are in `tests/`; no PDF bytes are committed.
- [ ] No document-specific constants (thresholds tuned to one file, special cases keyed on a name, producer or page count).
- [ ] `python -m unittest discover -s tests` passes, and the five script suites where they apply.
- [ ] The quality check says LIFTS or NEUTRAL, and the gated 16 pass in both lanes.
- [ ] No change to the measurement: baseline, canonical environment, corpus or manifests, thresholds, harness reading, waivers (or it is explained above and left for the maintainer).
- [ ] The Google Docs profile (`--output-profile gdocs`) is unchanged, or the change is described for the maintainer's live check.
- [ ] No new runtime dependency (or it was agreed in an issue and `docs/license-audit.md` is updated).
- [ ] CHANGELOG.md has an entry under **Unreleased**.
- [ ] Nothing private or copyrighted is added: no personal PDFs, credentials or generated output.
- [ ] I agree that this contribution is licensed under Apache-2.0 (inbound = outbound).
