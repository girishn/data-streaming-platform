"""
End-to-end platform provisioning script.
Runs Terraform for Confluent Cloud + EKS, then installs CFK + cert-manager + CSI driver.

Usage:
    uv run --project scripts scripts/provision.py [--dry-run]

Required env vars — see scripts/bootstrap.py for the full list.
"""

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from rich.panel import Panel
from _util import (
    REPO_ROOT, Config, VALID_ENVS, console, step, ok, info, warn,
    check_tool, run,
    tf_init, tf_apply, tf_outputs,
    kubectl_apply, kubectl_apply_file, wait_rollout,
    update_kubeconfig, helm_repo_add, helm_upgrade,
)

HELM_REPOS = {
    "jetstack":              "https://charts.jetstack.io",
    "confluentinc":          "https://confluent.github.io/helm-charts",
    "secrets-store-csi-driver": "https://kubernetes-sigs.github.io/secrets-store-csi-driver/charts",
    "aws-secrets-provider":  "https://aws.github.io/secrets-store-csi-driver-provider-aws",
}


def check_prerequisites() -> None:
    step("Checking prerequisites")
    for tool in ["terraform", "kubectl", "helm", "aws"]:
        check_tool(tool)
        ok(tool)


def provision_networking(cfg: Config) -> dict:
    step("Provisioning VPC and networking")
    tf_init("infra/networking", cfg, cfg.networking_backend_key)
    tf_apply("infra/networking", cfg.networking_tf_env())
    outputs = tf_outputs("infra/networking", cfg.networking_tf_env())
    ok(f"VPC: {outputs['vpc_id']}  ({outputs['vpc_cidr']})")
    ok(f"Private subnets: {', '.join(outputs['private_subnet_ids'])}")
    return outputs


def provision_confluent(cfg: Config, networking_out: dict) -> dict:
    step("Provisioning Confluent Cloud infrastructure")
    env = cfg.platform_tf_env(networking_out)
    tf_init("infra/platform", cfg, cfg.platform_backend_key)
    tf_apply("infra/platform", env)
    outputs = tf_outputs("infra/platform", env)
    ok(f"Cluster: {outputs['cluster_id']}")
    ok(f"Bootstrap: {outputs['cluster_bootstrap_endpoint']}")
    return outputs


def detect_my_ip() -> str | None:
    """Return current public IP as a /32 CIDR, or None if unreachable."""
    try:
        with urllib.request.urlopen("https://checkip.amazonaws.com", timeout=5) as r:
            return r.read().decode().strip() + "/32"
    except Exception:
        return None


def provision_eks(cfg: Config, networking_out: dict) -> dict:
    step("Provisioning EKS cluster")
    env = cfg.eks_tf_env(networking_out)

    if cfg.endpoint_public_access and not cfg.public_access_cidrs:
        my_ip = detect_my_ip()
        if my_ip:
            info(f"Restricting EKS public endpoint to current IP: {my_ip}")
            info(f"  To lock this in: set public_access_cidrs=[\"{my_ip}\"] in {cfg.env}/eks.tfvars.json")
            env = {**env, "TF_VAR_public_access_cidrs": json.dumps([my_ip])}
        else:
            warn("Could not detect public IP — EKS endpoint will be open to 0.0.0.0/0")

    tf_init("infra/eks", cfg, cfg.eks_backend_key)
    tf_apply("infra/eks", env)
    outputs = tf_outputs("infra/eks", env)
    ok(f"Cluster: {outputs['cluster_name']}")
    ok(f"OIDC provider: {outputs['oidc_provider_arn']}")
    return outputs


def install_helm_repos() -> None:
    step("Adding Helm repositories")
    for name, url in HELM_REPOS.items():
        helm_repo_add(name, url)
        ok(name)


def install_cert_manager() -> None:
    step("Installing cert-manager")
    kubectl_apply_file("kubernetes/cert-manager/namespace.yaml")
    helm_upgrade(
        release="cert-manager",
        chart="jetstack/cert-manager",
        namespace="cert-manager",
        values_file="kubernetes/cert-manager/values.yaml",
        version="v1.14.5",
    )
    wait_rollout("cert-manager", "cert-manager")
    wait_rollout("cert-manager", "cert-manager-webhook")
    ok("cert-manager ready")


