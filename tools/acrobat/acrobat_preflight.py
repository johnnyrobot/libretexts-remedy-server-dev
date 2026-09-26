"""Run Acrobat Pro's Preflight PDF/UA-1 verification on a PDF.

Drives Adobe Acrobat Pro DC via AppleScript + injected Acrobat JavaScript.
The injected JS finds the "Verify compliance with PDF/UA-1" Preflight
profile, runs it on the active document, parses the XML report, and stashes
a JSON summary in the PDF's `subject` metadata field. We then read that
field back to surface a structured failure list to Python callers.

This is NOT identical to Adobe Acrobat's GUI "Accessibility Full Check" --
the GUI check has no scripted API. Preflight PDF/UA-1 covers the ISO
14289-1 machine-checkable rules, which heavily overlap with Adobe's Full
Check (~75-85% of the 32 rules).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF

_HERE = Path(__file__).resolve().parent
_APPLESCRIPT = _HERE / "run_preflight.applescript"
_JS = _HERE / "preflight.js"
_OUT_PDF = Path("/tmp/acrobat_preflight_out.pdf")


@dataclass
class RuleFailure:
    rule: str
    severity: str
    hits: int


@dataclass
class PreflightSummary:
    profile: str
    total_errors: int
    total_warnings: int
    total_infos: int
    unique_rules: int
    rules: list[RuleFailure] = field(default_factory=list)
    exception: str | None = None

    @property
    def passes(self) -> bool:
        return self.exception is None and self.total_errors == 0

    def as_dict(self) -> dict:
        return {
            "profile": self.profile,
            "totals": {
                "errors": self.total_errors,
                "warnings": self.total_warnings,
                "infos": self.total_infos,
            },
            "unique_rules": self.unique_rules,
            "passes": self.passes,
            "rules": [
                {"rule": r.rule, "severity": r.severity, "hits": r.hits}
                for r in sorted(self.rules, key=lambda x: (-x.hits, x.rule))
            ],
            "exception": self.exception,
        }


def run_preflight(pdf_path: Path) -> PreflightSummary:
    if not pdf_path.is_file():
        raise FileNotFoundError(pdf_path)

    # Copy to a stable path so Acrobat won't get confused by spaces / unicode
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        tmp_path.write_bytes(pdf_path.read_bytes())
        if _OUT_PDF.exists():
            _OUT_PDF.unlink()
        js_code = _JS.read_text()
        proc = subprocess.run(
            [
                "osascript",
                str(_APPLESCRIPT),
                str(tmp_path),
                js_code,
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if proc.returncode != 0 or "ERR" in proc.stdout:
            raise RuntimeError(
                f"AppleScript failed (code={proc.returncode}): "
                f"stdout={proc.stdout.strip()!r} stderr={proc.stderr.strip()!r}"
            )
        if not _OUT_PDF.is_file():
            raise RuntimeError("Acrobat did not produce /tmp/acrobat_preflight_out.pdf")
        with fitz.open(str(_OUT_PDF)) as doc:
            subject = (doc.metadata or {}).get("subject") or ""
        if not subject:
            raise RuntimeError("Acrobat returned empty `subject` metadata")
        payload = json.loads(subject)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass

    if "exception" in payload and "totals" not in payload:
        return PreflightSummary(
            profile=payload.get("profile", "?"),
            total_errors=-1,
            total_warnings=-1,
            total_infos=-1,
            unique_rules=0,
            exception=payload.get("exception"),
        )

    rules = [
        RuleFailure(rule=name, severity=info["sev"], hits=info["hits"])
        for name, info in (payload.get("rules") or {}).items()
    ]
    totals = payload.get("totals") or {}
    return PreflightSummary(
        profile=payload.get("profile", "?"),
        total_errors=int(totals.get("errors") or 0),
        total_warnings=int(totals.get("warnings") or 0),
        total_infos=int(totals.get("infos") or 0),
        unique_rules=int(payload.get("uniqueRules") or len(rules)),
        rules=rules,
        exception=payload.get("exception"),
    )


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pdf", type=Path, help="PDF to check")
    parser.add_argument("--json", action="store_true", help="Emit JSON to stdout")
    args = parser.parse_args(argv)

    summary = run_preflight(args.pdf)
    if args.json:
        print(json.dumps(summary.as_dict(), indent=2))
    else:
        print(f"Profile: {summary.profile}")
        print(f"Errors: {summary.total_errors}  Warnings: {summary.total_warnings}  Unique rules: {summary.unique_rules}")
        if summary.exception:
            print(f"Exception: {summary.exception}")
        if summary.rules:
            print("\nTop failing rules:")
            for rf in sorted(summary.rules, key=lambda x: -x.hits)[:30]:
                print(f"  [{rf.severity:>5}] {rf.hits:>6}  {rf.rule}")
        print(f"\nPASS: {summary.passes}")
    return 0 if summary.passes else 1


if __name__ == "__main__":
    sys.exit(_main())
