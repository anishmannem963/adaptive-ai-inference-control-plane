# Controlled cloud validation

Cloud validation is split into a free-provider deployment check and a separately authorized
minimal-paid Bedrock experiment. Neither command provisions infrastructure.

## 1. Cloud Run gateway check

After reviewing and explicitly applying the Terraform plan, validate the Cloud Run URL with
mock providers only:

```bash
python scripts/validate_cloud_gateway.py \
  --base-url 'https://YOUR-SERVICE.run.app' \
  --requests 25 \
  --output artifacts/free-cloud-validation.json
```

This checks readiness, confirms mock providers are enabled, sends 25 direct `mock-fast`
requests, and records success rate plus p50/p95/p99 latency. It does not invoke Bedrock.

Cloud Run requires a billing-enabled Google Cloud project. Scale-to-zero and free-tier-eligible
usage reduce expected cost but do not guarantee a zero bill. The Terraform budget is an alert,
not a hard cap. Inspect the plan, use a dedicated project, and destroy the resources after the
experiment.

## 2. Minimal-paid Bedrock check

Before enabling Bedrock:

1. Verify the current price for the exact model and AWS region.
2. Restrict the AWS identity to the required Bedrock inference actions and model resource.
3. Set `AWS_SESSION_BUDGET_USD=5` on a single gateway instance.
4. Set explicit input and output token prices.
5. Keep mock providers enabled for comparison, but call `bedrock-primary` directly so failure
   cannot silently substitute a mock.

The paid command requires an unmistakable confirmation phrase and enforces at most 100
sequential requests and a client ceiling no larger than $25:

```bash
python scripts/validate_bedrock.py \
  --base-url 'https://YOUR-SERVICE.run.app' \
  --requests 10 \
  --maximum-total-estimated-cost-usd 5 \
  --confirm-paid-run I_UNDERSTAND_THIS_MAY_INCUR_CHARGES \
  --output artifacts/bedrock-validation.json
```

The gateway's pre-inference session reservation is the authoritative spending guard. The client
ceiling stops subsequent requests based on returned usage and cannot prevent the final request
from crossing its own estimate. AWS billing data remains authoritative.

## Evidence and stop conditions

Retain the Cloud Run revision, image digest, region, configured model ID, current price source,
workflow or terminal timestamp, and both JSON reports. Stop immediately if:

- the configured model or region differs from the reviewed plan;
- AWS prices cannot be verified;
- the gateway session budget is absent or above the approved amount;
- the Cloud Run revision has more than one instance during the paid experiment;
- any credential appears in logs, artifacts, or source control; or
- the project-level billing alert is unavailable.

Do not publish a cost-saving or cloud-failover claim until this evidence is complete.

