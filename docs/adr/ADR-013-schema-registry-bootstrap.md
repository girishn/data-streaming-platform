# ADR-013: Schema Registry Lazy Provisioning — Two-Phase Activation

## Decision
Schema Registry resources (SR API key, role binding, Secrets Manager entry) are gated behind a `schema_registry_active` Terraform variable. The cluster pipeline is applied in two phases: Phase 1 without SR (default), Phase 2 with `schema_registry_active=true` after SR has been activated by the first schema registration.

## KB Source
Platform-state.md KB gap — Confluent ESSENTIALS SR lazy provisioning

## Rationale
Confluent Cloud ESSENTIALS Schema Registry is lazily provisioned: the SR cluster does not exist until the first schema is registered. Reading the `confluent_schema_registry_cluster` data source before SR exists causes the Confluent Terraform provider to poll the API indefinitely.

The `confluent_schema_registry_cluster` resource was removed from provider v2.x; it is now a data source only. The SR API key and role binding depend on this data source's output (`id`, `resource_name`, `rest_endpoint`), so all SR resources are gated behind `schema_registry_active`.

## Activation sequence
1. **Phase 1**: Apply `infra/cluster` with `schema_registry_active=false` (default).
   API keys, Secrets Manager secrets, topics, and ACLs are created. Connect workers start connecting to the cluster.
2. **SR activation**: A connector's Avro/Protobuf serialiser registers the first schema on first produce, OR the platform team registers a schema manually via the Confluent CLI.
3. **Phase 2**: Set `schema_registry_active=true` in `infra/environments/{env}/cluster.tfvars.json` and re-run:
   ```bash
   scripts/cluster_pipeline.py --env <env> --activate-sr
   ```
   This creates the SR API key, role binding, and Secrets Manager entry.
4. **Connect SR activation**: Re-run `provision.py --skip-terraform` to restore the `schemaRegistry` block in `connect.yaml` (provision.py strips it when SR endpoint is empty).

## Consequences
- Connect workers can start writing data before SR is active — topics with `confluent.value.schema.validation=true` defer enforcement until SR exists.
- The platform DLQ topic has schema validation enabled; messages without a schema will fail validation once SR is active, which is the desired behaviour for that topic.
- `schema_registry_active = false` must be the committed default in tfvars.json until SR is intentionally activated.