def install_cfk(cfg: Config) -> None:
    step("Installing Confluent for Kubernetes operator")
    kubectl_apply_file("kubernetes/confluent-operator/namespace.yaml")
    helm_upgrade(
        release="confluent-operator",
        chart="confluentinc/confluent-for-kubernetes",
        namespace="confluent",
        values_file="kubernetes/confluent-operator/values.yaml",
    )
    wait_rollout("confluent", "confluent-operator")
    ok("CFK operator ready")


def install_csi_driver(csi_irsa_arn: str) -> None:
    step("Installing CSI Secrets Store driver")
    helm_upgrade(
        release="csi-secrets-store",
        chart="secrets-store-csi-driver/secrets-store-csi-driver",
        namespace="kube-system",
        values_file="kubernetes/csi-secrets-store/values.yaml",
        set_args=[
            f"serviceAccount.annotations.eks\\.amazonaws\\.com/role-arn={csi_irsa_arn}",
        ],
    )
    helm_upgrade(
        release="secrets-provider-aws",
        chart="aws-secrets-provider/secrets-store-csi-driver-provider-aws",
        namespace="kube-system",
        set_args=["secrets-store-csi-driver.install=false"],
    )
    ok("CSI Secrets Store driver ready")


def apply_cert_issuers() -> None:
    step("Applying cert-manager issuers")
    kubectl_apply_file("kubernetes/cert-manager/cluster-issuer.yaml")
    ok("ClusterIssuer, CA, and Issuer applied")


def apply_connect(platform_out: dict, eks_out: dict, cfg: Config) -> None:
    step("Deploying CFK Connect workers")

    # ServiceAccount — inject IRSA ARN
    sa_yaml = (REPO_ROOT / "kubernetes/connect/service-account.yaml").read_text()
    sa_yaml = sa_yaml.replace(
        'eks.amazonaws.com/role-arn: ""',
        f'eks.amazonaws.com/role-arn: "{eks_out["cfk_connect_irsa_role_arn"]}"',
    )
    kubectl_apply(sa_yaml, label="connect/service-account.yaml")

    # SecretProviderClass — inject actual Secrets Manager secret name
    spc_yaml = (REPO_ROOT / "kubernetes/connect/secret-provider-class.yaml").read_text()
    # Secret path is deterministic: /{environment_name}/confluent/cfk-connect-jaas
    # Created by the cluster pipeline; not an infra pipeline output.
    jaas_secret = f"/{cfg.environment_name}/confluent/cfk-connect-jaas"
    spc_yaml = spc_yaml.replace('objectName: "cfk-connect-jaas"', f'objectName: "{jaas_secret}"')
    kubectl_apply(spc_yaml, label="connect/secret-provider-class.yaml")

    # Secret-sync pod — mounts CSI volume to trigger K8s Secret creation before Connect starts.
    # Will not become Available until the cluster pipeline has written the JAAS secret to
    # Secrets Manager — that's expected at this stage.
    kubectl_apply_file("kubernetes/connect/secret-sync.yaml")
    info("Waiting up to 60s for secret-sync (requires cluster pipeline JAAS secret) …")
    result = run(["kubectl", "wait", "--for=condition=Available",
                  "deployment/confluent-secret-sync",
                  "-n", "confluent", "--timeout=60s"],
                 check=False)
    if result.returncode != 0:
        warn("secret-sync not yet Available — JAAS secret missing until cluster pipeline runs; continuing")

    # Connect CR — inject bootstrap endpoint and SR URL
    connect_yaml = (REPO_ROOT / "kubernetes/connect/connect.yaml").read_text()
    connect_yaml = connect_yaml.replace(
        'bootstrapEndpoint: ""',
        f'bootstrapEndpoint: "{platform_out["cluster_bootstrap_endpoint"]}"',
    )
    # SR endpoint is provisioned in the cluster pipeline; strip the block entirely if not
    # yet available — CFK rejects url: "" (must be at least 1 char)
    sr_endpoint = platform_out.get("schema_registry_endpoint", "")
    if sr_endpoint:
        connect_yaml = connect_yaml.replace(
            'url: "" # replace with schema_registry_endpoint from infra/platform output',
            f'url: "{sr_endpoint}"',
        )
        connect_yaml = connect_yaml.replace("    # BEGIN:schemaRegistry  (stripped by provision.py when SR endpoint not yet available)\n", "")
        connect_yaml = connect_yaml.replace("    # END:schemaRegistry\n", "")
    else:
        connect_yaml = re.sub(
            r"    # BEGIN:schemaRegistry.*?    # END:schemaRegistry\n",
            "",
            connect_yaml,
            flags=re.DOTALL,
        )
    kubectl_apply(connect_yaml, label="connect/connect.yaml")

    info("Waiting for Connect workers to be ready …")
    run(["kubectl", "wait", "--for=condition=Ready",
         "pod", "-l", "app=connect",
         "-n", "confluent", "--timeout=300s"],
        check=False)
    ok("Connect workers deployed")


