# Byte-rate quota floor applied to all known platform service accounts.
#
# KB Source: 13-Performance-Tuning/quota-management.md
#   Multi-tenant cluster: set a default byte-rate quota floor; per-team
#   overrides for known high-volume services.
#
# Resolved KB_GAP: confluent_kafka_client_quota requires principals >= 1.
#   The provider does not support a true (*,*) default quota via principals=[].
#   Workaround: apply the same floor to each known platform service account.
#   New application service accounts get a quota resource added at onboarding
#   time via the self-service pipeline.
#
# Sizing: dev cluster 1 CKU ≈ 250 MB/s aggregate.
#   10 MB/s per principal leaves ample headroom for platform accounts.
#   Override upward for known high-volume connectors via per-principal resources.

resource "confluent_kafka_client_quota" "terraform_manager_floor" {
  display_name = "${var.environment_name}-terraform-manager-floor"
  description  = "Byte-rate quota floor for Terraform cluster pipeline SA"

  kafka_cluster {
    id = var.cluster_id
  }

  environment {
    id = var.environment_id
  }

  throughput {
    ingress_byte_rate = "10485760" # 10 MB/s
    egress_byte_rate  = "10485760" # 10 MB/s
  }

  principals = ["User:${var.sa_terraform_manager_id}"]
}

resource "confluent_kafka_client_quota" "cfk_connect_floor" {
  display_name = "${var.environment_name}-cfk-connect-floor"
  description  = "Byte-rate quota floor for CFK Connect workers"

  kafka_cluster {
    id = var.cluster_id
  }

  environment {
    id = var.environment_id
  }

  throughput {
    ingress_byte_rate = "10485760" # 10 MB/s — raise per connector at onboarding
    egress_byte_rate  = "10485760" # 10 MB/s
  }

  principals = ["User:${var.sa_cfk_connect_id}"]
}

resource "confluent_kafka_client_quota" "monitoring_floor" {
  display_name = "${var.environment_name}-monitoring-floor"
  description  = "Byte-rate quota floor for monitoring SA"

  kafka_cluster {
    id = var.cluster_id
  }

  environment {
    id = var.environment_id
  }

  throughput {
    ingress_byte_rate = "10485760" # 10 MB/s
    egress_byte_rate  = "10485760" # 10 MB/s
  }

  principals = ["User:${var.sa_monitoring_id}"]
}
