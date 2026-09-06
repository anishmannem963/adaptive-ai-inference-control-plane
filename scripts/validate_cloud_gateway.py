#!/usr/bin/env python3
"""Validate a deployed gateway without invoking a paid provider."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import httpx

from control_plane.evaluation.cloud import validate_free_gateway


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--requests", type=int, default=25)
    parser.add_argument("--expected-cache-backend")
    parser.add_argument("--allowed-origin")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/free-cloud-validation.json"),
    )
    return parser.parse_args()


async def run(args: argparse.Namespace) -> dict[str, object]:
    async with httpx.AsyncClient(
        base_url=args.base_url.rstrip("/"),
        timeout=120,
        trust_env=False,
    ) as client:
        return await validate_free_gateway(
            client,
            args.requests,
            expected_cache_backend=args.expected_cache_backend,
            allowed_origin=args.allowed_origin,
        )


def main() -> None:
    args = parse_args()
    if not 1 <= args.requests <= 1000:
        raise SystemExit("requests must be between 1 and 1000")
    report = asyncio.run(run(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    if report["summary"]["failed_requests"]:
        raise SystemExit("free cloud validation failed")


if __name__ == "__main__":
    main()
