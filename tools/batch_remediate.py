"""Batch-remediate every PDF in a source directory and run Acrobat Preflight
against each output to gate on Adobe-equivalent PDF/UA-1 compliance.

Usage::

    PDF_DISABLE_VISIBLE_TEXT_SCAFFOLD=1 \
        ./.venv/bin/python tools/batch_remediate.py \
            --source <input-pdf-dir> \
            --dest   <output-pdf-dir> \
            --report <output-pdf-dir>/_summary.json
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path


REMEDY_PDF = Path("./.venv/bin/remedy-pdf").resolve()
PREFLIGHT = Path("./tools/acrobat/acrobat_preflight.py").resolve()


@dataclass
class PdfRunResult:
    name: str
    size_bytes: int
    engine_ok: bool
    engine_elapsed_s: float
    engine_stderr_tail: str
    preflight_ok: bool
    preflight_errors: int
    preflight_unique_rules: int
    preflight_rules: list[dict]
    error: str | None = None


def _run_engine(input_pdf: Path, output_pdf: Path) -> tuple[bool, float, str]:
    start = time.perf_counter()
    proc = subprocess.run(
        [str(REMEDY_PDF), "fix", str(input_pdf), "-o", str(output_pdf), "--no-vision"],
        capture_output=True,
        text=True,
        timeout=1800,
    )
    elapsed = time.perf_counter() - start
    return proc.returncode == 0, elapsed, (proc.stderr or proc.stdout)[-2000:]


def _run_preflight(pdf_path: Path) -> tuple[bool, int, int, list[dict], str | None]:
    proc = subprocess.run(
        ["./.venv/bin/python", str(PREFLIGHT), str(pdf_path), "--json"],
        capture_output=True,
        text=True,
        timeout=900,
    )
    if proc.stdout.strip():
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            return False, -1, 0, [], f"json decode failed: {exc}"
        return (
            bool(payload.get("passes")),
            int(payload.get("totals", {}).get("errors", -1)),
            int(payload.get("unique_rules", 0)),
            payload.get("rules", []),
            payload.get("exception"),
        )
    return False, -1, 0, [], f"preflight produced no JSON: {(proc.stderr or '')[-500:]}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--dest", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=None, help="Stop after N PDFs (smoke run).")
    args = parser.parse_args()

    args.dest.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(args.source.glob("*.pdf"))
    if args.limit is not None:
        pdfs = pdfs[: args.limit]

    print(f"Found {len(pdfs)} PDF(s) in {args.source}")

    results: list[PdfRunResult] = []
    for idx, pdf in enumerate(pdfs, start=1):
        size = pdf.stat().st_size
        target = args.dest / pdf.name
        print(f"[{idx}/{len(pdfs)}] {pdf.name} ({size/1024:.0f} KB)")
        try:
            engine_ok, engine_elapsed, engine_tail = _run_engine(pdf, target)
            if not engine_ok or not target.exists():
                results.append(
                    PdfRunResult(
                        name=pdf.name,
                        size_bytes=size,
                        engine_ok=False,
                        engine_elapsed_s=engine_elapsed,
                        engine_stderr_tail=engine_tail,
                        preflight_ok=False,
                        preflight_errors=-1,
                        preflight_unique_rules=0,
                        preflight_rules=[],
                        error="engine failed or no output",
                    )
                )
                print(f"  engine FAIL: {engine_tail[-200:]!r}")
                continue
            preflight_ok, perr, urules, prules, pexc = _run_preflight(target)
            results.append(
                PdfRunResult(
                    name=pdf.name,
                    size_bytes=size,
                    engine_ok=True,
                    engine_elapsed_s=engine_elapsed,
                    engine_stderr_tail="",
                    preflight_ok=preflight_ok,
                    preflight_errors=perr,
                    preflight_unique_rules=urules,
                    preflight_rules=prules,
                    error=pexc,
                )
            )
            verdict = "PASS" if preflight_ok else f"FAIL ({perr} errs / {urules} rules)"
            print(f"  engine {engine_elapsed:5.1f}s -> preflight {verdict}")
        except subprocess.TimeoutExpired:
            results.append(
                PdfRunResult(
                    name=pdf.name,
                    size_bytes=size,
                    engine_ok=False,
                    engine_elapsed_s=-1,
                    engine_stderr_tail="",
                    preflight_ok=False,
                    preflight_errors=-1,
                    preflight_unique_rules=0,
                    preflight_rules=[],
                    error="timeout",
                )
            )
            print("  TIMEOUT")
        except Exception as exc:
            results.append(
                PdfRunResult(
                    name=pdf.name,
                    size_bytes=size,
                    engine_ok=False,
                    engine_elapsed_s=-1,
                    engine_stderr_tail="",
                    preflight_ok=False,
                    preflight_errors=-1,
                    preflight_unique_rules=0,
                    preflight_rules=[],
                    error=f"exception: {exc!r}",
                )
            )
            print(f"  EXC {exc!r}")

    args.report.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "source": str(args.source),
        "dest": str(args.dest),
        "total": len(results),
        "engine_ok": sum(1 for r in results if r.engine_ok),
        "preflight_pass": sum(1 for r in results if r.preflight_ok),
        "results": [asdict(r) for r in results],
    }
    args.report.write_text(json.dumps(summary, indent=2))
    print()
    print(f"== {summary['preflight_pass']}/{summary['total']} pass Acrobat Preflight ==")
    print(f"Summary report: {args.report}")
    return 0 if summary["preflight_pass"] == summary["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
