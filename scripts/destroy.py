"""
End-to-end platform destruction script.
Tears down in reverse order: K8s resources → EKS → Confluent Cloud.

Usage:
    uv run --project scripts scripts/destroy.py [--yes] [--destroy-bootstrap]

Required env vars — same as provision.py.
"""

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from rich.panel import Panel
from _util import (
    REPO_ROOT, Config, VALID_ENVS, console, step, ok, info, warn, die,
    check_tool, run,
    tf_init, tf_destroy, tf_outputs,
    kubectl_delete,
)


def confirm(msg: str, yes: bool) -> None:
    if yes:
        return
    console.print(f"\n[bold yellow]{msg}[/]")
    answer = input("Type 'yes' to continue: ").strip()
    if answer != "yes":
        console.print("[yellow]Aborted.[/]")
        sys.exit(0)


def delete_connect() -> None:
    step("Deleting CFK Connect workers")
    for manifest in [
        "kubernetes/connect/connect.yaml",
        "kubernetes/connect/secret-sync.yaml",
        "kubernetes/connect/secret-provider-class.yaml",
        "kubernetes/connect/service-account.yaml",
    ]:
        path = REPO_ROOT / manifest
        if path.exists():
            kubectl_delete(path.read_text())
            ok(manifest)

    # Wait for Connect pods to terminate before destroying infra
    info("Waiting for Connect pods to terminate …")
    run(
        ["kubectl", "wait", "--for=delete",
         "pod", "-l", "app=connect",
         "-n", "confluent", "--timeout=120s"],
        check=False,
    )


def delete_cert_issuers() -> None:
    step("Deleting cert-manager issuers")
    kubectl_delete(
        (REPO_ROOT / "kubernetes/cert-manager/cluster-issuer.yaml").read_text()
    )
    ok("Issuers deleted")


def uninstall_helm(release: str, namespace: str) -> None:
    info(f"helm uninstall {release}  (namespace: {namespace})")
    run(
        ["helm", "uninstall", release, "--namespace", namespace, "--wait"],
        check=False,
    )


def delete_k8s_infrastructure() -> None:
    step("Uninstalling Kubernetes platform components")
    uninstall_helm("confluent-operator", "confluent")
    uninstall_helm("secrets-provider-aws", "kube-system")
    uninstall_helm("csi-secrets-store", "kube-system")
    uninstall_helm("cert-manager", "cert-manager")

    # Delete namespaces last — may take time due to finalizers
    for ns in ["confluent", "cert-manager"]:
        info(f"Deleting namespace: {ns}")
        run(["kubectl", "delete", "namespace", ns, "--ignore-not-found=true",
             "--timeout=120s"], check=False)
    ok("Kubernetes infrastructure removed")


def destroy_cluster_pipeline(cfg: Config, platform_out: dict, via_bastion: bool = False) -> None:
    step("Destroying cluster pipeline resources (topics, ACLs, API keys, secrets)")
    if not platform_out.get("cluster_id"):
        warn("Platform outputs unavailable (state already destroyed) — skipping cluster pipeline destroy")
        return
    if via_bastion:
        from cluster_pipeline import run_via_bastion
        run_via_bastion(cfg, activate_sr=False, destroy=True)
        return
    warn("This must run from inside the VPC — cluster REST endpoint is PrivateLink-only.")
    warn("Use --via-bastion if running from outside the VPC.")
    tf_init("infra/cluster", cfg, cfg.cluster_backend_key)
    tf_destroy("infra/cluster", cfg.cluster_tf_env(platform_out))
    ok("Cluster pipeline resources destroyed")


def destroy_eks(cfg: Config, networking_out: dict) -> None:
    step("Destroying EKS cluster")
    tf_init("infra/eks", cfg, cfg.eks_backend_key)
    tf_destroy("infra/eks", cfg.eks_tf_env(networking_out))
    ok("EKS destroyed")


def destroy_platform(cfg: Config, networking_out: dict) -> None:
    step("Destroying Confluent Cloud infrastructure")
    tf_init("infra/platform", cfg, cfg.platform_backend_key)
    tf_destroy("infra/platform", cfg.platform_tf_env(networking_out))
    ok("Confluent Cloud infrastructure destroyed")


def destroy_networking(cfg: Config) -> None:
    step("Destroying VPC and networking")
    tf_init("infra/networking", cfg, cfg.networking_backend_key)
    tf_destroy("infra/networking", cfg.networking_tf_env())
    ok("Networking destroyed")


