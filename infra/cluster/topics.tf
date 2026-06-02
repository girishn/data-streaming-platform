# Platform topics managed by the cluster pipeline.
#
# Naming convention (KB Source: topic-design-framework.md):
#   {domain}.{entity}.{event-type}.v{N}
#   All lowercase, dot-separated. Domain = bounded context (not team name).
#   events suffix → append-only event stream (delete retention)
#   state  suffix → compacted latest-value table (compact cleanup)
#
# Partition sizing (KB Source: 02-Broker-Infrastructure/partitioning-strategies.md):
#   partitions = max(target_throughput / 10_MB_s, expected_max_consumers)
#   Apply 2-3x growth multiplier. Partition count cannot be reduced after creation
#   without topic recreation — over-provision rather than under-provision.
#
# Replication factor is not configurable on Confluent Cloud — Dedicated tier
# always uses RF=3. min.insync.replicas=2 is enforced per-topic.
#
# broker-side schema validation requires Dedicated tier + SR active.
# The config key is accepted even when SR is not yet active; enforcement begins
# once SR is provisioned.

# ── Platform Connect DLQ ──────────────────────────────────────────────────────
# Receives failed connector records from all CFK Connect tasks.
# KB Source: 05-Enterprise-Connect/error-handling-dlq.md (via connector-onboarding.md)
#
# Sizing: DLQ volume < 1 MB/s assumed. Max concurrent replay consumers = 6.
# partitions = max(1, 6) × 2 growth = 6 (throughput < 10 MB/s band → 3–6, take 6)

resource "confluent_kafka_topic" "platform_connect_dlq" {
  kafka_cluster {
    id = var.cluster_id
  }

  topic_name       = "platform.connect.dlq.v1"
  partitions_count = 6
  rest_endpoint    = var.cluster_rest_endpoint

  config = {
    "cleanup.policy"                    = "delete"
    "retention.ms"                      = "604800000" # 7 days — gives replay window
    "min.insync.replicas"               = "2"
    "confluent.value.schema.validation" = "true"
  }

  credentials {
    key    = confluent_api_key.terraform_manager_kafka.id
    secret = confluent_api_key.terraform_manager_kafka.secret
  }
}
