# ── API key IDs (non-sensitive — secrets are in Secrets Manager) ──────────────

output "terraform_manager_kafka_key_id" {
  description = "Terraform-manager Kafka API key ID"
  value       = confluent_api_key.terraform_manager_kafka.id
}

output "cfk_connect_kafka_key_id" {
  description = "CFK Connect Kafka API key ID"
  value       = confluent_api_key.cfk_connect_kafka.id
}

output "monitoring_kafka_key_id" {
  description = "Monitoring Kafka API key ID"
  value       = confluent_api_key.monitoring_kafka.id
}

# ── Schema Registry ───────────────────────────────────────────────────────────
# Empty string when schema_registry_active = false.
# Consumed by cluster_pipeline.py to activate the schemaRegistry block in
# kubernetes/connect/connect.yaml via provision.py re-run.

output "schema_registry_endpoint" {
  description = "Schema Registry REST endpoint. Empty until schema_registry_active = true."
  value       = var.schema_registry_active ? data.confluent_schema_registry_cluster.main[0].rest_endpoint : ""
}

output "schema_registry_id" {
  description = "Schema Registry cluster ID. Empty until schema_registry_active = true."
  value       = var.schema_registry_active ? data.confluent_schema_registry_cluster.main[0].id : ""
}

# ── Secret paths (for reference by other pipelines) ───────────────────────────

output "jaas_secret_path" {
  description = "Secrets Manager path for cfk-connect JAAS config (mounted by secret-sync.yaml)"
  value       = aws_secretsmanager_secret.cfk_connect_jaas.name
}
