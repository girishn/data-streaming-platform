variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "ap-southeast-2"
}

variable "aws_account_id" {
  description = "AWS account ID"
  type        = string
}

variable "environment_name" {
  description = "Environment name — used to namespace IAM roles and cluster name"
  type        = string
}

variable "cluster_name" {
  description = "EKS cluster name"
  type        = string
  default     = "data-streaming-eks"
}

variable "kubernetes_version" {
  description = "EKS Kubernetes version"
  type        = string
  default     = "1.30"
}

variable "vpc_id" {
  description = "VPC ID for the EKS cluster"
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet IDs for EKS nodes and control plane ENIs"
  type        = list(string)
}

variable "node_instance_types" {
  description = "EC2 instance types for the Connect worker node group"
  type        = list(string)
  default     = ["m6i.xlarge"]
}

variable "node_min_size" {
  type    = number
  default = 2
}

variable "node_max_size" {
  type    = number
  default = 6
}

variable "node_desired_size" {
  type    = number
  default = 2
}

# Passed in from infra/platform outputs — used to scope IRSA policy
variable "confluent_secrets_path_prefix" {
  description = "AWS Secrets Manager path prefix for Confluent API keys, e.g. /data-streaming-prod/confluent"
  type        = string
}

variable "endpoint_public_access" {
  description = "Enable public EKS API server endpoint. true for dev (local kubectl); false for prod (VPN/bastion only)."
  type        = bool
  default     = false
}

variable "public_access_cidrs" {
  description = "CIDRs allowed to reach the public EKS endpoint. Empty list = unrestricted (0.0.0.0/0). Only applies when endpoint_public_access = true."
  type        = list(string)
  default     = []
}

variable "tf_bucket" {
  description = "Terraform state S3 bucket — used to scope the cluster pipeline bastion IAM policy"
  type        = string
}

variable "tf_table" {
  description = "Terraform state DynamoDB table — used to scope the cluster pipeline bastion IAM policy"
  type        = string
}

variable "tags" {
  type    = map(string)
  default = {}
}
