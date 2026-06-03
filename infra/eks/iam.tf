# ── EKS Cluster Role ──────────────────────────────────────────────────────────

resource "aws_iam_role" "eks_cluster" {
  name = "${var.cluster_name}-cluster-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "eks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "eks_cluster_policy" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
  role       = aws_iam_role.eks_cluster.name
}

resource "aws_iam_role_policy_attachment" "eks_vpc_resource_controller" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSVPCResourceController"
  role       = aws_iam_role.eks_cluster.name
}

# ── EKS Node Role ─────────────────────────────────────────────────────────────

resource "aws_iam_role" "eks_nodes" {
  name = "${var.cluster_name}-node-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "eks_worker_node_policy" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy"
  role       = aws_iam_role.eks_nodes.name
}

resource "aws_iam_role_policy_attachment" "eks_cni_policy" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"
  role       = aws_iam_role.eks_nodes.name
}

resource "aws_iam_role_policy_attachment" "eks_ecr_readonly" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
  role       = aws_iam_role.eks_nodes.name
}

# ── OIDC Provider — enables IRSA ──────────────────────────────────────────────

data "tls_certificate" "eks_oidc" {
  url = aws_eks_cluster.main.identity[0].oidc[0].issuer
}

resource "aws_iam_openid_connect_provider" "eks" {
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.eks_oidc.certificates[0].sha1_fingerprint]
  url             = aws_eks_cluster.main.identity[0].oidc[0].issuer

  tags = local.common_tags
}

locals {
  oidc_issuer = replace(aws_iam_openid_connect_provider.eks.url, "https://", "")
}

# ── IRSA — VPC CNI ────────────────────────────────────────────────────────────

resource "aws_iam_role" "vpc_cni_irsa" {
  name = "${var.cluster_name}-vpc-cni-irsa"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.eks.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "${local.oidc_issuer}:sub" = "system:serviceaccount:kube-system:aws-node"
          "${local.oidc_issuer}:aud" = "sts.amazonaws.com"
        }
      }
    }]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "vpc_cni_irsa" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"
  role       = aws_iam_role.vpc_cni_irsa.name
}

# ── IRSA — CFK Connect Workers ────────────────────────────────────────────────
# ServiceAccount: confluent/connect
# Permissions: read Confluent API key secrets from Secrets Manager

resource "aws_iam_role" "cfk_connect_irsa" {
  name = "${var.cluster_name}-cfk-connect-irsa"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.eks.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "${local.oidc_issuer}:sub" = "system:serviceaccount:confluent:connect"
          "${local.oidc_issuer}:aud" = "sts.amazonaws.com"
        }
      }
    }]
  })

  tags = local.common_tags
}

resource "aws_iam_policy" "cfk_connect_secrets" {
  name        = "${var.cluster_name}-cfk-connect-secrets"
  description = "Allow CFK Connect workers to read Confluent API keys from Secrets Manager"
  tags        = local.common_tags

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "secretsmanager:GetSecretValue",
        "secretsmanager:DescribeSecret",
      ]
      Resource = "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:${var.confluent_secrets_path_prefix}/*"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "cfk_connect_secrets" {
  policy_arn = aws_iam_policy.cfk_connect_secrets.arn
  role       = aws_iam_role.cfk_connect_irsa.name
}

# ── IRSA — CSI Secrets Store Driver ──────────────────────────────────────────
# The driver's provider pod needs GetSecretValue to mount secrets into pods.

resource "aws_iam_role" "csi_secrets_store_irsa" {
  name = "${var.cluster_name}-csi-secrets-store-irsa"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.eks.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "${local.oidc_issuer}:sub" = "system:serviceaccount:kube-system:secrets-store-csi-driver"
          "${local.oidc_issuer}:aud" = "sts.amazonaws.com"
        }
      }
    }]
  })

  tags = local.common_tags
}

resource "aws_iam_policy" "csi_secrets_store" {
  name        = "${var.cluster_name}-csi-secrets-store"
  description = "Allow CSI Secrets Store driver to read secrets on behalf of pods"
  tags        = local.common_tags

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "secretsmanager:GetSecretValue",
        "secretsmanager:DescribeSecret",
      ]
      Resource = "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:${var.confluent_secrets_path_prefix}/*"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "csi_secrets_store" {
  policy_arn = aws_iam_policy.csi_secrets_store.arn
  role       = aws_iam_role.csi_secrets_store_irsa.name
}

# ── Cluster Pipeline Bastion ──────────────────────────────────────────────────
# EC2 instance profile for the temporary SSM bastion that runs infra/cluster.
# Kept separate from the CFK Connect IRSA role — the bastion needs TF state
# access and secret-write permission that Connect workers must never have.
# Org-level Confluent API key lives under pipeline_secrets_path_prefix, not
# confluent_secrets_path_prefix, so Connect pods cannot read it.

resource "aws_iam_role" "cluster_pipeline_bastion" {
  name = "${var.cluster_name}-cluster-pipeline-bastion"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = local.common_tags
}

resource "aws_iam_instance_profile" "cluster_pipeline_bastion" {
  name = "${var.cluster_name}-cluster-pipeline-bastion"
  role = aws_iam_role.cluster_pipeline_bastion.name
  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "bastion_ssm_core" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
  role       = aws_iam_role.cluster_pipeline_bastion.name
}

resource "aws_iam_policy" "cluster_pipeline_bastion" {
  name        = "${var.cluster_name}-cluster-pipeline-bastion"
  description = "Cluster pipeline bastion: Terraform state, cluster secret management, org credential read"
  tags        = local.common_tags

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "TFStateBucket"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket",
        ]
        Resource = [
          "arn:aws:s3:::${var.tf_bucket}",
          "arn:aws:s3:::${var.tf_bucket}/*",
        ]
      },
      {
        Sid    = "TFStateLock"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:DeleteItem",
        ]
        Resource = "arn:aws:dynamodb:${var.aws_region}:${var.aws_account_id}:table/${var.tf_table}"
      },
      {
        Sid    = "ClusterSecretsManage"
        Effect = "Allow"
        Action = [
          "secretsmanager:CreateSecret",
          "secretsmanager:GetSecretValue",
          "secretsmanager:PutSecretValue",
          "secretsmanager:DescribeSecret",
          "secretsmanager:GetResourcePolicy",
          "secretsmanager:TagResource",
          "secretsmanager:DeleteSecret",
        ]
        Resource = "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:${var.confluent_secrets_path_prefix}/*"
      },
      {
        Sid    = "CloudWatchLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
          "logs:DescribeLogStreams",
        ]
        Resource = "arn:aws:logs:${var.aws_region}:${var.aws_account_id}:log-group:/data-streaming/*/cluster-pipeline*"
      },
      {
        Sid    = "OrgCredentialsRead"
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret",
        ]
        Resource = "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:/${var.environment_name}/pipeline/*"
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "cluster_pipeline_bastion" {
  policy_arn = aws_iam_policy.cluster_pipeline_bastion.arn
  role       = aws_iam_role.cluster_pipeline_bastion.name
}
