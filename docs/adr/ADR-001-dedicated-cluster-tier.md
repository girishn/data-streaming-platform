# ADR-001: Use Confluent Cloud Dedicated Cluster Tier

## Decision
Deploy a Dedicated cluster (MULTI_ZONE, 2 CKU minimum) rather than Basic or Standard.

## KB Source
`01-Core-Concepts/kafka-vs-confluent.md` — Cluster type capability matrix

## Rationale
Three hard requirements forced Dedicated:
1. **AWS PrivateLink** — only available on Dedicated. Required for private data-plane connectivity from EKS.
2. **Broker-side schema validation** — `confluent.value.schema.validation=true` on topics requires Dedicated.
3. **SASL/TLS with all client types** (CLAUDE.md requirement) — Dedicated supports mTLS via Certificate Identity Pools in addition to SASL/PLAIN and SASL/OAUTHBEARER. Basic/Standard do not support mTLS client auth.

## Consequences
- Higher base cost vs serverless tiers, but fixed capacity planning is appropriate for a platform.
- CKU count can be scaled up via Terraform without cluster recreation.
- Schema governance enforcement at the broker layer is available from day one.
