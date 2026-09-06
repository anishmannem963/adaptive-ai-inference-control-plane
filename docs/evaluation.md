# Reproducible evaluation

Iteration 9 measures the control plane without using a paid model or cloud service. Every
report is JSON, includes its workload configuration, and separates controlled simulation from
real-provider evidence.

## Load benchmark

Start the gateway with response caching disabled so repeated work cannot improve the reported
latency:

```bash
CACHE_ENABLED=false \
PROVIDER_RATE_PER_SECOND=100000 \
PROVIDER_BURST_CAPACITY=100000 \
uvicorn control_plane.main:app --port 8080
```

In another terminal, run the complete default matrix:

```bash
python scripts/run_load_benchmark.py \
  --requests 1000 \
  --concurrency 20 \
  --repetitions 3 \
  --output artifacts/load-benchmark.json
```

This sends 12,000 HTTP requests: 1,000 requests × 3 repetitions × 4 routing profiles. The
profiles are adaptive, round robin, a fixed `mock-quality` provider, and lowest cost. Every
request has a unique prompt and request ID. Each run records:

- successful and failed requests;
- throughput and elapsed time;
- p50, p95, p99, and maximum end-to-end latency;
- estimated provider cost;
- provider selection counts; and
- fallback count.

The report also aggregates repeated runs per profile and calculates the adaptive policy's
estimated-cost reduction and mean-p95 latency change against each baseline. Negative cost
reduction means adaptive routing cost more than that baseline; no result is silently presented
as an improvement.

The high local admission settings intentionally remove the normal 100-request/second provider
guard from this gateway-overhead experiment. Rate limiting remains independently tested; the
report configuration makes this benchmark boundary explicit.

The mock providers use controlled price, latency, and quality inputs. These results compare
routing behavior and gateway overhead; they are not claims about Bedrock, vLLM, GPU, or public
internet performance.

## Provider fault matrix

```bash
python scripts/run_fault_matrix.py \
  --repetitions 10 \
  --output artifacts/fault-matrix.json
```

The default matrix runs 60 independent scenarios across six categories:

1. provider error with successful fallback;
2. provider timeout with successful fallback;
3. open-circuit isolation without a second provider invocation;
4. half-open recovery and circuit closure;
5. explicit-model failure without silent substitution; and
6. complete provider outage with an auditable HTTP 503.

The harness calls the real FastAPI application through its ASGI interface while injecting
controlled provider behavior. It does not expose a fault-control endpoint in the deployed
service.

## CI levels

Pull-request CI runs a smaller gate of 400 load requests and 12 fault scenarios. The manually
started **Evaluation evidence** workflow runs the 12,000-request and 60-scenario matrices and
retains both JSON files as a downloadable GitHub Actions artifact.

CI never enables AWS Bedrock, creates a cloud resource, or spends cloud credits.
