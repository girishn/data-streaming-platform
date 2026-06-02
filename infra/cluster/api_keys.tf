# Cluster-scoped API keys for the three platform service accounts.
# These CANNOT be created in the infra pipeline — the Confluent TF provider
# validates each key by calling the cluster REST endpoint, which resolves to
# a PrivateLink private IP unreachable from outside the VPC.
# ADR: ADR-010-cluster-pipeline-in-vpc.md

# ── Terraform-manager ─────────────────────────────────────────────────────────
# Used in credentials {} blocks on all topic and ACL resources in this pipeline.
# CloudClusterAdmin role binding was created by the infra pipeline.

resource "confluent_api_key" "terraform_manager_kafka" {
  display_name = "${var.environment_name}-terraform-manager-kafka"
  description  = "Cluster pipeline Terraform — topic/ACL management"

  owner {
    id          = var.sa_terraform_manager_id
    api_version = "iam/v2"
    kind        = "ServiceAccount"
  }

  managed_resource {
    id          = var.cluster_id
    api_version = "cmk/v2"
    kind        = "Cluster"

    environment {
      id = var.environment_id
    }
  }
}

# ── CFK Connect ───────────────────────────────────────────────────────────────
# JAAS config assembled from this key is stored in Secrets Manager (secrets.tf)
# and mounted by secret-sync.yaml via the CSI driver into the Connect pods.

resource "confluent_api_key" "cfk_connect_kafka" {
  display_name = "${var.environment_name}-cfk-connect-kafka"
  description  = "CFK Connect workers — Confluent Cloud Kafka access"

  owner {
    id          = var.sa_cfk_connect_id
    api_version = "iam/v2"
    kind        = "ServiceAccount"
  }

  managed_resource {
    id          = var.cluster_id
    api_version = "cmk/v2"
    kind        = "Cluster"

    environment {
      id = var.environment_id
    }
  }
}

# ── Monitoring ────────────────────────────────────────────────────────────────
# Used by the Confluent Cloud Metrics API. MetricsViewer role binding was
# created by the infra pipeline at org scope.

resource "confluent_api_key" "monitoring_kafka" {
  display_name = "${var.environment_name}-monitoring-kafka"
  description  = "Metrics collection — Confluent Cloud Metrics API"

  owner {
    id          = var.sa_monitoring_id
    api_version = "iam/v2"
    kind        = "ServiceAccount"
  }

  managed_resource {
    id          = var.cluster_id
    api_version = "cmk/v2"
    kind        = "Cluster"

    environment {
      id = var.environment_id
    }
  }
}
