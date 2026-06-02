"""
Cluster pipeline: Confluent Cloud topics, ACLs, API keys, quotas, and secrets.

IMPORTANT — VPC REQUIREMENT:
  This script MUST run from inside the AWS VPC (bastion host, EKS job, or
  AWS CodeBuild in the private subnet). The Confluent Terraform provider
  validates each Kafka cluster API key by calling the cluster REST endpoint,
  which resolves to a PrivateLink private IP unreachable from outside the VPC.
  Running this from a developer laptop or CI runner outside the VPC will hang.

  ADR: docs/adr/ADR-010-cluster-pipeline-in-vpc.md

Two-phase apply:
  Phase 1 (default): API keys, Secrets Manager secrets, topics, ACLs, quotas.
    Schema Registry is NOT activated — SR on ESSENTIALS is lazily provisioned.
  Phase 2: Set schema_registry_active=true in cluster.tfvars.json after the
    first schema has been registered (connector serialiser or manual CLI).
    Re-run this script to create the SR API key and update Secrets Manager.
    Then re-run provision.py to activate the schemaRegistry block in Connect CR.

Usage:
    uv run --project scripts scripts/cluster_pipeline.py --env dev
    uv run --project scripts scripts/cluster_pipeline.py --env dev --activate-sr

Required env vars — same as provision.py (CONFLUENT_CLOUD_API_KEY / _SECRET).
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from rich.panel import Panel
from _util import (
    REPO_ROOT, Config, VALID_ENVS, console, step, ok, info, warn, die,
    check_tool, run,
    tf_init, tf_apply, tf_outputs,
)


def check_vpc_warning() -> None:
    """Emit a prominent VPC requirement warning and require acknowledgement."""
    console.print()
    console.print(Panel.fit(
        "[bold yellow]VPC REQUIREMENT[/]\n\n"
        "This pipeline must run from inside the AWS VPC.\n"
        "The Confluent provider validates API keys against the cluster REST\n"
        "endpoint, which resolves to a PrivateLink private IP.\n\n"
        "If you are on a bastion host or EKS job inside the VPC, continue.\n"
        "If you are on a developer laptop or external CI, this will hang.",
        title="⚠ In-VPC execution required",
        border_style="yellow",
    ))
    console.print()


def provision_cluster(cfg: Config, platform_out: dict, schema_registry_active: bool) -> dict:
    step("Applying cluster pipeline (infra/cluster)")

    env = cfg.cluster_tf_env(platform_out)

    # Overlay the schema_registry_active flag from the call argument so the
    # caller can pass --activate-sr without editing cluster.tfvars.json.
    if schema_registry_active:
        env["TF_VAR_schema_registry_active"] = "true"

    tf_init("infra/cluster", cfg, cfg.cluster_backend_key)
    tf_apply("infra/cluster", env)
    outputs = tf_outputs("infra/cluster", env)

    ok(f"terraform-manager key: {outputs.get('terraform_manager_kafka_key_id', 'n/a')}")
    ok(f"cfk-connect key:       {outputs.get('cfk_connect_kafka_key_id', 'n/a')}")
    ok(f"JAAS secret:           {outputs.get('jaas_secret_path', 'n/a')}")

    sr_endpoint = outputs.get("schema_registry_endpoint", "")
    if sr_endpoint:
        ok(f"Schema Registry:       {sr_endpoint}")
    else:
        info("Schema Registry not yet active (schema_registry_active=false)")
        info("Register first schema, then re-run with --activate-sr")

    return outputs


def activate_connect_sr(platform_out: dict, cluster_out: dict, cfg: Config) -> None:
    """Re-apply the Connect CR with the SR endpoint once SR is active."""
    sr_endpoint = cluster_out.get("schema_registry_endpoint", "")
    if not sr_endpoint:
        warn("No SR endpoint in cluster outputs — skipping Connect SR activation")
        return

    step("Activating Schema Registry block in Connect CR")
    info(f"SR endpoint: {sr_endpoint}")

    # Patch platform_out with the SR endpoint so apply_connect() can inject it.
    # apply_connect() is defined in provision.py — import and call it here to
    # avoid duplicating the Connect CR apply logic.
    from provision import apply_connect
    platform_out_with_sr = {**platform_out, "schema_registry_endpoint": sr_endpoint}

    # eks_out is needed for apply_connect; re-read from existing TF state.
    from _util import tf_init as _tf_init, tf_outputs as _tf_outputs
    tf_init("infra/networking", cfg, cfg.networking_backend_key)
    networking_out = _tf_outputs("infra/networking", cfg.networking_tf_env())
    tf_init("infra/eks", cfg, cfg.eks_backend_key)
    eks_out = _tf_outputs("infra/eks", cfg.eks_tf_env(networking_out))

    apply_connect(platform_out_with_sr, eks_out, cfg)
    ok("Connect CR updated with Schema Registry endpoint")


def print_summary(cluster_out: dict, schema_registry_active: bool) -> None:
    sr_line = cluster_out.get("schema_registry_endpoint") or "not yet active"
    console.print()
    console.print(Panel.fit(
        f"""[bold green]Cluster pipeline applied[/]

[bold]API Keys[/]
  terraform-manager : {cluster_out.get('terraform_manager_kafka_key_id', 'n/a')}
  cfk-connect       : {cluster_out.get('cfk_connect_kafka_key_id', 'n/a')}
  monitoring        : {cluster_out.get('monitoring_kafka_key_id', 'n/a')}

[bold]Schema Registry[/]
  Endpoint          : {sr_line}

[bold]Next steps[/]
  1. secret-sync pod will become Available now that cfk-connect-jaas exists
  2. Connect workers will authenticate to Confluent Cloud on next restart
  3. When first schema is registered → re-run with --activate-sr""",
        title="Summary",
    ))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", required=True, choices=VALID_ENVS,
                        help="Target environment")
    parser.add_argument("--activate-sr", action="store_true",
                        help="Phase 2: activate Schema Registry resources (after first schema registered)")
    parser.add_argument("--yes", action="store_true",
                        help="Skip VPC confirmation prompt")
    args = parser.parse_args()

    for tool in ["terraform", "aws"]:
        check_tool(tool)

    check_vpc_warning()

    if not args.yes:
        answer = input("Running from inside the VPC? Type 'yes' to continue: ").strip()
        if answer.lower() != "yes":
            console.print("[yellow]Aborted.[/]")
            sys.exit(0)

    cfg = Config.load(args.env)
    console.print(f"\n[bold]Cluster pipeline — environment:[/] [cyan]{args.env}[/]  "
                  f"({cfg.environment_name})\n")

    # Read infra pipeline outputs to feed as variables
    warn("Reading existing Terraform outputs from infra pipelines …")
    tf_init("infra/networking", cfg, cfg.networking_backend_key)
    networking_out = tf_outputs("infra/networking", cfg.networking_tf_env())

    tf_init("infra/platform", cfg, cfg.platform_backend_key)
    platform_out = tf_outputs("infra/platform", cfg.platform_tf_env(networking_out))

    cluster_out = provision_cluster(cfg, platform_out, schema_registry_active=args.activate_sr)

    if args.activate_sr and cluster_out.get("schema_registry_endpoint"):
        activate_connect_sr(platform_out, cluster_out, cfg)

    print_summary(cluster_out, schema_registry_active=args.activate_sr)


if __name__ == "__main__":
    main()
