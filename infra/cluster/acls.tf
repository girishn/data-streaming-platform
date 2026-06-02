# Connect worker ACLs for the cfk-connect service account.
#
# KB Source: 09-Security-Architecture/rbac.md — self-managed Connect workers
#   require ACLs (not RBAC). RBAC does not cover transactional IDs and does not
#   express the per-operation grants Connect workers need on internal topics.
# KB Source: 05-Enterprise-Connect/managed-connectors.md — Connect internal
#   topics: connect-configs, connect-offsets, connect-status. Workers share
#   group.id for task distribution.
#
# [KB_GAP: Kafka Connect worker required ACL operations per resource type]
# The KB confirms ACLs are required and names the internal topics and group,
# but does not specify the exact operation set (READ/WRITE/CREATE/DESCRIBE/DELETE)
# per resource type for the worker service account. The ACL resources below
# are structured correctly (resource types, names, pattern types, principal)
# but the operation fields are marked with TODO and must be validated against
# Confluent's Connect worker ACL documentation before applying.
#
# CFK Connect worker group.id: CFK uses the Connect CR name as the group.id
# prefix. For the CR named "connect" in namespace "confluent", the worker
# group.id is "connect". Confirm with: kubectl describe connect connect -n confluent.

locals {
  connect_principal = "User:${var.sa_cfk_connect_id}"
  connect_group_id  = "connect" # CFK CR name — verify against deployed Connect CR
}

# ── Internal topic ACLs ───────────────────────────────────────────────────────
# [KB_GAP] Replace TODO_OPERATION with the correct set for each resource.
# Typical set for Connect internal topics: READ, WRITE, CREATE, DESCRIBE.
# Each operation requires a separate confluent_kafka_acl resource.

resource "confluent_kafka_acl" "connect_configs_read" {
  kafka_cluster { id = var.cluster_id }
  resource_type = "TOPIC"
  resource_name = "connect-configs"
  pattern_type  = "LITERAL"
  principal     = local.connect_principal
  host          = "*"
  operation     = "READ" # [KB_GAP] — confirm full operation set
  permission    = "ALLOW"
  rest_endpoint = var.cluster_rest_endpoint
  credentials {
    key    = confluent_api_key.terraform_manager_kafka.id
    secret = confluent_api_key.terraform_manager_kafka.secret
  }
}

resource "confluent_kafka_acl" "connect_configs_write" {
  kafka_cluster { id = var.cluster_id }
  resource_type = "TOPIC"
  resource_name = "connect-configs"
  pattern_type  = "LITERAL"
  principal     = local.connect_principal
  host          = "*"
  operation     = "WRITE" # [KB_GAP] — confirm full operation set
  permission    = "ALLOW"
  rest_endpoint = var.cluster_rest_endpoint
  credentials {
    key    = confluent_api_key.terraform_manager_kafka.id
    secret = confluent_api_key.terraform_manager_kafka.secret
  }
}

resource "confluent_kafka_acl" "connect_configs_describe" {
  kafka_cluster { id = var.cluster_id }
  resource_type = "TOPIC"
  resource_name = "connect-configs"
  pattern_type  = "LITERAL"
  principal     = local.connect_principal
  host          = "*"
  operation     = "DESCRIBE" # [KB_GAP]
  permission    = "ALLOW"
  rest_endpoint = var.cluster_rest_endpoint
  credentials {
    key    = confluent_api_key.terraform_manager_kafka.id
    secret = confluent_api_key.terraform_manager_kafka.secret
  }
}

resource "confluent_kafka_acl" "connect_offsets_read" {
  kafka_cluster { id = var.cluster_id }
  resource_type = "TOPIC"
  resource_name = "connect-offsets"
  pattern_type  = "LITERAL"
  principal     = local.connect_principal
  host          = "*"
  operation     = "READ"
  permission    = "ALLOW"
  rest_endpoint = var.cluster_rest_endpoint
  credentials {
    key    = confluent_api_key.terraform_manager_kafka.id
    secret = confluent_api_key.terraform_manager_kafka.secret
  }
}

