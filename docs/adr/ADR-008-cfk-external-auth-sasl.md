# ADR-008: CFK → Confluent Cloud Auth via SASL/PLAIN over TLS

## Decision
CFK Connect workers authenticate to Confluent Cloud using SASL/PLAIN with API key credentials, delivered as a JAAS config string from AWS Secrets Manager. TLS encryption is always on (`tls.enabled: true`, `ignoreTrustStoreConfig: true` to use JVM default trust store for Confluent Cloud certificates).

## KB Source
`09-Security-Architecture/mtls-oauth.md` — mTLS support boundary table, Confluent Cloud vs self-managed
`09-Security-Architecture/private-networking.md` — Outbound connectivity for self-managed Connect

## Rationale
SASL/PLAIN with API key is the standard authentication path for Confluent Cloud Dedicated clusters. The KB documents that mTLS client auth on Confluent Cloud requires Certificate Identity Pools (a Dedicated-only feature) — this is a valid upgrade path but adds IdP integration complexity not needed at this stage.

`ignoreTrustStoreConfig: true` is correct: Confluent Cloud broker certificates are signed by a public CA (Let's Encrypt / DigiCert) already in the JVM default trust store. Providing a custom truststore would be redundant.

JAAS config is stored as a pre-assembled string in Secrets Manager (not username/password separately) because the CSI driver can mount it directly as `plain-jaas.conf` without any string assembly at runtime.

## Consequences
- API key rotation requires updating the Secrets Manager secret. CSI rotation polling (2-min interval) picks it up without pod restart.
- Upgrade path to OAuth/OIDC (Confluent Cloud Identity Pools) requires adding an Identity Pool to the cluster and updating the CFK `Connect` CR `authentication.type` — no networking changes required.
