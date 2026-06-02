# ADR-005: API Keys Stored in AWS Secrets Manager, Injected via CSI

## Decision
All Confluent Cloud API keys are stored in AWS Secrets Manager at `/{env}/confluent/{name}` and injected into pods at startup via the CSI Secrets Store driver. Keys are never stored in Kubernetes Secrets directly or in git.

## KB Source
`10-Operational-Patterns/gitops-terraform.md` — CSI SecretProviderClass pattern, credentials-in-git anti-pattern
`10-Operational-Patterns/connector-onboarding.md` — Gate 4: Credential injection checklist

## Rationale
- KB explicitly states credentials must not appear in connector config files, git repos, or Kubernetes Secrets in plaintext.
- CSI Secrets Store driver mounts secrets as volumes and optionally syncs to Kubernetes Secrets (required for CFK `secretRef` pattern).
- IRSA on the Connect ServiceAccount means credential access is scoped to the specific pod identity — no long-lived static credentials on nodes.
- `syncSecret: enabled` + `enableSecretRotation: true` in the CSI driver config means rotated secrets in SM are picked up within 2 minutes without a pod restart.

## Consequences
- CSI Secrets Store driver must be deployed before Connect workers start.
- Secret rotation requires validating that CFK picks up the new value within the poll interval without connection disruption.
- Each environment has a separate secret path prefix (`/prod/confluent/` vs `/staging/confluent/`).
