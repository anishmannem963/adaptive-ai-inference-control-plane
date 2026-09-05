import asyncio
from decimal import Decimal

import pytest

from control_plane.contracts import ChatCompletionRequest, ChatMessage, RoutingOptions
from control_plane.providers.deterministic import default_providers
from control_plane.providers.registry import ProviderRegistry
from control_plane.routing import NoEligibleProviderError, RoutingEngine


def request(
    *,
    policy: str = "adaptive",
    max_latency_ms: int | None = None,
    max_cost: Decimal | None = None,
    min_quality: float | None = None,
    preferred_provider: str | None = None,
) -> ChatCompletionRequest:
    return ChatCompletionRequest(
        model="auto",
        messages=[ChatMessage(role="user", content="route this request")],
        max_tokens=100,
        routing=RoutingOptions(
            policy=policy,  # type: ignore[arg-type]
            max_latency_ms=max_latency_ms,
            max_estimated_cost_usd=max_cost,
            min_quality=min_quality,
            preferred_provider=preferred_provider,
        ),
    )


def engine() -> RoutingEngine:
    return RoutingEngine(ProviderRegistry(default_providers()))


@pytest.mark.parametrize(
    ("policy", "expected"),
    [
        ("lowest_cost", "mock-economy"),
        ("lowest_latency", "mock-fast"),
        ("highest_quality", "mock-quality"),
    ],
)
def test_baseline_policies_are_deterministic(policy: str, expected: str) -> None:
    decision = asyncio.run(engine().select(request(policy=policy)))

    assert decision.provider.descriptor.name == expected
    assert decision.policy == policy
    assert decision.reason


def test_round_robin_rotates_over_eligible_providers() -> None:
    router = engine()

    decisions = [asyncio.run(router.select(request(policy="round_robin"))) for _ in range(4)]

    assert [decision.provider.descriptor.name for decision in decisions] == [
        "mock-economy",
        "mock-fast",
        "mock-quality",
        "mock-economy",
    ]


def test_latency_constraint_filters_slow_providers() -> None:
    decision = asyncio.run(engine().select(request(policy="highest_quality", max_latency_ms=100)))

    assert decision.provider.descriptor.name == "mock-fast"
    assert decision.eligible_providers == ("mock-fast",)


def test_quality_constraint_filters_lower_quality_providers() -> None:
    decision = asyncio.run(engine().select(request(policy="lowest_cost", min_quality=0.90)))

    assert decision.provider.descriptor.name == "mock-quality"


def test_impossible_constraints_fail_instead_of_being_relaxed() -> None:
    with pytest.raises(NoEligibleProviderError, match="no provider"):
        asyncio.run(
            engine().select(
                request(
                    max_latency_ms=40,
                    max_cost=Decimal("0.000001"),
                    min_quality=0.99,
                )
            )
        )


def test_single_provider_must_be_eligible() -> None:
    with pytest.raises(NoEligibleProviderError, match="preferred"):
        asyncio.run(
            engine().select(
                request(
                    policy="single_provider",
                    preferred_provider="mock-quality",
                    max_latency_ms=100,
                )
            )
        )


def test_direct_model_still_honors_constraints() -> None:
    direct = ChatCompletionRequest(
        model="mock-quality",
        messages=[ChatMessage(role="user", content="hello")],
        routing=RoutingOptions(max_latency_ms=100),
    )

    with pytest.raises(NoEligibleProviderError, match="explicit"):
        asyncio.run(engine().select(direct))
