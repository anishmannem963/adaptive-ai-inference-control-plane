# Completely free hosted demo

This path publishes the control plane without creating a Google Cloud or AWS account.

## Architecture

- Netlify serves the static dashboard.
- A free Render web service runs the FastAPI gateway from the repository Dockerfile.
- A free Render Key Value instance provides the Redis-compatible cache.
- The gateway registers deterministic mock providers only.
- GitHub Actions remains the authoritative Kubernetes, load, and fault-test environment.

The provider responses, configured prices, quality scores, and provider failures are controlled
simulations. This deployment must not be described as real multi-cloud or Bedrock inference.

## Safety defaults

The root `render.yaml` is the deployment contract. It explicitly:

- selects the `free` plan for both resources;
- keeps Ollama and AWS Bedrock disabled;
- fixes the Bedrock session budget at USD 0;
- enables only deterministic mock providers;
- permits browser requests only from the production Netlify origin;
- uses the private Render Key Value connection string;
- disables persistent Key Value storage; and
- deploys application commits only after their GitHub checks pass.

No payment credential, cloud credential, model key, or secret belongs in the repository.

## Deploy from Render

1. Create a free Render account and connect GitHub.
2. In the Render dashboard, choose **New > Blueprint**.
3. Select `anishmannem963/adaptive-ai-inference-control-plane`.
4. Use the default branch `main` and Blueprint path `render.yaml`.
5. Review the proposed resources. Both plans must display **Free**.
6. Apply the Blueprint.
7. Wait for the gateway health check to pass.
8. Copy the generated `https://...onrender.com` web-service URL.

Do not select a paid plan and do not add AWS credentials. Without a payment method, Render
suspends free services when applicable included limits are exhausted instead of charging for
supplementary usage.

## Validate the hosted gateway

Run the existing bounded validator from a local checkout:

```bash
python scripts/validate_cloud_gateway.py \
  --base-url 'https://YOUR-SERVICE.onrender.com' \
  --requests 25 \
  --output artifacts/free-render-validation.json
```

The validator confirms readiness, verifies the free simulated-provider configuration, performs
25 direct requests, and records success rate and latency percentiles. It never invokes Bedrock.

Also verify the cache connection:

```bash
curl 'https://YOUR-SERVICE.onrender.com/v1/cache/status'
```

The response should report `"backend":"redis"`. Free Key Value storage is intentionally
non-persistent; losing cached responses or idempotency records after a restart is expected and
does not affect inference availability.

## Connect Netlify

Until the generated Render hostname is known, the dashboard retains its editable **Gateway URL**
field.

1. Open <https://adaptive-ai-inference-control-plane.netlify.app/>.
2. Paste the Render web-service URL into **Gateway URL**.
3. Select **Connect**.
4. Confirm that the banner reads **Gateway connected**.
5. Submit an adaptive request and inspect its route, cache status, latency, and trace ID.

The dashboard stores the selected gateway URL in that browser. After the first hosted validation
passes, update the dashboard's default API URL to the exact Render hostname so interviewers do
not need to configure it.

## Free-tier behavior

A free Render web service spins down after an idle period. Its first request after sleeping can
take roughly one minute while the service starts. Open the dashboard shortly before an interview
and wait for **Gateway connected**.

The public deployment is a demonstration environment, not a production service. It runs one
small gateway instance, uses volatile cache storage, and is subject to provider free-tier usage
limits.

## Completion gate

The free hosted stage is complete only after:

- the Render deployment is healthy;
- `/v1/system/status` shows mock providers enabled and Bedrock disabled;
- `/v1/cache/status` reports the Redis backend;
- the 25-request hosted validation succeeds;
- the Netlify request playground completes an adaptive request; and
- no secret or paid-provider configuration is present.

Google Cloud, AWS Bedrock, and paid GPU validation remain optional later stages.
