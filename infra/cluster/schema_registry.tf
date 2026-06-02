# Schema Registry resources — gated behind var.schema_registry_active.
#
# SR on Confluent Cloud ESSENTIALS is lazily provisioned: the SR cluster does
# not exist until the first schema is registered. Reading the data source before
# that point loops indefinitely. Set schema_registry_active = true only after
# the first schema has been registered (typically when a connector's Avro
# serialiser registers on first produce, or via manual CLI registration).
#
# After this apply completes with schema_registry_active = true:
#   1. SR API key and role binding exist
#   2. SR API key is in Secrets Manager
#   3. Re-run provision.py to activate the schemaRegistry block in connect.yaml
#      (provision.py strips the block when SR endpoint is empty; it restores it
#       when the sr_endpoint output is non-empty)
#
# KB Source: platform-state.md KB gap — Confluent ESSENTIALS SR lazy provisioning
# ADR: ADR-013-schema-registry-bootstrap.md

data "confluent_schema_registry_cluster" "main" {
  count = var.schema_registry_active ? 1 : 0

  environment {
    id = var.environment_id
  }
}

# ── CFK Connect SR API key ────────────────────────────────────────────────────
# ResourceOwner on subject=* allows Connect to register schemas for any subject
# it produces to. Narrow to subject=<domain>.* per connector when onboarding
# is formalised through the self-service pipeline.

resource "confluent_api_key" "cfk_connect_sr" {
  count        = var.schema_registry_active ? 1 : 0
  display_name = "${var.environment_name}-cfk-connect-sr"
  description  = "Schema Registry API key for CFK Connect workers"

  owner {
    id          = var.sa_cfk_connect_id
    api_version = "iam/v2"
    kind        = "ServiceAccount"
  }

  managed_resource {
    id          = data.confluent_schema_registry_cluster.main[0].id
    api_version = "srcm/v2"
    kind        = "SchemaRegistry"

    environment {
      id = var.environment_id
    }
  }
}

resource "confluent_role_binding" "cfk_connect_sr_resource_owner" {
  count       = var.schema_registry_active ? 1 : 0
  principal   = "User:${var.sa_cfk_connect_id}"
  role_name   = "ResourceOwner"
  crn_pattern = "${data.confluent_schema_registry_cluster.main[0].resource_name}/subject=*"
}

# ── SR credentials in Secrets Manager ────────────────────────────────────────
# Stored as JSON {key, secret} — assembled into HTTP Basic auth header by the
# application layer. Not assembled as a JAAS string (SR uses Basic auth, not
# SASL/PLAIN). CFK Connect references these via the basic.secretRef in connect.yaml.

resource "aws_secretsmanager_secret" "cfk_connect_sr" {
  count                   = var.schema_registry_active ? 1 : 0
  name                    = "/${var.environment_name}/confluent/cfk-connect-sr"
  description             = "Schema Registry API key for CFK Connect workers"
  recovery_window_in_days = 0

  tags = local.common_tags
}

resource "aws_secretsmanager_secret_version" "cfk_connect_sr" {
  count     = var.schema_registry_active ? 1 : 0
  secret_id = aws_secretsmanager_secret.cfk_connect_sr[0].id
  secret_string = jsonencode({
    key    = confluent_api_key.cfk_connect_sr[0].id
    secret = confluent_api_key.cfk_connect_sr[0].secret
  })
}
