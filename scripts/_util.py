"""Shared utilities for platform provisioning scripts."""

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from rich.console import Console
from rich.rule import Rule

# Load .env from repo root if present — before any os.environ reads
load_dotenv(Path(__file__).parent.parent / ".env")

console = Console(legacy_windows=False)
REPO_ROOT = Path(__file__).parent.parent
VALID_ENVS = ("dev", "prod")


def _load_shared() -> dict:
    path = REPO_ROOT / "infra" / "environments" / "shared.json"
    if not path.exists():
        die(f"Missing: {path}")
    return json.loads(path.read_text())


# ── Output helpers ────────────────────────────────────────────────────────────

def step(msg: str) -> None:
    console.print()
    console.print(Rule(f"[bold cyan]{msg}[/]"))


def ok(msg: str) -> None:
    console.print(f"  [bold green]OK[/] {msg}")


def info(msg: str) -> None:
    console.print(f"  [blue]->[/] {msg}")


def warn(msg: str) -> None:
    console.print(f"  [yellow]![/] {msg}")


def die(msg: str) -> None:
    console.print(f"\n[bold red]FAILED:[/] {msg}")
    sys.exit(1)


# ── Config ────────────────────────────────────────────────────────────────────

@dataclass
class Config:
    env: str                      # "dev" or "prod"
    tf_bucket: str
    tf_table: str
    aws_region: str
    confluent_api_key: str
    confluent_api_secret: str
    # from infra/environments/{env}/platform.tfvars.json
    environment_name: str
    aws_account_id: str
    cluster_name: str
    cluster_cku: int
    cluster_availability: str
    # from infra/environments/{env}/networking.tfvars.json
    vpc_cidr: str
    private_subnet_cidrs: list[str]
    public_subnet_cidrs: list[str]
    availability_zones: list[str]
    single_nat_gateway: bool
    # from infra/environments/{env}/eks.tfvars.json
    node_instance_types: list[str]
    node_min_size: int
    node_max_size: int
    node_desired_size: int
    endpoint_public_access: bool
    public_access_cidrs: list[str]

    @classmethod
    def load(cls, env: str) -> "Config":
        """Load config: shared.json + tfvars.json for non-sensitive, env vars / .env for secrets."""
        if env not in VALID_ENVS:
            die(f"Invalid env '{env}'. Must be one of: {', '.join(VALID_ENVS)}")

        shared = _load_shared()
        env_dir = REPO_ROOT / "infra" / "environments" / env

        platform_path = env_dir / "platform.tfvars.json"
        if not platform_path.exists():
            die(f"Missing: {platform_path}")
        p = json.loads(platform_path.read_text())

        networking_path = env_dir / "networking.tfvars.json"
        if not networking_path.exists():
            die(f"Missing: {networking_path}")
        n = json.loads(networking_path.read_text())

        eks_path = env_dir / "eks.tfvars.json"
        e = json.loads(eks_path.read_text()) if eks_path.exists() else {}

        # Only the two Confluent API keys must come from env vars / .env
        for var in ["CONFLUENT_CLOUD_API_KEY", "CONFLUENT_CLOUD_API_SECRET"]:
            if not os.environ.get(var):
                die(
                    f"Missing: {var}\n"
                    f"  Set it in your shell or copy .env.example -> .env and fill it in."
                )

        return cls(
            env=env,
            tf_bucket=os.environ.get("PLATFORM_TF_BUCKET", shared["tf_bucket"]),
            tf_table=os.environ.get("PLATFORM_TF_TABLE", shared["tf_table"]),
            aws_region=os.environ.get("AWS_DEFAULT_REGION", shared.get("aws_region", "ap-southeast-2")),
            confluent_api_key=os.environ["CONFLUENT_CLOUD_API_KEY"],
            confluent_api_secret=os.environ["CONFLUENT_CLOUD_API_SECRET"],
            environment_name=p["environment_name"],
            aws_account_id=p["aws_account_id"],
            cluster_name=p.get("cluster_name", f"data-streaming-{env}"),
            cluster_cku=p.get("cluster_cku", 2),
            cluster_availability=p.get("cluster_availability", "MULTI_ZONE"),
            vpc_cidr=n["vpc_cidr"],
            private_subnet_cidrs=n["private_subnet_cidrs"],
            public_subnet_cidrs=n["public_subnet_cidrs"],
            availability_zones=n.get(
                "availability_zones",
                ["ap-southeast-2a", "ap-southeast-2b", "ap-southeast-2c"],
            ),
            single_nat_gateway=n.get("single_nat_gateway", True),
            node_instance_types=e.get("node_instance_types", ["m6i.xlarge"]),
            node_min_size=e.get("node_min_size", 2),
            node_max_size=e.get("node_max_size", 6),
            node_desired_size=e.get("node_desired_size", 2),
            endpoint_public_access=e.get("endpoint_public_access", False),
            public_access_cidrs=e.get("public_access_cidrs", []),
        )

    @property
    def networking_backend_key(self) -> str:
        return f"{self.env}/networking/terraform.tfstate"

    @property
    def platform_backend_key(self) -> str:
        return f"{self.env}/platform/terraform.tfstate"

    @property
    def eks_backend_key(self) -> str:
        return f"{self.env}/eks/terraform.tfstate"

    @property
    def cluster_backend_key(self) -> str:
        return f"{self.env}/cluster/terraform.tfstate"

    def networking_tf_env(self) -> dict[str, str]:
        return {
            **os.environ,
            "TF_VAR_environment_name":     self.environment_name,
            "TF_VAR_aws_region":           self.aws_region,
            "TF_VAR_cluster_name":         self.cluster_name,
            "TF_VAR_vpc_cidr":             self.vpc_cidr,
            "TF_VAR_private_subnet_cidrs": json.dumps(self.private_subnet_cidrs),
            "TF_VAR_public_subnet_cidrs":  json.dumps(self.public_subnet_cidrs),
            "TF_VAR_availability_zones":   json.dumps(self.availability_zones),
            "TF_VAR_single_nat_gateway":   str(self.single_nat_gateway).lower(),
        }

    def platform_tf_env(self, networking_out: dict | None = None) -> dict[str, str]:
        out = networking_out or {}
        return {
            **os.environ,
            "TF_VAR_environment_name":          self.environment_name,
            "TF_VAR_confluent_cloud_api_key":    self.confluent_api_key,
            "TF_VAR_confluent_cloud_api_secret": self.confluent_api_secret,
            "TF_VAR_aws_account_id":             self.aws_account_id,
            "TF_VAR_aws_region":                 self.aws_region,
            "TF_VAR_vpc_id":                     out.get("vpc_id", ""),
            "TF_VAR_private_subnet_ids":         json.dumps(out.get("private_subnet_ids", [])),
            "TF_VAR_private_subnet_cidrs":       json.dumps(out.get("private_subnet_cidrs", [])),
            "TF_VAR_cluster_name":               self.cluster_name,
            "TF_VAR_cluster_cku":                str(self.cluster_cku),
            "TF_VAR_cluster_availability":       self.cluster_availability,
            "TF_VAR_availability_zones":         json.dumps(out.get("availability_zones", self.availability_zones)),
        }

    def eks_tf_env(self, networking_out: dict | None = None) -> dict[str, str]:
        out = networking_out or {}
        return {
            **os.environ,
            "TF_VAR_environment_name":              self.environment_name,
            "TF_VAR_aws_account_id":                self.aws_account_id,
            "TF_VAR_aws_region":                    self.aws_region,
            "TF_VAR_cluster_name":                  self.cluster_name,
            "TF_VAR_vpc_id":                        out.get("vpc_id", ""),
            "TF_VAR_private_subnet_ids":            json.dumps(out.get("private_subnet_ids", [])),
            "TF_VAR_confluent_secrets_path_prefix": f"/{self.environment_name}/confluent",
            "TF_VAR_tf_bucket":                     self.tf_bucket,
            "TF_VAR_tf_table":                      self.tf_table,
            "TF_VAR_node_instance_types":           json.dumps(self.node_instance_types),
            "TF_VAR_node_min_size":                 str(self.node_min_size),
            "TF_VAR_node_max_size":                 str(self.node_max_size),
            "TF_VAR_node_desired_size":             str(self.node_desired_size),
            "TF_VAR_endpoint_public_access":        str(self.endpoint_public_access).lower(),
            "TF_VAR_public_access_cidrs":           json.dumps(self.public_access_cidrs),
        }

    def cluster_tf_env(self, platform_out: dict) -> dict[str, str]:
        """TF_VAR env for infra/cluster — requires platform pipeline outputs."""
        return {
            **os.environ,
            "TF_VAR_environment_name":          self.environment_name,
            "TF_VAR_confluent_cloud_api_key":    self.confluent_api_key,
            "TF_VAR_confluent_cloud_api_secret": self.confluent_api_secret,
            "TF_VAR_aws_account_id":             self.aws_account_id,
            "TF_VAR_aws_region":                 self.aws_region,
            "TF_VAR_environment_id":             platform_out["environment_id"],
            "TF_VAR_cluster_id":                 platform_out["cluster_id"],
            "TF_VAR_cluster_rest_endpoint":      platform_out["cluster_rest_endpoint"],
            "TF_VAR_sa_terraform_manager_id":    platform_out["sa_terraform_manager_id"],
            "TF_VAR_sa_cfk_connect_id":          platform_out["sa_cfk_connect_id"],
            "TF_VAR_sa_monitoring_id":           platform_out["sa_monitoring_id"],
        }


