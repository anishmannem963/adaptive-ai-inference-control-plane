"""Constraint-aware provider selection and explainable baseline policies."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal

from control_plane.contracts import ChatCompletionRequest
from control_plane.providers.base import InferenceProvider
from control_plane.providers.registry import ProviderRegistry, UnknownModelError


class NoEligibleProviderError(LookupError):
    """No provider satisfies all hard request constraints."""


@dataclass(frozen=True, slots=True)
class Candidate:
    provider: InferenceProvider
    estimated_cost_usd: Decimal


@dataclass(frozen=True, slots=True)
class RouteDecision:
    provider: InferenceProvider
    policy: str
    reason: str
    eligible_providers: tuple[str, ...]
    estimated_cost_usd: Decimal


class RoutingEngine:
    def __init__(self, registry: ProviderRegistry) -> None:
        self._registry = registry
        self._round_robin_index = 0
        self._round_robin_lock = asyncio.Lock()

    async def select(self, request: ChatCompletionRequest) -> RouteDecision:
        if request.model != "auto":
            try:
                provider = self._registry.resolve(request.model)
            except UnknownModelError:
                raise
            candidate = Candidate(provider, self._estimate_cost(provider, request))
            self._enforce_constraints(candidate, request)
            return RouteDecision(
                provider=provider,
                policy="direct",
                reason=f"explicit model {request.model} mapped to {provider.descriptor.name}",
                eligible_providers=(provider.descriptor.name,),
                estimated_cost_usd=candidate.estimated_cost_usd,
            )

        candidates = [
            Candidate(provider, self._estimate_cost(provider, request))
            for provider in self._registry.list()
        ]
        eligible = [
            candidate
            for candidate in candidates
            if self._satisfies_constraints(candidate, request)
        ]
        if not eligible:
            raise NoEligibleProviderError("no provider satisfies all routing constraints")

        policy = request.routing.policy
        if policy == "single_provider":
            selected = next(
                (
                    candidate
                    for candidate in eligible
                    if candidate.provider.descriptor.name
                    == request.routing.preferred_provider
                ),
                None,
            )
            if selected is None:
                raise NoEligibleProviderError("preferred provider is missing or ineligible")
            reason = f"selected required provider {request.routing.preferred_provider}"
        elif policy == "round_robin":
            async with self._round_robin_lock:
                selected = eligible[self._round_robin_index % len(eligible)]
                self._round_robin_index += 1
            reason = "selected next eligible provider in round-robin order"
        elif policy == "lowest_cost":
            selected = min(eligible, key=lambda item: item.estimated_cost_usd)
            reason = "selected minimum estimated request cost"
        elif policy == "lowest_latency":
            selected = min(
                eligible,
                key=lambda item: item.provider.descriptor.nominal_latency_ms,
            )
            reason = "selected minimum nominal latency"
        elif policy == "highest_quality":
            selected = max(
                eligible,
                key=lambda item: item.provider.descriptor.quality_score,
            )
            reason = "selected maximum measured quality score"
        else:
            selected = min(eligible, key=lambda item: self._adaptive_score(item, eligible, request))
            reason = "selected minimum normalized weighted cost-latency-quality score"

        return RouteDecision(
            provider=selected.provider,
            policy=policy,
            reason=reason,
            eligible_providers=tuple(
                candidate.provider.descriptor.name for candidate in eligible
            ),
            estimated_cost_usd=selected.estimated_cost_usd,
        )

    def _estimate_cost(
        self,
        provider: InferenceProvider,
        request: ChatCompletionRequest,
    ) -> Decimal:
        prompt_tokens = max(
            1,
            len(" ".join(message.content for message in request.messages)) // 4,
        )
        descriptor = provider.descriptor
        return (
            Decimal(prompt_tokens)
            * Decimal(descriptor.input_cost_per_million_tokens_usd)
            + Decimal(request.max_tokens)
            * Decimal(descriptor.output_cost_per_million_tokens_usd)
        ) / Decimal(1_000_000)

    def _satisfies_constraints(
        self,
        candidate: Candidate,
        request: ChatCompletionRequest,
    ) -> bool:
        options = request.routing
        descriptor = candidate.provider.descriptor
        return not (
            options.max_latency_ms is not None
            and descriptor.nominal_latency_ms > options.max_latency_ms
            or options.max_estimated_cost_usd is not None
            and candidate.estimated_cost_usd > options.max_estimated_cost_usd
            or options.min_quality is not None
            and descriptor.quality_score < options.min_quality
        )

    def _enforce_constraints(
        self,
        candidate: Candidate,
        request: ChatCompletionRequest,
    ) -> None:
        if not self._satisfies_constraints(candidate, request):
            raise NoEligibleProviderError("explicit model violates routing constraints")

    def _adaptive_score(
        self,
        candidate: Candidate,
        eligible: list[Candidate],
        request: ChatCompletionRequest,
    ) -> float:
        max_cost = max(item.estimated_cost_usd for item in eligible) or Decimal(1)
        max_latency = max(
            item.provider.descriptor.nominal_latency_ms for item in eligible
        ) or 1
        weights = request.routing.weights
        return (
            weights.cost * float(candidate.estimated_cost_usd / max_cost)
            + weights.latency
            * candidate.provider.descriptor.nominal_latency_ms
            / max_latency
            + weights.quality * (1 - candidate.provider.descriptor.quality_score)
        )