def destroy_bootstrap(cfg: Config) -> None:
    step("Destroying Terraform state backend (S3 + DynamoDB)")
    warn("This will delete all Terraform state. This is irreversible.")
    confirm("Destroy the S3 bucket and DynamoDB table?", yes=False)

    import boto3
    session = boto3.Session(region_name=cfg.aws_region)
    s3 = session.client("s3")
    ddb = session.client("dynamodb")

    # Empty and delete the bucket
    info(f"Emptying s3://{cfg.tf_bucket} …")
    paginator = s3.get_paginator("list_object_versions")
    for page in paginator.paginate(Bucket=cfg.tf_bucket):
        objects = [
            {"Key": obj["Key"], "VersionId": obj["VersionId"]}
            for obj in page.get("Versions", []) + page.get("DeleteMarkers", [])
        ]
        if objects:
            s3.delete_objects(Bucket=cfg.tf_bucket, Delete={"Objects": objects})
    s3.delete_bucket(Bucket=cfg.tf_bucket)
    ok(f"Bucket deleted: {cfg.tf_bucket}")

    info(f"Deleting DynamoDB table: {cfg.tf_table} …")
    ddb.delete_table(TableName=cfg.tf_table)
    ok(f"Table deleted: {cfg.tf_table}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", required=True, choices=VALID_ENVS,
                        help="Target environment")
    parser.add_argument("--yes", action="store_true",
                        help="Skip confirmation prompts")
    parser.add_argument("--destroy-bootstrap", action="store_true",
                        help="Also destroy the S3 bucket and DynamoDB table (irreversible)")
    parser.add_argument("--k8s-only", action="store_true",
                        help="Only remove Kubernetes resources, skip Terraform destroy")
    parser.add_argument("--cluster-only", action="store_true",
                        help="Only destroy cluster pipeline resources (topics/ACLs/keys/secrets). "
                             "Must run from inside the VPC or with --via-bastion.")
    parser.add_argument("--via-bastion", action="store_true",
                        help="Run the cluster pipeline destroy from a temporary SSM bastion in the "
                             "VPC. Required when destroying from outside the VPC. Applies to the "
                             "cluster pipeline step only.")
    args = parser.parse_args()

    for tool in ["terraform", "kubectl", "helm", "aws"]:
        check_tool(tool)

    cfg = Config.load(args.env)
    console.print(f"\n[bold]Target environment:[/] [cyan]{args.env}[/]  "
                  f"({cfg.environment_name})\n")

    if args.cluster_only:
        console.print(Panel.fit(
            "[bold red]This will destroy cluster pipeline resources only.[/]\n\n"
            "Topics, ACLs, API keys, and Secrets Manager secrets will be deleted.\n"
            "Topic data and consumer group offsets will be permanently lost.\n"
            "K8s, EKS, and Confluent Cloud infrastructure are NOT affected.",
            title="⚠ Destructive Operation",
        ))
        confirm("Destroy cluster pipeline resources?", yes=args.yes)
        tf_init("infra/networking", cfg, cfg.networking_backend_key)
        networking_out = tf_outputs("infra/networking", cfg.networking_tf_env())
        tf_init("infra/platform", cfg, cfg.platform_backend_key)
        platform_out = tf_outputs("infra/platform", cfg.platform_tf_env(networking_out))
        destroy_cluster_pipeline(cfg, platform_out, via_bastion=args.via_bastion)
        console.print()
        console.rule("[bold green]Cluster pipeline destroyed[/]")
        return

    console.print(Panel.fit(
        "[bold red]This will destroy the entire data streaming platform.[/]\n\n"
        "All Confluent Cloud resources, EKS cluster, networking, and API keys will be deleted.\n"
        "Topic data, schemas, and consumer group offsets will be permanently lost.",
        title="⚠ Destructive Operation",
    ))
    confirm("Destroy the platform?", yes=args.yes)

    delete_connect()
    delete_cert_issuers()
    delete_k8s_infrastructure()

    if not args.k8s_only:
        # Read networking + platform outputs to feed downstream destroy envs
        tf_init("infra/networking", cfg, cfg.networking_backend_key)
        networking_out = tf_outputs("infra/networking", cfg.networking_tf_env())

        tf_init("infra/platform", cfg, cfg.platform_backend_key)
        platform_out = tf_outputs("infra/platform", cfg.platform_tf_env(networking_out))

        # Cluster resources (topics/ACLs/keys) must be destroyed before the cluster itself
        destroy_cluster_pipeline(cfg, platform_out, via_bastion=args.via_bastion)
        destroy_eks(cfg, networking_out)
        destroy_platform(cfg, networking_out)
        destroy_networking(cfg)  # last — platform owns PrivateLink ENIs bound to the VPC

    if args.destroy_bootstrap:
        destroy_bootstrap(cfg)

    console.print()
    console.rule("[bold green]Destroy complete[/]")


if __name__ == "__main__":
    main()
