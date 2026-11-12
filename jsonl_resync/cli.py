"""CLI: report corrupt lines in a JSONL file, optionally emitting a report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .core import scan, resync


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="jsonl-resync", description=__doc__)
    ap.add_argument("path", type=Path)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--max-bad", type=int, default=20)
    ap.add_argument("--salvage", action="store_true", help="print recovered records as JSONL")
    args = ap.parse_args(argv)
    try:
        data = args.path.read_bytes()
    except OSError as exc:
        sys.stderr.write(f"jsonl-resync: {exc}\n")
        return 2
    report = scan(data, keep_records=args.salvage)
    if args.salvage:
        for _line_no, rec in resync(data):
            print(json.dumps(rec, ensure_ascii=False))
    if args.json:
        print(json.dumps(report.to_dict(args.max_bad), indent=2))
    elif not args.salvage:
        fb = report.first_bad
        print(f"{args.path}: {report.valid_lines}/{report.total_lines} lines valid, "
              f"{len(report.bad)} bad, valid prefix {report.valid_prefix_bytes} bytes")
        if fb:
            print(f"  first bad line {fb.line_no} at byte {fb.byte_offset}: {fb.error}")
    return 0 if report.ok else 5


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