# ── subprocess helpers ────────────────────────────────────────────────────────

def run(
    cmd: list[str],
    cwd: Path | None = None,
    env: dict | None = None,
    capture: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess:
    result = subprocess.run(
        cmd,
        cwd=str(cwd or REPO_ROOT),
        env=env or dict(os.environ),
        capture_output=capture,
        text=True,
    )
    if check and result.returncode != 0:
        if capture and result.stderr:
            console.print(result.stderr)
        die(f"Command failed (exit {result.returncode}): {' '.join(str(c) for c in cmd)}")
    return result


def check_tool(name: str) -> None:
    result = subprocess.run(["which", name], capture_output=True)
    if result.returncode != 0:
        die(f"Required tool not found: {name}. Install it before running this script.")


# ── Terraform helpers ─────────────────────────────────────────────────────────

def tf_init(module: str, cfg: Config, backend_key: str) -> None:
    info(f"terraform init  ({module}  key={backend_key})")
    run(
        [
            "terraform", "init",
            f"-backend-config=bucket={cfg.tf_bucket}",
            f"-backend-config=dynamodb_table={cfg.tf_table}",
            f"-backend-config=region={cfg.aws_region}",
            f"-backend-config=key={backend_key}",
            "-reconfigure",
        ],
        cwd=REPO_ROOT / module,
    )


def tf_apply(module: str, env: dict) -> None:
    info(f"terraform apply  ({module})")
    run(["terraform", "apply", "-auto-approve"], cwd=REPO_ROOT / module, env=env)


def tf_destroy(module: str, env: dict) -> None:
    info(f"terraform destroy  ({module})")
    run(["terraform", "destroy", "-auto-approve"], cwd=REPO_ROOT / module, env=env)


def tf_outputs(module: str, env: dict | None = None) -> dict[str, Any]:
    result = run(
        ["terraform", "output", "-json"],
        cwd=REPO_ROOT / module,
        env=env or dict(os.environ),
        capture=True,
    )
    return {k: v["value"] for k, v in json.loads(result.stdout).items()}


# ── Kubernetes helpers ────────────────────────────────────────────────────────

def kubectl_apply(manifest: str, label: str = "") -> None:
    if label:
        info(f"kubectl apply  {label}")
    result = subprocess.run(
        ["kubectl", "apply", "-f", "-"],
        input=manifest, text=True, capture_output=True,
    )
    if result.returncode != 0:
        console.print(result.stderr)
        die("kubectl apply failed")
    for line in result.stdout.strip().splitlines():
        console.print(f"    {line}")


def kubectl_delete(manifest: str, ignore_not_found: bool = True) -> None:
    cmd = ["kubectl", "delete", "-f", "-"]
    if ignore_not_found:
        cmd += ["--ignore-not-found=true"]
    subprocess.run(cmd, input=manifest, text=True, capture_output=True)


def kubectl_apply_file(rel_path: str) -> None:
    kubectl_apply((REPO_ROOT / rel_path).read_text(), label=rel_path)


def wait_rollout(namespace: str, deployment: str, timeout: int = 180) -> None:
    info(f"Waiting for deployment/{deployment} in {namespace} …")
    run([
        "kubectl", "rollout", "status",
        f"deployment/{deployment}",
        "-n", namespace,
        f"--timeout={timeout}s",
    ])


def update_kubeconfig(cluster_name: str, region: str) -> None:
    info(f"Updating kubeconfig for cluster {cluster_name}")
    run(["aws", "eks", "update-kubeconfig", "--name", cluster_name, "--region", region])


def helm_repo_add(name: str, url: str) -> None:
    run(["helm", "repo", "add", name, url], check=False)
    run(["helm", "repo", "update"])


def helm_upgrade(
    release: str,
    chart: str,
    namespace: str,
    values_file: str | None = None,
    set_args: list[str] | None = None,
    version: str | None = None,
) -> None:
    cmd = [
        "helm", "upgrade", "--install", release, chart,
        "--namespace", namespace, "--create-namespace",
        "--wait", "--timeout", "5m",
    ]
    if values_file:
        cmd += ["-f", str(REPO_ROOT / values_file)]
    if version:
        cmd += ["--version", version]
    for s in (set_args or []):
        cmd += ["--set", s]
    info(f"helm upgrade --install {release}  ({chart})")
    run(cmd)
