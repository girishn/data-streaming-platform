locals {
  common_tags = merge(
    {
      environment = var.environment_name
      managed-by  = "terraform"
      platform    = "data-streaming"
    },
    var.tags,
  )
}

# ── EKS Cluster ───────────────────────────────────────────────────────────────

resource "aws_eks_cluster" "main" {
  name     = var.cluster_name
  version  = var.kubernetes_version
  role_arn = aws_iam_role.eks_cluster.arn

  vpc_config {
    subnet_ids              = var.private_subnet_ids
    endpoint_private_access = true
    endpoint_public_access  = var.endpoint_public_access
    public_access_cidrs     = length(var.public_access_cidrs) > 0 ? var.public_access_cidrs : null
  }

  enabled_cluster_log_types = ["api", "audit", "authenticator", "controllerManager", "scheduler"]

  depends_on = [
    aws_iam_role_policy_attachment.eks_cluster_policy,
    aws_iam_role_policy_attachment.eks_vpc_resource_controller,
  ]

  tags = local.common_tags
}

# ── Managed Node Group — Connect Workers ─────────────────────────────────────

resource "aws_eks_node_group" "connect" {
  cluster_name    = aws_eks_cluster.main.name
  node_group_name = "${var.cluster_name}-connect-workers"
  node_role_arn   = aws_iam_role.eks_nodes.arn
  subnet_ids      = var.private_subnet_ids
  instance_types  = var.node_instance_types

  scaling_config {
    min_size     = var.node_min_size
    max_size     = var.node_max_size
    desired_size = var.node_desired_size
  }

  update_config {
    max_unavailable = 1
  }

  labels = {
    role = "connect-worker"
  }

  depends_on = [
    aws_iam_role_policy_attachment.eks_worker_node_policy,
    aws_iam_role_policy_attachment.eks_cni_policy,
    aws_iam_role_policy_attachment.eks_ecr_readonly,
  ]

  tags = merge(local.common_tags, { Name = "${var.cluster_name}-connect-workers" })
}

# ── EKS Add-ons ───────────────────────────────────────────────────────────────

resource "aws_eks_addon" "coredns" {
  cluster_name = aws_eks_cluster.main.name
  addon_name   = "coredns"
  tags         = local.common_tags
}

resource "aws_eks_addon" "kube_proxy" {
  cluster_name = aws_eks_cluster.main.name
  addon_name   = "kube-proxy"
  tags         = local.common_tags
}

resource "aws_eks_addon" "vpc_cni" {
  cluster_name             = aws_eks_cluster.main.name
  addon_name               = "vpc-cni"
  service_account_role_arn = aws_iam_role.vpc_cni_irsa.arn
  tags                     = local.common_tags
}

resource "aws_eks_addon" "eks_pod_identity" {
  cluster_name = aws_eks_cluster.main.name
  addon_name   = "eks-pod-identity-agent"
  tags         = local.common_tags
}
