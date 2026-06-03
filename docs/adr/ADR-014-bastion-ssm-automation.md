# ADR-014: SSM Bastion for Automated Cluster Pipeline Execution

## Decision

The `cluster_pipeline.py --via-bastion` flag launches a temporary EC2 t3.micro in the
platform VPC private subnet, runs the cluster pipeline on it via AWS Systems Manager (SSM),
then terminates the instance and deletes the ephemeral credential secret. This enables
fully automated in-VPC execution from any machine without SSH, key pairs, or inbound
security group rules.

## KB Source

`10-Operational-Patterns/gitops-terraform.md` — cluster pipeline in-VPC execution model  
`09-Security-Architecture/private-networking.md` — PrivateLink DNS resolution constraint  
ADR-010 — established the in-VPC requirement

## Rationale

**Why SSM over SSH**: SSM uses IAM-authenticated HTTPS outbound from the instance to
`ssm.{region}.amazonaws.com` via the existing NAT gateway. No inbound port 22, no key pairs,
no security group rules beyond the existing egress-all default. CloudTrail records every
`send-command` invocation; `SecretString` values are redacted on both put and get.

**Why a private subnet**: The instance is placed in a private subnet (no public IP). SSM
connectivity is outbound-only via NAT — the same path as EKS nodes. This eliminates any
public IP attack surface while preserving VPC-internal access to the PrivateLink endpoint.

**Why ephemeral credentials**: The org-level Confluent Cloud API key (`CONFLUENT_CLOUD_API_KEY`
/ `CONFLUENT_CLOUD_API_SECRET`) is written to Secrets Manager immediately before launch and
force-deleted in the `finally` block — whether the pipeline succeeds or fails. The secret
lives for ~5–10 minutes (bastion startup + pipeline apply). It is stored under
`/{env}/pipeline/org-api-key`, not `/{env}/confluent/*`, so the CFK Connect and CSI Secrets
Store IAM roles cannot read it. The org key is never passed through `send-command` parameters
(which appear in CloudTrail plaintext); the bastion reads it directly from Secrets Manager
using its instance profile.

**Why a dedicated IAM instance profile**: The `cfk-connect` IRSA role has `secretsmanager:
GetSecretValue` on `/{env}/confluent/*` only — insufficient for Terraform state (S3 +
DynamoDB) and secret creation. The bastion instance profile (`{cluster}-cluster-pipeline-
bastion`) is scoped separately: S3 + DynamoDB for TF state, secret create/manage on
`/{env}/confluent/*`, and secret read on `/{env}/pipeline/*`.

**Full log in S3**: SSM `get-command-invocation` truncates stdout at ~48 KB — too small for a
full Confluent provider `terraform apply`. `send-command` is configured with
`OutputS3BucketName` pointing to the existing TF state bucket (`logs/cluster-pipeline/{env}/`
prefix). The script polls `Status` (not stdout) and fetches the complete log from S3 after
the terminal state is reached.

**20 GB root volume**: Default AL2023 8 GB root is insufficient for the Confluent TF provider
(~200 MB) + Python environment + Terraform provider cache. `BlockDeviceMappings` sets 20 GB
gp3 (`DeleteOnTermination: true`).

## Destroy symmetry

The same `--via-bastion` automation applies to teardown. `destroy.py --cluster-only` has the
same in-VPC constraint as `cluster_pipeline.py`. To automate it, the same pattern applies:

```
uv run --project scripts scripts/destroy.py --env dev --cluster-only
```

A `--via-bastion` flag on `destroy.py` can be added following the identical pattern if needed.

## Consequences

- `provision.py` is unchanged — it has no in-VPC constraint.
- `cluster_pipeline.py --via-bastion` is the recommended invocation for developer laptops.
- The `--via-bastion` path short-circuits before `check_vpc_warning()` so the VPC prompt
  is not shown to the calling machine.
- The inner bastion invocation carries `--yes` (no interactive prompt on the remote side).
- EKS must be provisioned first (`provision.py`) — the instance profile is created by
  `infra/eks/iam.tf` as part of the EKS pipeline.
- EC2 cost: t3.micro in ap-southeast-2 is ~$0.013/hr; a typical apply takes 5–10 min (~$0.002).
