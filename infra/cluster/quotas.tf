# Cluster-wide default quota floor.
#
# KB Source: 13-Performance-Tuning/quota-management.md
#   Multi-tenant cluster: set a default (*, *) byte-rate quota as a floor.
#   Per-team overrides are added as connectors and applications onboard.
#
# [KB_GAP: confluent_kafka_client_quota Terraform resource — default (*,*) syntax]
# The KB confirms the quota strategy (default floor + per-principal overrides)
# but does not document the Confluent Terraform provider schema for the
# confluent_kafka_client_quota resource, specifically whether principals = []
# creates a true default (*,*) quota or requires a different attribute.
# Validate against confluent provider v2.x docs before applying.
#
# Sizing rationale (dev cluster, 1 CKU ≈ 250 MB/s aggregate):
#   10 MB/s per principal leaves headroom for ~24 concurrent producers or
#   consumers before the default kicks in. Override upward for known
#   high-volume services via per-principal quota resources.

resource "confluent_kafka_client_quota" "default_floor" {
  display_name = "${var.environment_name}-default-floor"
  description  = "Default byte-rate quota floor — all clients not covered by a specific quota"

  kafka_cluster {
    id = var.cluster_id
  }

  environment {
    id = var.environment_id
  }

  throughput {
    ingress_byte_rate = "10485760" # 10 MB/s per principal
    egress_byte_rate  = "10485760" # 10 MB/s per principal
  }

  # [KB_GAP] Empty principals list — verify this creates a (*,*) default quota
  # in the Confluent provider v2.x. If not, this resource may need to be omitted
  # or restructured.
  principals = []
}
