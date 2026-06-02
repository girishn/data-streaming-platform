# ADR-006: Confluent Cloud Managed Schema Registry (ESSENTIALS)

## Decision
Use Confluent Cloud's managed Schema Registry (Stream Governance ESSENTIALS package) co-located in the same environment as the Kafka cluster, rather than deploying CFK-managed Schema Registry on EKS.

## KB Source
`10-Operational-Patterns/gitops-terraform.md` — Terraform provider SR resource pattern
`08-Stream-Governance/schema-evolution.md` — Compatibility modes and registry practices

## Rationale
- **Operational simplicity** — no SR pods to manage, scale, or back up. Confluent manages HA and durability.
- **Co-location** — SR in the same Confluent Cloud environment as the cluster avoids cross-cluster schema lookups and latency.
- **ESSENTIALS is sufficient** — stream catalog, stream lineage, and data contracts are available at ESSENTIALS tier. ADVANCED adds Business Metadata and Tag Propagation, which is not needed at this stage.
- **CFK SR on EKS** would require managing certificates, storage, scaling, and backup — adding operational burden for no gain at this platform maturity.

## Consequences
- SR endpoint is HTTPS (port 443) — handled by the `ignoreTrustStoreConfig: true` flag in CFK Connect dependencies (uses JVM default trust store for Confluent Cloud certs).
- Schema subjects are Terraform-managed in the cluster pipeline.
- Upgrading to ADVANCED tier later is an in-place change to the `confluent_schema_registry_cluster` resource.
