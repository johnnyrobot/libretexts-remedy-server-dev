"""Re-run engine + preflight on PDFs that failed the previous batch.

Reads _summary.json, picks every result with preflight_ok == False, runs the
engine again on the source PDF, replaces the output in the destination
directory, runs Acrobat Preflight, and emits a new summary.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

REMEDY_PDF = Path("./.venv/bin/remedy-pdf").resolve()
PREFLIGHT = Path("./tools/acrobat/acrobat_preflight.py").resolve()


@dataclass
class Result:
    name: str
    engine_ok: bool
    preflight_ok: bool
    preflight_errors: int
    preflight_rules: list[dict]
    error: str | None = None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--dest", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True, help="Existing _summary.json")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    data = json.loads(args.summary.read_text())
    failures = [r for r in data["results"] if not r["preflight_ok"]]
    print(f"Re-processing {len(failures)} failed PDF(s)")
    results: list[Result] = []
    for idx, r in enumerate(failures, 1):
        name = r["name"]
        src = args.source / name
        out = args.dest / name
        print(f"[{idx}/{len(failures)}] {name}")
        if not src.is_file():
            print("  source missing"); continue
        engine = subprocess.run(
            [str(REMEDY_PDF), "fix", str(src), "-o", str(out), "--no-vision"],
            capture_output=True, text=True, timeout=1800,
        )
        if engine.returncode != 0 or not out.exists():
            results.append(Result(name, False, False, -1, [], engine.stderr[-500:]))
            print(f"  ENGINE FAIL")
            continue
        pre = subprocess.run(
            ["./.venv/bin/python", str(PREFLIGHT), str(out), "--json"],
            capture_output=True, text=True, timeout=600,
        )
        try:
            payload = json.loads(pre.stdout)
        except json.JSONDecodeError:
            results.append(Result(name, True, False, -1, [], f"json decode: {pre.stderr[-200:]}"))
            print("  preflight no JSON"); continue
        ok = bool(payload.get("passes"))
        errs = int(payload.get("totals", {}).get("errors", -1))
        rules = payload.get("rules", [])
        results.append(Result(name, True, ok, errs, rules, payload.get("exception")))
        print(f"  preflight: {'PASS' if ok else f'FAIL ({errs} errs)'}")

    summary = {
        "total": len(results),
        "preflight_pass": sum(1 for r in results if r.preflight_ok),
        "results": [asdict(r) for r in results],
    }
    args.report.write_text(json.dumps(summary, indent=2))
    print(f"\n== {summary['preflight_pass']}/{summary['total']} now pass ==")
    print(f"Report: {args.report}")
    return 0 if summary["preflight_pass"] == summary["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
