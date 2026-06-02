# Platform State

## Build Phase
**Infrastructure Pipeline** — Complete. Confluent Cloud base + EKS Terraform applied. cert-manager, CFK operator, CSI Secrets Store driver all running. Connect CR applied (SR block stripped — awaiting cluster pipeline). secret-sync pod deployed (pending JAAS secret from cluster pipeline).

**Cluster Pipeline** — `infra/cluster/` Terraform written. Awaiting first apply from inside the VPC. Must run via `scripts/cluster_pipeline.py` (not provision.py). Phase 1 (default): API keys + secrets + topics + ACLs + quotas. Phase 2 (`--activate-sr`): SR API key + role binding, after first schema registration.

## Decisions Made

| Decision | Choice | KB Source |
|---|---|---|
| Cluster type | Dedicated (MULTI_ZONE, 2 CKU) | `01-Core-Concepts/kafka-vs-confluent.md` — Dedicated required for PrivateLink + broker-side schema validation |
| Networking | AWS PrivateLink + Route 53 PHZ | `09-Security-Architecture/private-networking.md` — preferred for new AWS deployments |
| Terraform model | Two-pipeline (infra / cluster) | `10-Operational-Patterns/gitops-terraform.md` |
| Platform service accounts | terraform-manager (CloudClusterAdmin), cfk-connect, monitoring (MetricsViewer) | `09-Security-Architecture/rbac.md` |
| API key storage | AWS Secrets Manager | `10-Operational-Patterns/gitops-terraform.md` — CSI Secrets Provider pattern |
| Schema Registry | Confluent Cloud managed, ESSENTIALS package | `10-Operational-Patterns/gitops-terraform.md` |
| CFK internal auth | mTLS via cert-manager + cfk-ca-issuer | `09-Security-Architecture/mtls-oauth.md` — separate internal/external auth paths |
| CFK → Confluent Cloud auth | SASL/PLAIN over TLS, API key from Secrets Manager via CSI | `09-Security-Architecture/mtls-oauth.md` + `10-Operational-Patterns/gitops-terraform.md` |
| IRSA | cfk-connect + csi-secrets-store ServiceAccounts annotated | CLAUDE.md requirement — IRSA everywhere |
| EKS | Private endpoint only, managed node group m6i.xlarge, 2–6 nodes | Generic AWS Terraform (no KB query required per CLAUDE.md) |
| Cluster pipeline execution | In-VPC only (bastion/EKS job/CodeBuild) | `10-Operational-Patterns/gitops-terraform.md` + KB gap — PrivateLink REST endpoint validation |
| Connect worker permissions | ACLs (not RBAC) on internal topics + group | `09-Security-Architecture/rbac.md` — self-managed Connect uses ACLs |
| Topic naming | `{domain}.{entity}.{event-type}.v{N}` | `topic-design-framework.md` — lowercase dot-separated |
| Partition sizing | `max(throughput/10MB_s, max_consumers) × 2–3×` | `02-Broker-Infrastructure/partitioning-strategies.md` |
| SR activation | Two-phase: Phase 1 no SR, Phase 2 `schema_registry_active=true` after first schema | KB gap — ESSENTIALS lazy provisioning; `ADR-013` |
| Default quota floor | 10 MB/s ingress + egress per principal `(*,*)` | `13-Performance-Tuning/quota-management.md` |

## Open / Blocked Decisions
- **Cluster pipeline apply** — `infra/cluster/` written; awaiting first apply from inside VPC. Unblocks: secret-sync pod, Connect worker auth, SR activation path.
- **[KB_GAP] Connect ACL operations** — exact READ/WRITE/CREATE/DESCRIBE set per resource type for Connect worker not confirmed by KB. `acls.tf` implements READ/WRITE/DESCRIBE as starting set; validate against Confluent docs before production apply.
- **quota default resolved** — `principals = []` rejected by provider (minimum 1). Workaround: per-SA quota resources for the three platform accounts. New onboarded SAs get quota added at self-service time.
- **SR Phase 2** — pending first schema registration; then `--activate-sr` re-run.
- **Self-service pipeline** (`self-service/`) — OPA policies, onboarding gates. Not started.

## KB Gaps
- `confluent_schema_registry_cluster resource vs data source in Confluent TF provider v2.x` — KB has no guidance on which TF resource/data-source type to use for Schema Registry in provider v2.x. Fixed empirically: provider v2.x auto-provisions SR via `stream_governance` on the environment; `confluent_schema_registry_cluster` is now a data source, not a resource. `confluent_schema_registry_region` data source was removed entirely.
- `Confluent Cloud network zones parameter format for ap-southeast-2` — KB has no guidance on the zone identifier format for `confluent_network.zones`. AWS AZ names (`ap-southeast-2a`) are rejected ("zone(s) are invalid"). Fix: removed `zones` from `confluent_network`; let Confluent choose zones automatically. VPC endpoint uses all private subnet IDs so ENIs are created in whatever AZs the endpoint service supports.
- `Confluent ESSENTIALS Schema Registry lazy provisioning` — `stream_governance { package = "ESSENTIALS" }` on `confluent_environment` sets the billing package only; SR cluster is NOT created until the first schema is registered (lazy). Any data source read before that loops forever. Fix: all SR resources removed from infra pipeline entirely. SR data source, SR role binding (`ResourceOwner`), SR API key, SR Secrets Manager entry, and SR outputs all moved to cluster pipeline scope. `provision.py` SR URL injection is now a no-op if output absent.
- `Confluent Dedicated SINGLE_ZONE vs MULTI_ZONE for non-production environments` — KB has no guidance. MULTI_ZONE Dedicated requires minimum 2 CKUs; SINGLE_ZONE allows 1 CKU. PrivateLink works on SINGLE_ZONE Dedicated. Decision: dev uses SINGLE_ZONE + 1 CKU (cost saving); prod uses MULTI_ZONE + 2 CKU. `cluster_availability` added as per-env variable.
- `Confluent TF provider Kafka API key sync for PrivateLink-only clusters` — After creating a cluster-scoped API key, the Confluent TF provider validates it by calling the cluster REST endpoint. With `dns_config { resolution = "PRIVATE" }`, that endpoint resolves to the PrivateLink private IP — unreachable from outside the VPC. No provider flag to skip this check. Fix: removed all cluster-scoped API keys from infra pipeline. They are created in the cluster pipeline which runs from inside the VPC. Secrets Manager secrets also moved to cluster pipeline.

## Next Session Start Point
1. Run `list_topics()` + read this file.
2. Next build options (choose one):
   a. **Apply cluster pipeline from inside VPC** — `scripts/cluster_pipeline.py --env dev`. Validates ACL operations before apply (KB_GAP above must be resolved).
   b. **Self-service pipeline** (`self-service/`) — OPA conftest policies, producer/consumer/connector onboarding gates.
3. After cluster pipeline Phase 1: Connect workers authenticate, secret-sync pod becomes Available.
4. After first schema registered: `cluster_pipeline.py --env dev --activate-sr`, then `provision.py --env dev --skip-terraform` to restore SR block in Connect CR.
