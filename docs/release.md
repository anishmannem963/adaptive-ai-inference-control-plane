# Release process

Version `1.0.0` is gated by controlled cloud validation. Do not create the tag while the
changelog still marks the release as unreleased or while cloud evidence is absent.

## Release gate

- application, evaluation, infrastructure, and dashboard CI are green;
- the hosted mock evaluation summary is committed with provenance;
- free-provider Cloud Run validation is retained;
- the explicitly approved AWS Bedrock validation is retained;
- documentation distinguishes simulated estimates from real provider observations;
- `pyproject.toml` and `control_plane.__version__` both equal `1.0.0`; and
- the release commit contains no credentials, Terraform state, or unignored secret values.

Create the annotated `v1.0.0` tag from the exact reviewed commit. The tag workflow retests the
source, builds the Python wheel and source distribution, creates `SHA256SUMS`, uploads a
90-day Actions artifact, and creates or updates the GitHub Release.

The release workflow never provisions cloud infrastructure or invokes an inference provider.

