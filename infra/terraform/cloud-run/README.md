# Cloud Run deployment

This configuration prepares the free-first public gateway without creating a paid Kubernetes cluster. It creates:

- required Google Cloud API enablement
- one regional Artifact Registry Docker repository
- one least-privilege Cloud Run runtime service account
- one Cloud Run service with scale-to-zero and a bounded maximum instance count
- optional access to an existing Redis URL in Secret Manager
- optional billing-budget alerts

It does not create Redis, insert secret values, enable Bedrock, or run automatically from CI.

## Prerequisites

Create a Google Cloud project, attach billing, and authenticate Terraform locally. Copy `terraform.tfvars.example` to an ignored `terraform.tfvars` file and replace the project and immutable image values.

~~~bash
gcloud auth application-default login
terraform init
terraform fmt -check
terraform validate
terraform plan -out=tfplan
~~~

Inspect the complete plan before explicitly running `terraform apply tfplan`. A configured budget is an alerting mechanism, not a hard spending cap.

When testing is complete, remove provisioned resources with an inspected destroy plan:

~~~bash
terraform plan -destroy -out=destroy.tfplan
terraform apply destroy.tfplan
~~~

The application image must exist before Cloud Run can deploy it. Container publishing automation is intentionally deferred until the project and Workload Identity configuration are available; do not commit service-account keys.
