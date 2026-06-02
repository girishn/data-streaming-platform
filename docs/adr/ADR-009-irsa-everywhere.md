# ADR-009: IRSA for All Kubernetes → AWS Service Interactions

## Decision
All EKS workloads that call AWS APIs (Secrets Manager, ECR, VPC CNI) use IAM Roles for Service Accounts (IRSA). No static IAM credentials on nodes or in environment variables. IRSA roles are scoped to the specific namespace + service account combination.

## KB Source
CLAUDE.md — "IRSA everywhere" is a fixed platform requirement.

## Rationale
IRSA binds an IAM role to a specific Kubernetes ServiceAccount via the EKS OIDC provider. This provides:
- **Pod-level identity** — the IAM role is only assumable by pods with the exact `namespace:serviceaccount` combination in the OIDC trust condition.
- **No node-level over-permission** — node IAM roles have only the minimum permissions for EKS operation (AmazonEKSWorkerNodePolicy, ECR read). No Secrets Manager access on nodes.
- **Auditability** — CloudTrail shows API calls per service account identity, not per node.

## IRSA Roles Provisioned

| Role | ServiceAccount | Permissions |
|---|---|---|
| `cfk-connect-irsa` | `confluent/connect` | `secretsmanager:GetSecretValue` on `/{env}/confluent/*` |
| `csi-secrets-store-irsa` | `kube-system/secrets-store-csi-driver` | Same Secrets Manager scope (driver reads on behalf of pods) |
| `vpc-cni-irsa` | `kube-system/aws-node` | `AmazonEKS_CNI_Policy` |

## Consequences
- ServiceAccount annotations (`eks.amazonaws.com/role-arn`) must be set before pods start. The provision script injects the ARN from Terraform outputs.
- New AWS-calling workloads must get their own IRSA role via the infra pipeline — no ad-hoc IAM credential distribution.
