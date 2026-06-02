# ADR-011: CFK Connect Worker Permissions — ACLs for Internal Topics

## Decision
The CFK Connect worker service account (`cfk-connect`) is granted permissions via Kafka ACLs, not RBAC role bindings. ACLs cover the three Connect internal topics (`connect-configs`, `connect-offsets`, `connect-status`), the worker consumer group, and the platform DLQ topic. Per-connector topic access is added as connectors are onboarded via the self-service pipeline.

## KB Source
`09-Security-Architecture/rbac.md` — "Self-managed Kafka Connect connector ACLs: use ACL — connector worker service account needs specific ACL operations"
`05-Enterprise-Connect/managed-connectors.md` — worker internal topics: `connect-configs`, `connect-offsets`, `connect-status`; workers share `group.id` for task rebalancing

## Rationale
The KB explicitly categorises self-managed Connect as an ACL case, not RBAC. RBAC roles in Confluent Cloud bundle higher-level permissions and do not have a resource type for transactional IDs or the precise per-operation grants that Connect workers need on internal topics. ACLs provide exact control per resource/operation.

### [KB_GAP: Kafka Connect worker required ACL operations per resource type]
The KB confirms ACLs are required and names the internal topics and worker group, but does not document the exact operation set (READ/WRITE/CREATE/DESCRIBE/DELETE) per resource type. The `infra/cluster/acls.tf` implements READ/WRITE/DESCRIBE on the three internal topics and READ on the worker group as a starting set. This set must be validated against Confluent's Connect worker ACL documentation before a production apply.

## Consequences
- Each connector that is onboarded adds a separate WRITE ACL on its target topic for the `cfk-connect` service account.
- The consumer group for source connectors gets a READ ACL at onboarding time.
- The worker group.id (`connect`) must match the CFK Connect CR name — verify with `kubectl describe connect connect -n confluent`.
