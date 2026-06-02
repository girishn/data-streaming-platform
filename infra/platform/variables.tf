# ── Confluent Cloud auth ──────────────────────────────────────────────────────
# Provide via environment variables: TF_VAR_confluent_cloud_api_key / _secret
# These are org-level Cloud API keys, not cluster keys.

variable "confluent_cloud_api_key" {
  description = "Confluent Cloud org-level API key for Terraform"
  type        = string
  sensitive   = true
}

variable "confluent_cloud_api_secret" {
  description = "Confluent Cloud org-level API secret for Terraform"
  type        = string
  sensitive   = true
}

# ── Environment ───────────────────────────────────────────────────────────────

variable "environment_name" {
  description = "Confluent Cloud environment name (e.g. data-streaming-prod)"
  type        = string
}

# ── Cluster ───────────────────────────────────────────────────────────────────

variable "cluster_name" {
  description = "Kafka cluster display name"
  type        = string
  default     = "data-streaming-cluster"
}

variable "cluster_cku" {
  description = "Number of Confluent Kafka Units. 1 CKU ≈ 250 MB/s. Minimum 2 for MULTI_ZONE."
  type        = number
  default     = 2
}

variable "cluster_availability" {
  description = "Cluster availability zone mode. SINGLE_ZONE allows 1 CKU (dev cost saving). MULTI_ZONE requires >= 2 CKU."
  type        = string
  default     = "MULTI_ZONE"

  validation {
    condition     = contains(["SINGLE_ZONE", "MULTI_ZONE"], var.cluster_availability)
    error_message = "cluster_availability must be SINGLE_ZONE or MULTI_ZONE."
  }
}

# ── AWS ───────────────────────────────────────────────────────────────────────

variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "ap-southeast-2"
}

variable "aws_account_id" {
  description = "AWS account ID — required to authorise PrivateLink access from this account"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID where the PrivateLink endpoint will be created"
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet IDs (one per AZ) for the VPC endpoint ENIs"
  type        = list(string)
}

variable "private_subnet_cidrs" {
  description = "Private subnet CIDR blocks — used to scope PrivateLink endpoint SG ingress"
  type        = list(string)
}

variable "availability_zones" {
  description = "AZs matching private_subnet_ids — used for per-broker Route 53 zonal CNAME records. Fed from networking outputs."
  type        = list(string)
  default     = ["ap-southeast-2a", "ap-southeast-2b", "ap-southeast-2c"]
}

# ── Tags ──────────────────────────────────────────────────────────────────────

variable "tags" {
  description = "Additional tags to merge onto all resources"
  type        = map(string)
  default     = {}
}
