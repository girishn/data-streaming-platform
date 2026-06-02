# ADR-004: Three Platform-Level Service Accounts with RBAC

## Decision
Create three platform-level Confluent service accounts in the infrastructure pipeline:
- `terraform-manager` — CloudClusterAdmin on the cluster; ResourceOwner on Schema Registry
- `cfk-connect` — no topic grants at creation; topic-level DeveloperRead/DeveloperWrite added per connector in the cluster pipeline
- `monitoring` — MetricsViewer at org scope

Application-level service accounts (per team, per connector) are provisioned in the cluster pipeline, not here.

## KB Source
`09-Security-Architecture/rbac.md` — Role taxonomy, role binding patterns
`10-Operational-Patterns/gitops-terraform.md` — Two-pipeline model, authorization layer

## Rationale
- **Separation of platform vs application identities** — platform accounts are long-lived and managed by the platform team. Application accounts are per-team and managed via the self-service GitOps pipeline.
- **Least privilege** — `cfk-connect` gets no topic grants at the platform level. Grants are added in the cluster pipeline when a connector is onboarded. This prevents the Connect worker from accessing topics it doesn't own.
- **MetricsViewer at org scope** — required for the Metrics API to enumerate all cluster resources for monitoring (Datadog integration pattern from KB).

## Consequences
- The cluster pipeline Terraform runs need the `terraform-manager` API key from Secrets Manager.
- Per-connector RBAC bindings are part of the connector onboarding gate (to be built in `self-service/`).
