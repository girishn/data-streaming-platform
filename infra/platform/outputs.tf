# ── Confluent Cloud ───────────────────────────────────────────────────────────

output "environment_id" {
  description = "Confluent Cloud environment ID"
  value       = confluent_environment.main.id
}

output "cluster_id" {
  description = "Kafka cluster ID — used by cluster pipeline Terraform"
  value       = confluent_kafka_cluster.main.id
}

output "cluster_bootstrap_endpoint" {
  description = "Kafka bootstrap endpoint — resolves to PrivateLink IPs within VPC"
  value       = confluent_kafka_cluster.main.bootstrap_endpoint
}

output "cluster_rest_endpoint" {
  description = "Kafka REST endpoint — used by Terraform cluster pipeline for topic management"
  value       = confluent_kafka_cluster.main.rest_endpoint
}

# ── Service Account IDs ───────────────────────────────────────────────────────
# Consumed by the cluster pipeline to scope RBAC bindings.

output "sa_terraform_manager_id" {
  description = "Service account ID for cluster pipeline Terraform"
  value       = confluent_service_account.terraform_manager.id
}

output "sa_cfk_connect_id" {
  description = "Service account ID for CFK Connect workers"
  value       = confluent_service_account.cfk_connect.id
}

output "sa_monitoring_id" {
  description = "Service account ID for metrics collection"
  value       = confluent_service_account.monitoring.id
}

# ── Networking ────────────────────────────────────────────────────────────────

output "vpc_endpoint_id" {
  description = "VPC endpoint ID for the Confluent PrivateLink connection"
  value       = aws_vpc_endpoint.confluent.id
}

output "route53_zone_id" {
  description = "Route 53 Private Hosted Zone ID for Confluent DNS"
  value       = aws_route53_zone.confluent.zone_id
}
