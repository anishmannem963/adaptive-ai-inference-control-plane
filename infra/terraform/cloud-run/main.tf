provider "google" {
  project = var.project_id
  region  = var.region
}

data "google_project" "current" {
  project_id = var.project_id
}

locals {
  required_apis = toset([
    "artifactregistry.googleapis.com",
    "billingbudgets.googleapis.com",
    "cloudbilling.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
  ])
}

resource "google_project_service" "apis" {
  for_each = local.required_apis

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "gateway" {
  project       = var.project_id
  location      = var.region
  repository_id = "adaptive-ai-inference"
  description   = "Container images for the adaptive inference gateway"
  format        = "DOCKER"

  depends_on = [google_project_service.apis]
}

resource "google_service_account" "gateway" {
  project      = var.project_id
  account_id   = "adaptive-inference-gateway"
  display_name = "Adaptive inference Cloud Run runtime"
}

resource "google_secret_manager_secret_iam_member" "redis" {
  count = var.redis_secret_id == "" ? 0 : 1

  project   = var.project_id
  secret_id = var.redis_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.gateway.email}"

  depends_on = [google_project_service.apis]
}

resource "google_cloud_run_v2_service" "gateway" {
  project             = var.project_id
  name                = var.service_name
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account                  = google_service_account.gateway.email
    timeout                          = "60s"
    max_instance_request_concurrency = 40

    scaling {
      min_instance_count = 0
      max_instance_count = var.max_instances
    }

    containers {
      image = var.container_image

      ports {
        name           = "http1"
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        cpu_idle          = true
        startup_cpu_boost = false
      }

      env {
        name  = "APP_ENV"
        value = "production"
      }
      env {
        name  = "MOCK_PROVIDERS_ENABLED"
        value = "true"
      }
      env {
        name  = "OLLAMA_ENABLED"
        value = "false"
      }
      env {
        name  = "AWS_BEDROCK_ENABLED"
        value = "false"
      }
      env {
        name  = "AWS_SESSION_BUDGET_USD"
        value = "0"
      }
      env {
        name  = "CACHE_ENABLED"
        value = "true"
      }
      env {
        name  = "CORS_ALLOWED_ORIGINS"
        value = var.netlify_origin
      }
      env {
        name  = "OTEL_SERVICE_NAME"
        value = "adaptive-ai-inference-control-plane"
      }

      dynamic "env" {
        for_each = var.redis_secret_id == "" ? [] : [var.redis_secret_id]
        content {
          name = "REDIS_URL"
          value_source {
            secret_key_ref {
              secret  = env.value
              version = "latest"
            }
          }
        }
      }

      startup_probe {
        initial_delay_seconds = 0
        timeout_seconds       = 3
        period_seconds        = 5
        failure_threshold     = 12
        http_get {
          path = "/health/live"
          port = 8080
        }
      }

      liveness_probe {
        initial_delay_seconds = 5
        timeout_seconds       = 3
        period_seconds        = 10
        failure_threshold     = 3
        http_get {
          path = "/health/live"
          port = 8080
        }
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  depends_on = [
    google_project_service.apis,
    google_secret_manager_secret_iam_member.redis,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "public" {
  count = var.allow_unauthenticated ? 1 : 0

  project  = var.project_id
  location = google_cloud_run_v2_service.gateway.location
  name     = google_cloud_run_v2_service.gateway.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_billing_budget" "project" {
  count = var.billing_account_id == "" ? 0 : 1

  billing_account = var.billing_account_id
  display_name    = "${var.service_name} monthly alert"

  budget_filter {
    projects = ["projects/${data.google_project.current.number}"]
  }

  amount {
    specified_amount {
      currency_code = "USD"
      units         = tostring(var.monthly_budget_usd)
    }
  }

  threshold_rules {
    threshold_percent = 0.5
  }
  threshold_rules {
    threshold_percent = 0.9
  }
  threshold_rules {
    threshold_percent = 1.0
  }

  depends_on = [google_project_service.apis]
}
