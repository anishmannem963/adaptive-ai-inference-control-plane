output "cloud_run_url" {
  description = "Gateway origin to enter in the Netlify dashboard."
  value       = google_cloud_run_v2_service.gateway.uri
}

output "artifact_registry_repository" {
  description = "Docker repository used for immutable gateway images."
  value       = google_artifact_registry_repository.gateway.name
}

output "runtime_service_account" {
  description = "Least-privilege identity assigned to the Cloud Run revision."
  value       = google_service_account.gateway.email
}
