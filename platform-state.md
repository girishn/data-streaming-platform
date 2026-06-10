# Platform State

## Build Phase
**Infrastructure Pipeline** — Complete. Networking + Confluent Cloud + EKS Terraform all applied.
cert-manager, CFK operator (v1), CSI Secrets Store driver (with tokenRequests fixed) all running.

**Cluster Pipeline** — Phase 1 applied successfully (topics, ACLs, API keys, JAAS secret written to Secrets Manager).
Cluster pipeline is idempotent: pre-flight step force-deletes scheduled-deletion secrets before apply.

**K8s / Connect** — CFK Connect CR applied. Workers were coming up at end of session; destroy running now.
Connect auth uses `jaasConfigPassThrough` (full JAAS string from Secrets Manager, not username= format).
CA secret `ca-pair-sslcerts` created by cert-manager (cfk-ca Certificate).

**Current status** — `destroy.py --env dev --yes --via-bastion` running at end of session (2026-06-10).

## Decisions Made

| Decision | Choice | KB Source |
|---|---|---|
| Cluster type | Dedicated (SINGLE_ZONE, 1 CKU dev / MULTI_ZONE 2 CKU prod) | `01-Core-Concepts/kafka-vs-confluent.md` |
| Networking | AWS PrivateLink + Route 53 PHZ | `09-Security-Architecture/private-networking.md` |
| Terraform model | Two-pipeline (infra / cluster) | `10-Operational-Patterns/gitops-terraform.md` |
| Platform service accounts | terraform-manager (CloudClusterAdmin), cfk-connect, monitoring (MetricsViewer) | `09-Security-Architecture/rbac.md` |
| API key storage | AWS Secrets Manager | `10-Operational-Patterns/gitops-terraform.md` — CSI Secrets Provider pattern |
| Schema Registry | Confluent Cloud managed, ESSENTIALS package | `10-Operational-Patterns/gitops-terraform.md` |
| CFK internal auth | mTLS via cert-manager + cfk-ca-issuer; CA secret = `ca-pair-sslcerts` | `09-Security-Architecture/mtls-oauth.md` |
| CFK → Confluent Cloud auth | SASL/PLAIN, full JAAS string via `jaasConfigPassThrough.secretRef`, key=`plain.txt` | `09-Security-Architecture/mtls-oauth.md` |
| IRSA | cfk-connect + csi-secrets-store ServiceAccounts annotated | CLAUDE.md requirement |
| EKS | Private endpoint only, managed node group m6i.xlarge, 2–6 nodes | Generic AWS Terraform |
| Cluster pipeline execution | In-VPC only via SSM bastion | `10-Operational-Patterns/gitops-terraform.md` |
| Bastion automation | SSM (no SSH), private subnet, ephemeral SM secret under `/{env}/pipeline/` | ADR-014 |
| Connect internal topic ACLs | CREATE + READ + WRITE + DESCRIBE on connect-configs/offsets/status | inferred — KB_GAP partially resolved |
| Connect consumer group ACL | READ on group `connect` (= CFK CR name) | inferred from CFK CR name |
| Connect exactly-once | `exactly.once.source.enabled=true` in configOverrides | confirmed required for Debezium |
| Connect transactional ID ACLs | WRITE + DESCRIBE on TRANSACTIONAL_ID `connect` (PREFIXED) | required for exactly-once source |
| Connector topic ACLs | Added at connector deploy time via self-service pipeline (not in acls.tf) | architecture decision |
| Topic auto-creation | Off (Confluent Dedicated default); topics created topic-first via self-service | governance decision |
| Topic naming | `{domain}.{entity}.{event-type}.v{N}` | `topic-design-framework.md` |
| Partition sizing | `max(throughput/10MB_s, max_consumers) × 2–3×` | `02-Broker-Infrastructure/partitioning-strategies.md` |
| SR activation | Two-phase: Phase 1 no SR, Phase 2 `--activate-sr` after first schema | ADR-013 |
| Provision/destroy parallelism | infra/platform + infra/eks run in parallel (both only need networking_out) | code decision |

## Open / Blocked Decisions
- **[KB_GAP] Connect ACL operations** — partially resolved. CREATE/READ/WRITE/DESCRIBE confirmed for internal topics; DESCRIBE_CONFIGS unconfirmed (probably not needed without broker-side config reads). Monitor Connect worker startup logs next provision for ACL errors.
- **[KB_GAP] confluent_kafka_client_quota principal format** — provider 2.73.0 returns 400 on valid sa-xxx principals. Quota resources disabled in `infra/cluster/quotas.tf`. Re-enable once provider bug is resolved.
- **SR Phase 2** — pending first schema registration; then `cluster_pipeline.py --env dev --via-bastion --activate-sr`.
- **Self-service pipeline** (`self-service/`) — OPA policies, onboarding gates. Not started.
- **Connect workers fully validated** — destroy interrupted validation. Next provision: confirm workers reach Running state and show successful broker connection in logs.

## KB Gaps
- `confluent_schema_registry_cluster resource vs data source in Confluent TF provider v2.x` — Fixed empirically: provider v2.x auto-provisions SR via `stream_governance`; `confluent_schema_registry_cluster` is a data source, not a resource.
- `Confluent Cloud network zones parameter format for ap-southeast-2` — Removed `zones` from `confluent_network`; let Confluent choose zones automatically.
- `Confluent ESSENTIALS Schema Registry lazy provisioning` — SR not created until first schema registered. All SR resources moved to cluster pipeline scope (Phase 2).
- `Confluent Dedicated SINGLE_ZONE vs MULTI_ZONE for non-production` — dev uses SINGLE_ZONE + 1 CKU; prod uses MULTI_ZONE + 2 CKU.
- `Confluent TF provider Kafka API key sync for PrivateLink-only clusters` — cluster-scoped keys moved to cluster pipeline (runs in-VPC).
- `confluent_kafka_client_quota principal format in provider 2.73.0` — 400 Bad Request on valid sa-xxx principals. Quota resources disabled.

## Known Fixes Applied (do not re-investigate)
- CSI driver: `tokenRequests: [{audience: sts.amazonaws.com}]` required in values.yaml for IRSA
- CFK CA secret must be named `ca-pair-sslcerts` (cert-manager Certificate secretName + Issuer ca.secretName)
- `SecretProviderClass` key must be `plain.txt` (not `plain-jaas.conf`) for CFK auth
- Connect CR must use `jaasConfigPassThrough.secretRef` (not `jaasConfig.secretRef`) — JAAS string format, not username= format
- Bastion IAM: `secretsmanager:RestoreSecret` added to ClusterSecretsManage statement
- Cluster pipeline pre-flight: uses `DescribeSecret` on known paths (not `ListSecrets`) to purge scheduled-deletion secrets

## Next Session Start Point
1. Run `list_topics()` + read this file.
2. Run `uv run --project scripts scripts/provision.py --env dev` (full provision — networking+platform+EKS applied fresh).
3. Run `uv run --project scripts scripts/cluster_pipeline.py --env dev --via-bastion`.
4. Verify Connect workers reach Running state: `kubectl get pod -n confluent` + `kubectl logs -n confluent -l app=connect --tail=50`.
5. Once Connect workers healthy — start **self-service pipeline** (`self-service/`): OPA conftest policies, producer/consumer/connector onboarding gates.
6. SR Phase 2 after first connector + schema registered: `cluster_pipeline.py --env dev --via-bastion --activate-sr` → `provision.py --env dev --skip-terraform`.
