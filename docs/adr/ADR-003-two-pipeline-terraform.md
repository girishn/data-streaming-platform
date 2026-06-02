# ADR-003: Two-Pipeline Terraform Model

## Decision
Separate Terraform state into two independent pipelines:
- **Infrastructure pipeline** (`infra/platform/`, `infra/eks/`): cluster, networking, service accounts, EKS
- **Cluster pipeline** (`infra/cluster/`): topics, ACLs, RBAC role bindings, schemas, quotas

## KB Source
`10-Operational-Patterns/gitops-terraform.md` — Two-pipeline model, ArgoCD scope section

## Rationale
The KB documents this pattern explicitly. Key reasons:
- **Blast radius isolation** — a misconfigured topic PR cannot accidentally destroy the EKS cluster or Confluent environment.
- **Frequency mismatch** — infrastructure changes are infrequent; topic/schema changes happen per team onboarding and per feature. Separating them avoids blocking team onboarding on infra lock.
- **ArgoCD scope** — ArgoCD manages Kubernetes manifests (CFK CRDs). It does NOT manage Confluent Cloud resources. Terraform CI/CD manages Confluent Cloud. Conflating them would require cross-tool orchestration.
- **Delegation** — the cluster pipeline can be delegated to team pipelines once per-team isolation patterns are established.

## Consequences
- Two Terraform state files in the same S3 bucket, different keys.
- Cross-state references use explicit variable passing (infra outputs → cluster pipeline inputs).
- A team-level topic PR does not require platform team approval or infra pipeline access.
