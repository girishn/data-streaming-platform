locals {
  common_tags = merge(
    {
      environment = var.environment_name
      managed-by  = "terraform"
      platform    = "data-streaming"
    },
    var.tags,
  )
}

data "confluent_organization" "main" {}

# ── Environment ───────────────────────────────────────────────────────────────

resource "confluent_environment" "main" {
  display_name = var.environment_name

  stream_governance {
    package = "ESSENTIALS"
  }
}

# ── Network (PrivateLink) ─────────────────────────────────────────────────────
# Dedicated clusters require a network to be specified at creation time.
# PRIVATE dns resolution ensures broker hostnames resolve to PrivateLink IPs.

resource "confluent_network" "main" {
  display_name     = "${var.environment_name}-network"
  cloud            = "AWS"
  region           = var.aws_region
  connection_types = ["PRIVATELINK"]

  environment {
    id = confluent_environment.main.id
  }

  dns_config {
    resolution = "PRIVATE"
  }
}

resource "confluent_private_link_access" "main" {
  display_name = "${var.environment_name}-pl-access"

  aws {
    account = var.aws_account_id
  }

  environment {
    id = confluent_environment.main.id
  }

  network {
    id = confluent_network.main.id
  }
}

# ── Kafka Cluster ─────────────────────────────────────────────────────────────
# Dedicated tier required for: PrivateLink, broker-side schema validation,
# SASL/TLS with all client types (CLAUDE.md requirement).

resource "confluent_kafka_cluster" "main" {
  display_name = var.cluster_name
  availability = var.cluster_availability
  cloud        = "AWS"
  region       = var.aws_region

  dedicated {
    cku = var.cluster_cku
  }

  environment {
    id = confluent_environment.main.id
  }

  network {
    id = confluent_network.main.id
  }
}

# ── Service Accounts ──────────────────────────────────────────────────────────
# Three platform-level accounts created here (infra pipeline).
# Application-level accounts (per team/connector) belong in the cluster pipeline.

resource "confluent_service_account" "terraform_manager" {
  display_name = "${var.environment_name}-terraform-manager"
  description  = "Cluster pipeline Terraform runs — CloudClusterAdmin on this cluster"
}

resource "confluent_service_account" "cfk_connect" {
  display_name = "${var.environment_name}-cfk-connect"
  description  = "CFK Connect workers on EKS — topic-level grants added per connector in cluster pipeline"
}

resource "confluent_service_account" "monitoring" {
  display_name = "${var.environment_name}-monitoring"
  description  = "Metrics collection — MetricsViewer at org scope"
}

# ── RBAC Role Bindings ────────────────────────────────────────────────────────

resource "confluent_role_binding" "terraform_manager_cluster_admin" {
  principal   = "User:${confluent_service_account.terraform_manager.id}"
  role_name   = "CloudClusterAdmin"
  crn_pattern = confluent_kafka_cluster.main.rbac_crn
}

resource "confluent_role_binding" "monitoring_metrics_viewer" {
  principal   = "User:${confluent_service_account.monitoring.id}"
  role_name   = "MetricsViewer"
  crn_pattern = "crn://confluent.cloud/organization=${data.confluent_organization.main.id}"
}

# ── API Keys ──────────────────────────────────────────────────────────────────
# Kafka cluster API keys are NOT created here.
# The Confluent TF provider validates each key by calling the cluster REST
# endpoint after creation. For PrivateLink-only clusters that endpoint resolves
# to a private IP unreachable from outside the VPC, causing the apply to hang.
#
# All cluster-scoped API keys (terraform-manager-kafka, cfk-connect-kafka,
# monitoring-kafka) are created in the cluster pipeline (infra/cluster/), which
# runs from inside the VPC where the endpoint is reachable.
#
# Service accounts and RBAC role bindings are created above so the cluster
# pipeline can immediately assign them permissions on first run.
