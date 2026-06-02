variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "ap-southeast-2"
}

variable "environment_name" {
  description = "Environment name — used for resource naming and tagging"
  type        = string
}

variable "cluster_name" {
  description = "EKS cluster name — used to tag subnets for EKS subnet auto-discovery"
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
}

variable "private_subnet_cidrs" {
  description = "CIDR blocks for private subnets — one per AZ, for EKS nodes and PrivateLink ENIs"
  type        = list(string)
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for public subnets — one per AZ, for NAT Gateways and load balancers"
  type        = list(string)
}

variable "availability_zones" {
  description = "Availability zones — must align with private/public subnet CIDR lists"
  type        = list(string)
  default     = ["ap-southeast-2a", "ap-southeast-2b", "ap-southeast-2c"]
}

variable "single_nat_gateway" {
  description = "Use a single NAT Gateway (cost-saving for dev). Set false in prod for per-AZ HA."
  type        = bool
  default     = true
}

variable "tags" {
  description = "Additional tags to merge onto all resources"
  type        = map(string)
  default     = {}
}
