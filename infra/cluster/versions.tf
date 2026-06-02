terraform {
  required_version = ">= 1.6"

  required_providers {
    confluent = {
      source  = "confluentinc/confluent"
      version = "~> 2.0"
    }
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# Org-level Cloud API key — creates and manages API keys, role bindings.
# Cluster-level resources (topics, ACLs) use per-resource credentials {} blocks
# referencing confluent_api_key.terraform_manager_kafka, avoiding a second
# provider alias before that key exists.
provider "confluent" {
  cloud_api_key    = var.confluent_cloud_api_key
  cloud_api_secret = var.confluent_cloud_api_secret
}

provider "aws" {
  region = var.aws_region
}
