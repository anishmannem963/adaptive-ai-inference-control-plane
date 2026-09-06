from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]


def load_yaml(path: str) -> dict[str, object]:
    content = yaml.safe_load((ROOT / path).read_text())
    assert isinstance(content, dict)
    return content


def test_kubernetes_base_is_complete_and_free_by_default() -> None:
    kustomization = load_yaml("deploy/kubernetes/base/kustomization.yaml")
    assert kustomization["resources"] == [
        "namespace.yaml",
        "service-account.yaml",
        "config-map.yaml",
        "deployment.yaml",
        "service.yaml",
    ]

    config = load_yaml("deploy/kubernetes/base/config-map.yaml")["data"]
    assert isinstance(config, dict)
    assert config["AWS_BEDROCK_ENABLED"] == "false"
    assert config["AWS_SESSION_BUDGET_USD"] == "0"
    assert config["CORS_ALLOWED_ORIGINS"] == (
        "https://adaptive-ai-inference-control-plane.netlify.app"
    )

    deployment = load_yaml("deploy/kubernetes/base/deployment.yaml")
    spec = deployment["spec"]
    assert isinstance(spec, dict)
    template = spec["template"]
    assert isinstance(template, dict)
    pod_spec = template["spec"]
    assert isinstance(pod_spec, dict)
    containers = pod_spec["containers"]
    assert isinstance(containers, list)
    gateway = containers[0]
    assert gateway["imagePullPolicy"] == "Never"
    assert gateway["securityContext"]["readOnlyRootFilesystem"] is True
    assert pod_spec["securityContext"]["runAsUser"] == 10001
    assert gateway["readinessProbe"]["httpGet"]["path"] == "/health/ready"

    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "--uid 10001" in dockerfile
    assert "--gid 10001" in dockerfile


def test_helm_values_do_not_enable_paid_or_external_providers() -> None:
    values = load_yaml("deploy/helm/control-plane/values.yaml")
    config = values["config"]
    assert isinstance(config, dict)
    assert config["mockProvidersEnabled"] is True
    assert config["ollamaEnabled"] is False
    assert config["awsBedrockEnabled"] is False
    assert values["redis"] == {"enabled": False, "image": "redis:7.4-alpine"}


def test_cloud_run_terraform_is_bounded_and_not_automatically_applied() -> None:
    main = (ROOT / "infra/terraform/cloud-run/main.tf").read_text()
    variables = (ROOT / "infra/terraform/cloud-run/variables.tf").read_text()
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()

    assert "min_instance_count = 0" in main
    assert "max_instance_count = var.max_instances" in main
    assert 'value = "false"' in main
    assert "default     = 2" in variables
    assert "default     = 5" in variables
    assert "terraform apply" not in workflow
