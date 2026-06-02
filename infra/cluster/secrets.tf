# AWS Secrets Manager secrets for Kafka API keys and JAAS config.
# Secret paths: /{environment_name}/confluent/{name}
# These paths are checked by status.py and consumed by:
#   - kubernetes/connect/secret-provider-class.yaml  (cfk-connect-jaas)
#   - cluster pipeline Terraform re-runs             (terraform-manager-kafka)
#
# recovery_window_in_days = 0 allows immediate deletion and re-creation in
# non-production environments. Change to 7+ for prod if compliance requires it.

# ── terraform-manager-kafka ───────────────────────────────────────────────────

resource "aws_secretsmanager_secret" "terraform_manager_kafka" {
  name                    = "/${var.environment_name}/confluent/terraform-manager-kafka"
  description             = "Kafka cluster API key for Terraform cluster pipeline"
  recovery_window_in_days = 0

  tags = local.common_tags
}

resource "aws_secretsmanager_secret_version" "terraform_manager_kafka" {
  secret_id = aws_secretsmanager_secret.terraform_manager_kafka.id
  secret_string = jsonencode({
    key    = confluent_api_key.terraform_manager_kafka.id
    secret = confluent_api_key.terraform_manager_kafka.secret
  })
}

# ── cfk-connect-kafka ─────────────────────────────────────────────────────────

resource "aws_secretsmanager_secret" "cfk_connect_kafka" {
  name                    = "/${var.environment_name}/confluent/cfk-connect-kafka"
  description             = "Kafka cluster API key for CFK Connect workers"
  recovery_window_in_days = 0

  tags = local.common_tags
}

resource "aws_secretsmanager_secret_version" "cfk_connect_kafka" {
  secret_id = aws_secretsmanager_secret.cfk_connect_kafka.id
  secret_string = jsonencode({
    key    = confluent_api_key.cfk_connect_kafka.id
    secret = confluent_api_key.cfk_connect_kafka.secret
  })
}

# ── monitoring-kafka ──────────────────────────────────────────────────────────

resource "aws_secretsmanager_secret" "monitoring_kafka" {
  name                    = "/${var.environment_name}/confluent/monitoring-kafka"
  description             = "Kafka cluster API key for metrics collection"
  recovery_window_in_days = 0

  tags = local.common_tags
}

resource "aws_secretsmanager_secret_version" "monitoring_kafka" {
  secret_id = aws_secretsmanager_secret.monitoring_kafka.id
  secret_string = jsonencode({
    key    = confluent_api_key.monitoring_kafka.id
    secret = confluent_api_key.monitoring_kafka.secret
  })
}

# ── cfk-connect-jaas ──────────────────────────────────────────────────────────
# Pre-assembled SASL/PLAIN JAAS string. Stored as a raw string (not JSON) so
# the CSI driver can mount it directly as plain-jaas.conf without runtime
# assembly. This is the load-bearing secret for the secret-sync.yaml pattern.
# ADR: ADR-008-cfk-external-auth-sasl.md

resource "aws_secretsmanager_secret" "cfk_connect_jaas" {
  name                    = "/${var.environment_name}/confluent/cfk-connect-jaas"
  description             = "SASL/PLAIN JAAS config for CFK Connect → Confluent Cloud. Mounted by CSI driver as plain-jaas.conf."
  recovery_window_in_days = 0

  tags = local.common_tags
}

resource "aws_secretsmanager_secret_version" "cfk_connect_jaas" {
  secret_id = aws_secretsmanager_secret.cfk_connect_jaas.id
  secret_string = format(
    "org.apache.kafka.common.security.plain.PlainLoginModule required username=\"%s\" password=\"%s\";",
    confluent_api_key.cfk_connect_kafka.id,
    confluent_api_key.cfk_connect_kafka.secret,
  )
}
