#!/usr/bin/env python3
"""Run the explicitly authorized minimal-paid Bedrock validation."""

from __future__ import annotations

import argparse
import asyncio
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

import httpx

from control_plane.evaluation.cloud import validate_bedrock

CONFIRMATION = "I_UNDERSTAND_THIS_MAY_INCUR_CHARGES"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--requests", type=int, default=10)
    parser.add_argument("--maximum-total-estimated-cost-usd", required=True)
    parser.add_argument("--confirm-paid-run", required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/bedrock-validation.json"),
    )
    return parser.parse_args()


def validate_guardrails(args: argparse.Namespace) -> Decimal:
    if args.confirm_paid_run != CONFIRMATION:
        raise SystemExit(f"paid validation requires --confirm-paid-run {CONFIRMATION}")
    if not 1 <= args.requests <= 100:
        raise SystemExit("requests must be between 1 and 100")
    try:
        ceiling = Decimal(args.maximum_total_estimated_cost_usd)
    except InvalidOperation as exc:
        raise SystemExit("cost ceiling must be a decimal") from exc
    if not ceiling.is_finite() or not Decimal("0") < ceiling <= Decimal("25"):
        raise SystemExit("cost ceiling must be greater than $0 and at most $25")
    return ceiling


async def run(args: argparse.Namespace, ceiling: Decimal) -> dict[str, object]:
    async with httpx.AsyncClient(
        base_url=args.base_url.rstrip("/"),
        timeout=90,
        trust_env=False,
    ) as client:
        return await validate_bedrock(
            client,
            requests=args.requests,
            maximum_total_estimated_cost_usd=ceiling,
        )


def main() -> None:
    args = parse_args()
    ceiling = validate_guardrails(args)
    report = asyncio.run(run(args, ceiling))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    summary = report["summary"]
    if summary["failed_requests"] or summary["successful_requests"] != args.requests:
        raise SystemExit("Bedrock validation did not complete every requested operation")


if __name__ == "__main__":
    main()
