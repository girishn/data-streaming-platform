# ADR-010: Cluster Pipeline Must Execute from Inside the VPC

## Decision
The cluster Terraform pipeline (`infra/cluster/`) is applied from a compute resource inside the AWS VPC (bastion host, EKS job, or AWS CodeBuild in the private subnet). It is not called from `provision.py` and cannot run from a developer laptop or external CI runner.

## KB Source
`10-Operational-Patterns/gitops-terraform.md` — two-pipeline model
Platform-state.md KB gap — Confluent TF provider Kafka API key sync for PrivateLink-only clusters

## Rationale
The Confluent Terraform provider validates each cluster-scoped API key after creation by calling the cluster REST endpoint. With `dns_config { resolution = "PRIVATE" }` on the Confluent network, that endpoint resolves to a PrivateLink private IP address — only reachable from within the VPC. From outside the VPC, the provider hangs indefinitely waiting for a response that never comes.

The same constraint applies to all cluster-level Terraform resources: topics, ACLs, and quotas are managed via the cluster REST API, which also requires in-VPC connectivity.

The infra pipeline (networking/platform/eks) has no such constraint — it calls Confluent Cloud's public API for environment, network, and cluster creation.

## Consequences
- `provision.py` installs and configures K8s components only; it does not call the cluster pipeline.
- `cluster_pipeline.py` is a separate script with an explicit VPC-requirement warning and interactive confirmation.
- In CI: the cluster pipeline job must run in a CodeBuild project placed in the private subnet, or via an EKS Job (which has in-VPC connectivity by definition).
- `destroy.py` includes cluster teardown (`destroy_cluster_pipeline`) but also warns about the VPC requirement.