resource "confluent_kafka_acl" "connect_offsets_write" {
  kafka_cluster { id = var.cluster_id }
  resource_type = "TOPIC"
  resource_name = "connect-offsets"
  pattern_type  = "LITERAL"
  principal     = local.connect_principal
  host          = "*"
  operation     = "WRITE"
  permission    = "ALLOW"
  rest_endpoint = var.cluster_rest_endpoint
  credentials {
    key    = confluent_api_key.terraform_manager_kafka.id
    secret = confluent_api_key.terraform_manager_kafka.secret
  }
}

resource "confluent_kafka_acl" "connect_offsets_describe" {
  kafka_cluster { id = var.cluster_id }
  resource_type = "TOPIC"
  resource_name = "connect-offsets"
  pattern_type  = "LITERAL"
  principal     = local.connect_principal
  host          = "*"
  operation     = "DESCRIBE"
  permission    = "ALLOW"
  rest_endpoint = var.cluster_rest_endpoint
  credentials {
    key    = confluent_api_key.terraform_manager_kafka.id
    secret = confluent_api_key.terraform_manager_kafka.secret
  }
}

resource "confluent_kafka_acl" "connect_status_read" {
  kafka_cluster { id = var.cluster_id }
  resource_type = "TOPIC"
  resource_name = "connect-status"
  pattern_type  = "LITERAL"
  principal     = local.connect_principal
  host          = "*"
  operation     = "READ"
  permission    = "ALLOW"
  rest_endpoint = var.cluster_rest_endpoint
  credentials {
    key    = confluent_api_key.terraform_manager_kafka.id
    secret = confluent_api_key.terraform_manager_kafka.secret
  }
}

resource "confluent_kafka_acl" "connect_status_write" {
  kafka_cluster { id = var.cluster_id }
  resource_type = "TOPIC"
  resource_name = "connect-status"
  pattern_type  = "LITERAL"
  principal     = local.connect_principal
  host          = "*"
  operation     = "WRITE"
  permission    = "ALLOW"
  rest_endpoint = var.cluster_rest_endpoint
  credentials {
    key    = confluent_api_key.terraform_manager_kafka.id
    secret = confluent_api_key.terraform_manager_kafka.secret
  }
}

resource "confluent_kafka_acl" "connect_status_describe" {
  kafka_cluster { id = var.cluster_id }
  resource_type = "TOPIC"
  resource_name = "connect-status"
  pattern_type  = "LITERAL"
  principal     = local.connect_principal
  host          = "*"
  operation     = "DESCRIBE"
  permission    = "ALLOW"
  rest_endpoint = var.cluster_rest_endpoint
  credentials {
    key    = confluent_api_key.terraform_manager_kafka.id
    secret = confluent_api_key.terraform_manager_kafka.secret
  }
}

# ── Consumer group ACL ────────────────────────────────────────────────────────
# Workers coordinate task rebalancing via the Connect consumer group.
# [KB_GAP] Confirm group.id matches CFK Connect CR deployment.

resource "confluent_kafka_acl" "connect_group_read" {
  kafka_cluster { id = var.cluster_id }
  resource_type = "GROUP"
  resource_name = local.connect_group_id
  pattern_type  = "LITERAL"
  principal     = local.connect_principal
  host          = "*"
  operation     = "READ"
  permission    = "ALLOW"
  rest_endpoint = var.cluster_rest_endpoint
  credentials {
    key    = confluent_api_key.terraform_manager_kafka.id
    secret = confluent_api_key.terraform_manager_kafka.secret
  }
}

# ── Platform DLQ write access ─────────────────────────────────────────────────
# Connect tasks write failed records to platform.connect.dlq.v1.

resource "confluent_kafka_acl" "connect_dlq_write" {
  kafka_cluster { id = var.cluster_id }
  resource_type = "TOPIC"
  resource_name = confluent_kafka_topic.platform_connect_dlq.topic_name
  pattern_type  = "LITERAL"
  principal     = local.connect_principal
  host          = "*"
  operation     = "WRITE"
  permission    = "ALLOW"
  rest_endpoint = var.cluster_rest_endpoint
  credentials {
    key    = confluent_api_key.terraform_manager_kafka.id
    secret = confluent_api_key.terraform_manager_kafka.secret
  }
}
