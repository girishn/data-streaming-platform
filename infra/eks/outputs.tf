output "cluster_name" {
  value = aws_eks_cluster.main.name
}

output "cluster_endpoint" {
  value = aws_eks_cluster.main.endpoint
}

output "cluster_ca_data" {
  description = "Base64-encoded CA certificate — used in kubeconfig and Helm provider"
  value       = aws_eks_cluster.main.certificate_authority[0].data
}

output "oidc_provider_arn" {
  description = "OIDC provider ARN — used to create additional IRSA roles"
  value       = aws_iam_openid_connect_provider.eks.arn
}

output "oidc_issuer" {
  description = "OIDC issuer URL (without https://) — used in IRSA trust policy conditions"
  value       = local.oidc_issuer
}

output "cfk_connect_irsa_role_arn" {
  description = "IAM role ARN to annotate the CFK Connect ServiceAccount"
  value       = aws_iam_role.cfk_connect_irsa.arn
}

output "csi_secrets_store_irsa_role_arn" {
  description = "IAM role ARN for the CSI Secrets Store driver ServiceAccount"
  value       = aws_iam_role.csi_secrets_store_irsa.arn
}

output "node_role_arn" {
  value = aws_iam_role.eks_nodes.arn
}
