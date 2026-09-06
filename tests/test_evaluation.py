import asyncio

from control_plane.evaluation.faults import SCENARIOS, run_fault_matrix
from control_plane.evaluation.load import (
    LoadProfile,
    RequestSample,
    aggregate_runs,
    compare_adaptive,
    percentile,
    summarize_samples,
)


def test_percentile_uses_nearest_rank() -> None:
    values = [1.0, 2.0, 3.0, 4.0, 100.0]

    assert percentile(values, 0.50) == 3.0
    assert percentile(values, 0.95) == 100.0
    assert percentile([], 0.99) == 0.0


def test_load_summary_counts_failures_cost_and_routes() -> None:
    run = summarize_samples(
        profile=LoadProfile("adaptive", "adaptive"),
        repetition=1,
        concurrency=2,
        duration_seconds=0.5,
        samples=[
            RequestSample(200, 10, "mock-fast", "0.001", 0),
            RequestSample(200, 20, "mock-fast", "0.002", 1),
            RequestSample(503, 30, None, "0", 0),
        ],
    )

    assert run.successful_requests == 2
    assert run.failed_requests == 1
    assert run.success_rate == 0.666667
    assert run.throughput_rps == 6
    assert run.latency_ms == {"p50": 10, "p95": 20, "p99": 20, "max": 20}
    assert run.estimated_cost_usd == "0.003"
    assert run.provider_distribution == {"mock-fast": 2}
    assert run.fallback_count == 1


def test_load_aggregates_generate_baseline_comparisons() -> None:
    adaptive = summarize_samples(
        profile=LoadProfile("adaptive", "adaptive"),
        repetition=1,
        concurrency=1,
        duration_seconds=1,
        samples=[RequestSample(200, 10, "fast", "0.001", 0)],
    )
    baseline = summarize_samples(
        profile=LoadProfile("round_robin", "round_robin"),
        repetition=1,
        concurrency=1,
        duration_seconds=1,
        samples=[RequestSample(200, 20, "quality", "0.002", 0)],
    )

    aggregates = aggregate_runs([adaptive, baseline])
    comparisons = compare_adaptive(aggregates)

    assert aggregates["adaptive"]["success_rate"] == 1
    assert aggregates["round_robin"]["provider_distribution"] == {"quality": 1}
    assert comparisons["round_robin"] == {
        "estimated_cost_reduction_percent": 50,
        "mean_p95_latency_change_percent": -50,
    }


def test_fault_matrix_exercises_every_category() -> None:
    report = asyncio.run(run_fault_matrix(repetitions=1))

    assert report["summary"]["scenarios"] == len(SCENARIOS)
    assert report["summary"]["passed"] == len(SCENARIOS)
    assert report["summary"]["failed"] == 0
    assert report["summary"]["pass_rate"] == 1
    assert {result["scenario"] for result in report["results"]} == {
        scenario.__name__ for scenario in SCENARIOS
    }
