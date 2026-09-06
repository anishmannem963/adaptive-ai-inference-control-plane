#!/usr/bin/env python3
"""Run the repeatable zero-cost HTTP benchmark matrix."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from control_plane.evaluation.load import run_matrix


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--requests", type=int, default=1000)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--output", type=Path, default=Path("artifacts/load-benchmark.json"))
    parser.add_argument("--minimum-success-rate", type=float, default=1.0)
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if args.requests <= 0 or args.concurrency <= 0 or args.repetitions <= 0:
        raise SystemExit("requests, concurrency, and repetitions must be positive")
    if not 0 <= args.minimum_success_rate <= 1:
        raise SystemExit("minimum success rate must be between 0 and 1")


def main() -> None:
    args = parse_args()
    validate_args(args)
    report = asyncio.run(
        run_matrix(
            base_url=args.base_url,
            requests=args.requests,
            concurrency=args.concurrency,
            repetitions=args.repetitions,
        )
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    summary = report["summary"]
    print(json.dumps(summary, indent=2))
    if summary["success_rate"] < args.minimum_success_rate:
        raise SystemExit("benchmark success rate is below the required threshold")


if __name__ == "__main__":
    main()
