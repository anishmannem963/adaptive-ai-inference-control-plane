variable "project_id" {
  description = "Existing Google Cloud project with billing attached."
  type        = string
}

variable "region" {
  description = "Google Cloud region for Cloud Run and Artifact Registry."
  type        = string
  default     = "us-east1"
}

variable "service_name" {
  description = "Cloud Run service name."
  type        = string
  default     = "adaptive-ai-inference-control-plane"
}

variable "container_image" {
  description = "Immutable container image reference, preferably pinned by digest."
  type        = string
}

variable "netlify_origin" {
  description = "Exact browser origin permitted by CORS."
  type        = string
  default     = "https://adaptive-ai-inference-control-plane.netlify.app"

  validation {
    condition     = startswith(var.netlify_origin, "https://")
    error_message = "netlify_origin must use HTTPS."
  }
}

variable "max_instances" {
  description = "Hard Cloud Run scale ceiling protecting the free-first deployment."
  type        = number
  default     = 2

  validation {
    condition     = var.max_instances >= 1 && var.max_instances <= 10
    error_message = "max_instances must be between 1 and 10."
  }
}

variable "allow_unauthenticated" {
  description = "Expose the interview demo API publicly."
  type        = bool
  default     = true
}

variable "redis_secret_id" {
  description = "Optional existing Secret Manager secret containing a REDIS_URL value."
  type        = string
  default     = ""
}

variable "billing_account_id" {
  description = "Optional billing account ID used only to create a budget alert."
  type        = string
  default     = ""
}

variable "monthly_budget_usd" {
  description = "Alerting budget; this is not a hard spending cap."
  type        = number
  default     = 5

  validation {
    condition     = var.monthly_budget_usd > 0
    error_message = "monthly_budget_usd must be positive."
  }
}
