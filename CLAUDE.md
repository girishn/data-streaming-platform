# CLAUDE.md — E2E Data Streaming Platform

## Stack (fixed — do not re-evaluate)
AWS · Kubernetes · Confluent Cloud + CFK (Kafka + Connect workers) · Flink · Debezium · Confluent Schema Registry
Region: `ap-southeast-2` · Terraform state: S3 + DynamoDB · IRSA everywhere · SASL/TLS all Kafka clients

## MCP Knowledge Base
Tools: `list_topics()` · `search_knowledge_base(query)`

**Session start:** call `list_topics()`, then read `./platform-state.md`.

**Query before any decision in:** architecture/topology · Kafka/Confluent config · Flink patterns · Debezium/CDC · schema evolution · CFK Connect deployment · exactly-once semantics · event mesh · self-service platform design · multi-tenancy · partition/consumer group strategy

**Do not query for:** generic K8s/Terraform/IaC syntax · AWS IAM/networking · language boilerplate · CI/CD

**Query discipline:** be specific (`"Flink checkpointing for exactly-once Kafka sink"` not `"Flink Kafka"`). Empty result = gap. Do not broaden until something returns.

## Gap Policy
No KB result for a streaming decision → emit `[KB_GAP: <topic>]` inline, halt that decision, continue other work. Never substitute training knowledge or web search for a streaming architecture decision.

End of session: append all gaps to `./platform-state.md`.

## platform-state.md (auto-maintain)
Keep current: build phase · decisions made (with KB topic) · open/blocked decisions · KB gaps · next session start point.

## Repo Layout
```
infra/          # Terraform
kubernetes/     # CFK, Flink operator manifests
connectors/     # Debezium + KafkaConnector CRs
flink-jobs/     # Flink application code
schema/         # Avro/Protobuf + registry config
self-service/   # Topic provisioning, platform API
docs/adr/       # One ADR per streaming decision (decision · KB source · rationale)
```