def print_summary(networking_out: dict, platform_out: dict, eks_out: dict) -> None:
    console.print()
    console.print(Panel.fit(
        f"""[bold green]Platform provisioned successfully[/]

[bold]Networking[/]
  VPC             : {networking_out.get('vpc_id', 'n/a')}  ({networking_out.get('vpc_cidr', 'n/a')})
  Private subnets : {', '.join(networking_out.get('private_subnet_ids', []))}

[bold]Confluent Cloud[/]
  Environment ID  : {platform_out.get('environment_id', 'n/a')}
  Cluster ID      : {platform_out.get('cluster_id', 'n/a')}
  Bootstrap       : {platform_out.get('cluster_bootstrap_endpoint', 'n/a')}
  Schema Registry : {platform_out.get('schema_registry_endpoint', 'n/a')}

[bold]EKS[/]
  Cluster         : {eks_out.get('cluster_name', 'n/a')}
  OIDC Provider   : {eks_out.get('oidc_provider_arn', 'n/a')}

[bold]Next steps[/]
  1. [bold]From inside the VPC[/] — run the cluster pipeline (creates API keys,
     JAAS secret, topics, ACLs — unblocks secret-sync pod + Connect workers):
       uv run --project scripts scripts/cluster_pipeline.py --env {eks_out.get('cluster_name', '<env>').split('-')[-1]}
  2. After first schema registered — activate Schema Registry:
       scripts/cluster_pipeline.py --env <env> --activate-sr
       scripts/provision.py --env <env> --skip-terraform
  3. Build self-service  →  self-service/  (OPA policies, onboarding gates)""",
        title="Summary",
    ))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", required=True, choices=VALID_ENVS,
                        help="Target environment")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate config and prerequisites without applying anything")
    parser.add_argument("--skip-terraform", action="store_true",
                        help="Skip Terraform (use existing outputs) — for re-running K8s steps only")
    args = parser.parse_args()

    cfg = Config.load(args.env)
    console.print(f"\n[bold]Provisioning environment:[/] [cyan]{args.env}[/]  "
                  f"({cfg.environment_name})\n")
    check_prerequisites()

    if args.dry_run:
        console.print("\n[yellow]Dry run — no changes applied.[/]")
        return

    install_helm_repos()

    if args.skip_terraform:
        warn("--skip-terraform: reading existing Terraform outputs")
        tf_init("infra/networking", cfg, cfg.networking_backend_key)
        tf_init("infra/platform", cfg, cfg.platform_backend_key)
        tf_init("infra/eks", cfg, cfg.eks_backend_key)
        networking_out = tf_outputs("infra/networking", cfg.networking_tf_env())
        platform_out = tf_outputs("infra/platform", cfg.platform_tf_env(networking_out))
        eks_out = tf_outputs("infra/eks", cfg.eks_tf_env(networking_out))
    else:
        networking_out = provision_networking(cfg)
        platform_out = provision_confluent(cfg, networking_out)
        eks_out = provision_eks(cfg, networking_out)

    update_kubeconfig(eks_out["cluster_name"], cfg.aws_region)
    install_cert_manager()
    install_cfk(cfg)
    install_csi_driver(eks_out["csi_secrets_store_irsa_role_arn"])
    apply_cert_issuers()
    apply_connect(platform_out, eks_out, cfg)
    print_summary(networking_out, platform_out, eks_out)


if __name__ == "__main__":
    main()
