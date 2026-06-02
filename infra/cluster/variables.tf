# ── Confluent Cloud auth ──────────────────────────────────────────────────────
# Org-level Cloud API key — same credentials as the infra pipeline.
# Provide via environment variables: TF_VAR_confluent_cloud_api_key / _secret

variable "confluent_cloud_api_key" {
  description = "Confluent Cloud org-level API key"
  type        = string
  sensitive   = true
}

variable "confluent_cloud_api_secret" {
  description = "Confluent Cloud org-level API secret"
  type        = string
  sensitive   = true
}

# ── Infra pipeline outputs (injected as TF_VAR_* by cluster_pipeline.py) ─────

variable "environment_name" {
  description = "Confluent Cloud environment display name (e.g. data-streaming-dev)"
  type        = string
}

variable "environment_id" {
  description = "Confluent Cloud environment ID — from infra/platform output"
  type        = string
}

variable "cluster_id" {
  description = "Kafka cluster ID — from infra/platform output"
  type        = string
}

variable "cluster_rest_endpoint" {
  description = "Kafka cluster REST endpoint — required for topic/ACL management via PrivateLink"
  type        = string
}

variable "sa_terraform_manager_id" {
  description = "Service account ID for cluster pipeline Terraform — from infra/platform output"
  type        = string
}

variable "sa_cfk_connect_id" {
  description = "Service account ID for CFK Connect workers — from infra/platform output"
  type        = string
}

variable "sa_monitoring_id" {
  description = "Service account ID for metrics collection — from infra/platform output"
  type        = string
}

# ── AWS ───────────────────────────────────────────────────────────────────────

variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "ap-southeast-2"
}

variable "aws_account_id" {
  description = "AWS account ID"
  type        = string
}

# ── Schema Registry ───────────────────────────────────────────────────────────
# SR is lazily provisioned on ESSENTIALS — it does not exist until the first
# schema is registered. Set this to true only after SR has been activated
# (a connector's serialiser has registered the first schema, or manual CLI
# registration). Until then, the data source call loops indefinitely.
# KB Source: platform-state.md KB gap — Confluent ESSENTIALS SR lazy provisioning

variable "schema_registry_active" {
  description = "Enable SR resources. Set true only after first schema is registered."
  type        = bool
  default     = false
}

# ── Tags ──────────────────────────────────────────────────────────────────────

variable "tags" {
  description = "Additional tags to merge onto all AWS resources"
  type        = map(string)
  default     = {}
}
