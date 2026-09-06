#!/usr/bin/env python3
"""Run the controlled provider fault matrix and retain JSON evidence."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from control_plane.evaluation.faults import run_fault_matrix


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetitions", type=int, default=10)
    parser.add_argument("--output", type=Path, default=Path("artifacts/fault-matrix.json"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.repetitions <= 0:
        raise SystemExit("repetitions must be positive")
    report = asyncio.run(run_fault_matrix(args.repetitions))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    summary = report["summary"]
    print(json.dumps(summary, indent=2))
    if summary["failed"]:
        raise SystemExit("one or more fault scenarios failed")


if __name__ == "__main__":
    main()
