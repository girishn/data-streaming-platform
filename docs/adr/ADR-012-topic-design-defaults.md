# ADR-012: Topic Naming Convention and Partition Sizing Defaults

## Decision
All platform topics use the naming convention `{domain}.{entity}.{event-type}.v{N}` — lowercase, dot-separated. Partition count is derived from the sizing formula with a 2–3× growth multiplier. Default retention is `delete` with `min.insync.replicas=2`. Broker-side schema validation is enabled on all platform topics.

## KB Source
`topic-design-framework.md` — naming convention, partition sizing formula, retention by type
`02-Broker-Infrastructure/partitioning-strategies.md` — sizing formula and practical bands
`10-Operational-Patterns/producer-onboarding.md` — Gate 1 checklist (naming, partition justification, retention)

## Naming Convention
```
{domain}.{entity}.{event-type}.v{N}
```
- **domain**: bounded context, not team name (e.g. `payments`, `orders`, `platform`)
- **event-type**: `events` for append-only, `state` for compacted — encodes retention semantics
- **v{N}**: schema major version (Avro/Protobuf breaking changes → new topic + version)
- Avoid encoding partition count or infrastructure details in the name — these change

## Partition Sizing
```
partitions = max(target_throughput / 10_MB_s, expected_max_consumers)
```
Apply a 2–3× growth multiplier. Partition count cannot be changed after topic creation without topic recreation (breaks `murmur2(key) mod N` routing for existing messages). Over-provision rather than under-provision.

**Practical bands:**
| Throughput | Range |
|---|---|
| < 10 MB/s | 3–6 |
| 10–100 MB/s | 6–30 |
| 100–500 MB/s | 30–100 |

**Example — platform.connect.dlq.v1:**
- Expected throughput: < 1 MB/s (error volume). Max concurrent replay consumers: 6.
- `partitions = max(1, 6) × 2 = 6`

## Retention
- `cleanup.policy = delete` for event streams (`events` suffix)
- `cleanup.policy = compact` for latest-value tables (`state` suffix)
- `cleanup.policy = compact,delete` for compacted topics with bounded history (add `retention.ms`)
- Blanket `delete` on reference data (state) topics is a design error

## Consequences
- New topics in the cluster pipeline must document their partition justification in a comment.
- Consumer onboarding gates (self-service pipeline) enforce the naming convention before provisioning ACLs.
- Schema validation (`confluent.value.schema.validation=true`) requires SR to be active; config is accepted but unenforced until SR is provisioned.
