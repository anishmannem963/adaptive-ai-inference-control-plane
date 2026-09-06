# Contributing

## Development checks

Use Python 3.12 and install the development dependencies:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
ruff check .
ruff format --check .
mypy
pytest
python scripts/validate_dashboard.py
```

Changes to deployment files must also pass Helm linting, Terraform validation, and the live
`kind` smoke test in CI.

## Evidence rules

- Do not convert mock prices, latency, quality, or failures into real-cloud claims.
- Include raw machine-readable output, configuration, commit SHA, and execution provenance for
  benchmark claims.
- Use unique prompts or disable caching when measuring uncached inference.
- Never commit credentials, API keys, Terraform state, `.tfvars`, or Redis connection secrets.
- Bedrock tests must remain opt-in, sequential, explicitly budgeted, and directly addressed to
  the real model alias.

Open a focused pull request and explain the behavior, safety boundary, tests, and expected cost
impact.

