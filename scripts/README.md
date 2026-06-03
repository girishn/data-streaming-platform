# Scripts

All scripts run via `uv` from the repo root. The `scripts/` directory contains a `pyproject.toml`
with all Python dependencies; `uv` resolves them automatically — no manual `pip install` needed.

## Prerequisites

```
uv >= 0.4        # python package manager
terraform        # >= 1.5
kubectl          # configured against the target cluster
helm             # >= 3
aws CLI          # credentials in env or ~/.aws
confluent CLI    # CONFLUENT_CLOUD_API_KEY / CONFLUENT_CLOUD_API_SECRET in env or scripts/.env
```

---

## bootstrap.py — one-time setup

Creates the S3 bucket and DynamoDB table used as the Terraform state backend.
Run **once per AWS account** before the first `provision.py`.

```
uv run --project scripts scripts/bootstrap.py
```

Config is read from `infra/environments/shared.json`.
Override with env vars: `PLATFORM_TF_BUCKET`, `PLATFORM_TF_TABLE`, `AWS_DEFAULT_REGION`.

---

## provision.py — infrastructure + K8s pipeline

Runs the three Terraform pipelines (networking → platform → EKS), then installs and configures
all Kubernetes components (cert-manager, CFK operator, CSI Secrets Store driver, Connect CR).

```
uv run --project scripts scripts/provision.py --env dev
uv run --project scripts scripts/provision.py --env dev --dry-run
uv run --project scripts scripts/provision.py --env dev --skip-terraform
```

| Flag | Description |
|---|---|
| `--env` | Target environment (`dev` or `prod`). Required. |
| `--dry-run` | Validate config and prerequisites without applying anything. |
| `--skip-terraform` | Skip all three Terraform pipelines and re-run K8s steps only (uses existing TF outputs). |

---

## cluster_pipeline.py — cluster resources (in-VPC)

Provisions Kafka topics, ACLs, API keys, quotas, and Secrets Manager secrets via
`infra/cluster/` Terraform.

**Must run from inside the AWS VPC.** The Confluent provider validates cluster API keys against
the cluster REST endpoint, which resolves to a PrivateLink private IP unreachable from outside
the VPC. Use `--via-bastion` to automate this from your laptop.

See `docs/adr/ADR-010-cluster-pipeline-in-vpc.md` and `docs/adr/ADR-014-bastion-ssm-automation.md`.

### Phase 1 — initial apply

```
# Automated (from anywhere — launches + terminates a temporary EC2 bastion via SSM):
uv run --project scripts scripts/cluster_pipeline.py --env dev --via-bastion

# Manual (must run from inside the VPC):
uv run --project scripts scripts/cluster_pipeline.py --env dev

# Destroy (also requires in-VPC execution):
uv run --project scripts scripts/cluster_pipeline.py --env dev --via-bastion --destroy
```

Creates API keys, Secrets Manager secrets, topics, and ACLs.
Schema Registry is not activated (ESSENTIALS SR is lazily provisioned on first schema write).

### Phase 2 — activate Schema Registry

After the first schema has been registered (via a connector serialiser or `confluent schema create`):

```
uv run --project scripts scripts/cluster_pipeline.py --env dev --via-bastion --activate-sr
```

Then re-run provision to restore the `schemaRegistry` block in the Connect CR:

```
uv run --project scripts scripts/provision.py --env dev --skip-terraform
```

| Flag | Description |
|---|---|
| `--env` | Target environment (`dev` or `prod`). Required. |
| `--via-bastion` | Launch a temporary SSM-managed EC2 t3.micro in the VPC private subnet, run the pipeline on it, then terminate. Safe to call from a developer laptop. Requires the EKS pipeline to have been applied first (instance profile created by `infra/eks`). |
| `--activate-sr` | Phase 2: create SR API key + role binding and write SR secret. Works with or without `--via-bastion`. |
| `--destroy` | Destroy cluster pipeline resources (topics/ACLs/keys/secrets). Also requires in-VPC execution; combine with `--via-bastion` when running from outside the VPC. |
| `--yes` | Skip the VPC confirmation prompt. Set automatically by `--via-bastion` on the remote invocation. |

---

## status.py — live resource status

Checks every platform resource directly against AWS and Confluent APIs.
No Terraform state required.

```
uv run --project scripts scripts/status.py --env dev
uv run --project scripts scripts/status.py --env prod
```

Expected end state after a full destroy: all billing resources (EKS, NAT Gateways, PrivateLink
endpoint, Confluent cluster) show **PENDING**. S3 bucket + DynamoDB table + state file objects
showing **OK** is expected — negligible cost, retained for the next provision run.

---

## destroy.py — teardown

Tears down in reverse order: K8s resources → cluster pipeline → EKS → Confluent Cloud → networking.

```
# Full destroy
uv run --project scripts scripts/destroy.py --env dev
uv run --project scripts scripts/destroy.py --env dev --yes

# Cluster pipeline only — via bastion (safe from outside VPC)
uv run --project scripts scripts/destroy.py --env dev --cluster-only --via-bastion

# Cluster pipeline only — manual (must run from inside VPC)
uv run --project scripts scripts/destroy.py --env dev --cluster-only

# K8s resources only (leaves all Terraform infra intact)
uv run --project scripts scripts/destroy.py --env dev --k8s-only

# Full destroy including S3 + DynamoDB state backend (irreversible)
uv run --project scripts scripts/destroy.py --env dev --destroy-bootstrap
```

| Flag | Description |
|---|---|
| `--env` | Target environment (`dev` or `prod`). Required. |
| `--yes` | Skip confirmation prompts. |
| `--cluster-only` | Destroy cluster pipeline resources only (topics, ACLs, API keys, Secrets Manager secrets). K8s, EKS, and Confluent infra are not affected. Combine with `--via-bastion` when running from outside the VPC. |
| `--via-bastion` | Run the cluster pipeline destroy via a temporary SSM bastion in the VPC. Required when destroying from outside the VPC. Applies to the cluster pipeline step only; all other destroy steps run locally. |
| `--k8s-only` | Remove Kubernetes resources only; skip all Terraform destroy. |
| `--destroy-bootstrap` | Also delete the S3 bucket and DynamoDB table after everything else. Irreversible. |

---

## Typical workflows

### First provision

```sh
uv run --project scripts scripts/bootstrap.py
uv run --project scripts scripts/provision.py --env dev
uv run --project scripts scripts/cluster_pipeline.py --env dev --via-bastion
```

### Activate Schema Registry (after first schema written)

```sh
uv run --project scripts scripts/cluster_pipeline.py --env dev --via-bastion --activate-sr
uv run --project scripts scripts/provision.py --env dev --skip-terraform
```

### Cost check after destroy

```sh
uv run --project scripts scripts/status.py --env dev
```

### Full teardown

```sh
uv run --project scripts scripts/destroy.py --env dev --yes --via-bastion
uv run --project scripts scripts/status.py --env dev   # verify
```
