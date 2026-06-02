# ADR-002: AWS PrivateLink for Confluent Cloud Connectivity

## Decision
Use AWS PrivateLink (VPC Interface Endpoint) to connect EKS workloads to the Confluent Cloud data plane. DNS resolution via Route 53 Private Hosted Zone.

## KB Source
`09-Security-Architecture/private-networking.md` — Networking options by cloud, PrivateLink vs VPC Peering decision table

## Rationale
KB explicitly recommends PrivateLink as the default for new AWS deployments:
- **One-way connection model** — Confluent-managed infrastructure cannot initiate connections into the VPC. VPC Peering is bidirectional.
- **No CIDR management** — no risk of overlapping CIDR blocks across peered VPCs.
- **No route table changes** — the endpoint appears in the VPC address space transparently.

Route 53 PHZ is required because broker hostnames resolve to public Confluent IPs by default. The PHZ overrides resolution with CNAME records pointing to the endpoint's private DNS name.

## Consequences
- One VPC endpoint + one Route 53 PHZ per environment.
- Zonal DNS records required for per-broker connections (added alongside wildcard record).
- Control plane traffic (Confluent CLI, Console, Terraform provider REST calls) still exits to the internet — this is expected per KB data plane vs control plane separation.
