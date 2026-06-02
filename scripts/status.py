"""
Platform status: checks every provisioned, in-progress, and pending resource.
Uses boto3 for AWS and the Confluent CLI for Confluent Cloud.
No Terraform state required — reads config from infra/environments/ directly.

Usage:
    uv run --project scripts scripts/status.py --env dev
    uv run --project scripts scripts/status.py --env prod

Requirements:
    AWS credentials in environment (aws configure / instance profile / env vars)
    Confluent CLI installed and CONFLUENT_CLOUD_API_KEY / _SECRET in env or .env
"""

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).parent))

import boto3
from botocore.exceptions import ClientError
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from _util import REPO_ROOT, VALID_ENVS

console = Console(legacy_windows=False)

# ── Status constants ──────────────────────────────────────────────────────────

OK       = "OK"
CREATING = "CREATING"
PENDING  = "PENDING"
ERROR    = "ERROR"
NA       = "N/A"
UNKNOWN  = "UNKNOWN"

STATUS_STYLE = {
    OK:       "bold green",
    CREATING: "bold yellow",
    PENDING:  "dim",
    ERROR:    "bold red",
    NA:       "dim cyan",
    UNKNOWN:  "dim yellow",
}

# Monthly cost notes — ap-southeast-2 On-Demand, approximate
COST = {
    "nat_gw":           "~$43/mo + $0.06/GB",
    "vpc_endpoint_az":  "~$9.50/mo/AZ",
    "eks_cluster":      "~$73/mo",
    "t3_large":         "~$69/mo/node",
    "m6i_xlarge":       "~$181/mo/node",
    "secrets_manager":  "~$0.40/mo/secret",
    "route53_phz":      "~$0.50/mo",
    "confluent_note":   "CKU-based — see confluent.io/pricing",
    "confluent_network":"PrivateLink fee — see confluent.io/pricing",
}


@dataclass
class Row:
    label: str
    status: str
    detail: str = ""
    cost: str = ""
    indent: bool = False


# ── Config loader (no API key required) ──────────────────────────────────────

def load_config(env: str) -> dict:
    shared_path = REPO_ROOT / "infra" / "environments" / "shared.json"
    if not shared_path.exists():
        console.print(f"[red]Missing:[/] {shared_path}")
        sys.exit(1)
    shared = json.loads(shared_path.read_text())

    env_dir = REPO_ROOT / "infra" / "environments" / env
    p = json.loads((env_dir / "platform.tfvars.json").read_text()) if (env_dir / "platform.tfvars.json").exists() else {}
    n = json.loads((env_dir / "networking.tfvars.json").read_text()) if (env_dir / "networking.tfvars.json").exists() else {}
    e = json.loads((env_dir / "eks.tfvars.json").read_text()) if (env_dir / "eks.tfvars.json").exists() else {}

    return {
        "env":                  env,
        "tf_bucket":            shared.get("tf_bucket", ""),
        "tf_table":             shared.get("tf_table", ""),
        "aws_region":           shared.get("aws_region", "ap-southeast-2"),
        "environment_name":     p.get("environment_name", f"data-streaming-{env}"),
        "cluster_name":         p.get("cluster_name", f"data-streaming-{env}"),
        "cluster_cku":          p.get("cluster_cku", 2),
        "cluster_availability": p.get("cluster_availability", "MULTI_ZONE"),
        "aws_account_id":       p.get("aws_account_id", ""),
        "vpc_cidr":             n.get("vpc_cidr", ""),
        "private_subnet_cidrs": n.get("private_subnet_cidrs", []),
        "public_subnet_cidrs":  n.get("public_subnet_cidrs", []),
        "availability_zones":   n.get("availability_zones", ["ap-southeast-2a", "ap-southeast-2b", "ap-southeast-2c"]),
        "single_nat_gateway":   n.get("single_nat_gateway", True),
        "node_instance_types":  e.get("node_instance_types", ["m6i.xlarge"]),
        "node_min_size":        e.get("node_min_size", 2),
        "node_max_size":        e.get("node_max_size", 6),
        "node_desired_size":    e.get("node_desired_size", 2),
        # derived
        "expected_nat_count":   1 if n.get("single_nat_gateway", True) else len(n.get("availability_zones", [3])),
    }


# ── Confluent CLI helper ──────────────────────────────────────────────────────

def confluent(*args) -> Optional[Any]:
    """Run a confluent CLI command with -o json. Returns parsed JSON or None on error."""
    cmd = ["confluent"] + list(args) + ["-o", "json"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return None
        return json.loads(result.stdout) if result.stdout.strip() else None
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return None


def confluent_available() -> bool:
    try:
        r = subprocess.run(["confluent", "version"], capture_output=True, timeout=10)
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


# ── AWS helper ────────────────────────────────────────────────────────────────

def tag_filter(cfg: dict) -> list:
    return [
        {"Name": "tag:Environment", "Values": [cfg["environment_name"]]},
        {"Name": "tag:Platform",    "Values": ["data-streaming"]},
    ]


def name_tag(resource: dict) -> str:
    for tag in resource.get("Tags", []):
        if tag["Key"] == "Name":
            return tag["Value"]
    return ""


def ago(dt: datetime) -> str:
    delta = datetime.now(timezone.utc) - dt
    h = int(delta.total_seconds() // 3600)
    m = int((delta.total_seconds() % 3600) // 60)
    return f"{h}h {m}m ago" if h else f"{m}m ago"


# ── Layer checks ──────────────────────────────────────────────────────────────

def check_bootstrap(cfg: dict, s3, ddb) -> list[Row]:
    rows: list[Row] = []
    bucket = cfg["tf_bucket"]
    table  = cfg["tf_table"]

    # ── S3 bucket
    try:
        s3.head_bucket(Bucket=bucket)
        ver = s3.get_bucket_versioning(Bucket=bucket)
        ver_status = ver.get("Status", "Disabled")
        rows.append(Row("S3 state bucket", OK,
                        f"{bucket}  (versioning: {ver_status.lower()})"))
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("404", "NoSuchBucket"):
            rows.append(Row("S3 state bucket", PENDING,
                            f"{bucket}  — run bootstrap.py first"))
        elif code == "403":
            rows.append(Row("S3 state bucket", ERROR,
                            f"{bucket}  — 403 Forbidden (name taken or no access)"))
        else:
            rows.append(Row("S3 state bucket", UNKNOWN, str(e)))

    # ── DynamoDB lock table
    try:
        resp = ddb.describe_table(TableName=table)
        status = resp["Table"]["TableStatus"]
        rows.append(Row("DynamoDB lock table", OK if status == "ACTIVE" else CREATING,
                        f"{table}  ({status.lower()})"))
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            rows.append(Row("DynamoDB lock table", PENDING,
                            f"{table}  — run bootstrap.py first"))
        else:
            rows.append(Row("DynamoDB lock table", UNKNOWN, str(e)))

    # ── Terraform state objects
    env = cfg["env"]
    for module, key in [
        ("networking", f"{env}/networking/terraform.tfstate"),
        ("platform",   f"{env}/platform/terraform.tfstate"),
        ("eks",        f"{env}/eks/terraform.tfstate"),
    ]:
        try:
            obj = s3.head_object(Bucket=bucket, Key=key)
            size  = obj["ContentLength"]
            mtime = obj["LastModified"]
            rows.append(Row(f"State: {module}", OK,
                            f"{key}  ({size:,} B, {ago(mtime)})", indent=True))
        except ClientError as e:
            if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
                rows.append(Row(f"State: {module}", PENDING,
                                f"{key}  — not yet applied", indent=True))
            else:
                rows.append(Row(f"State: {module}", UNKNOWN, str(e), indent=True))

    return rows


def check_networking(cfg: dict, ec2) -> list[Row]:
    rows: list[Row] = []
    env_name = cfg["environment_name"]

    # ── VPC
    vpc_id = None
    try:
        resp = ec2.describe_vpcs(Filters=tag_filter(cfg))
        vpcs = resp.get("Vpcs", [])
        if vpcs:
            vpc = vpcs[0]
            vpc_id = vpc["VpcId"]
            rows.append(Row("VPC", OK,
                            f"{vpc_id}  {vpc['CidrBlock']}  ({vpc['State']})"))
        else:
            rows.append(Row("VPC", PENDING,
                            f"expected CIDR {cfg['vpc_cidr']} — not found"))
    except Exception as e:
        rows.append(Row("VPC", UNKNOWN, str(e)))

    if not vpc_id:
        for label in ("Private subnets", "Public subnets", "Internet Gateway",
                      "NAT Gateways", "EIPs", "Private route tables", "Public route table"):
            rows.append(Row(label, PENDING, "waiting for VPC", indent=True))
        return rows

    # ── Subnets
    try:
        resp = ec2.describe_subnets(Filters=[
            {"Name": "vpc-id", "Values": [vpc_id]},
            *tag_filter(cfg),
        ])
        subnets = resp.get("Subnets", [])
        private = [s for s in subnets if "private" in name_tag(s).lower()]
        public  = [s for s in subnets if "public"  in name_tag(s).lower()]
        exp_priv = len(cfg["private_subnet_cidrs"])
        exp_pub  = len(cfg["public_subnet_cidrs"])
        priv_status = OK if len(private) == exp_priv else (CREATING if private else PENDING)
        pub_status  = OK if len(public)  == exp_pub  else (CREATING if public  else PENDING)
        priv_detail = "  ".join(f"{s['AvailabilityZone']}: {s['SubnetId']}" for s in private) or f"expected {exp_priv}x"
        pub_detail  = "  ".join(f"{s['AvailabilityZone']}: {s['SubnetId']}" for s in public)  or f"expected {exp_pub}x"
        rows.append(Row(f"Private subnets ({len(private)}/{exp_priv})", priv_status, priv_detail, indent=True))
        rows.append(Row(f"Public subnets ({len(public)}/{exp_pub})",   pub_status,  pub_detail,  indent=True))
    except Exception as e:
        rows.append(Row("Subnets", UNKNOWN, str(e), indent=True))

    # ── Internet Gateway
    try:
        resp = ec2.describe_internet_gateways(Filters=[
            {"Name": "attachment.vpc-id", "Values": [vpc_id]},
            *tag_filter(cfg),
        ])
        igws = resp.get("InternetGateways", [])
        if igws:
            rows.append(Row("Internet Gateway", OK, igws[0]["InternetGatewayId"], indent=True))
        else:
            rows.append(Row("Internet Gateway", PENDING, "not found", indent=True))
    except Exception as e:
        rows.append(Row("Internet Gateway", UNKNOWN, str(e), indent=True))

    # ── NAT Gateways
    try:
        resp = ec2.describe_nat_gateways(Filters=[
            {"Name": "vpc-id", "Values": [vpc_id]},
            {"Name": "state",  "Values": ["pending", "available"]},
            *tag_filter(cfg),
        ])
        nats = resp.get("NatGateways", [])
        exp_nat = cfg["expected_nat_count"]
        nat_status = OK if len(nats) == exp_nat else (CREATING if nats else PENDING)
        nat_detail = "  ".join(f"{n['NatGatewayId']} ({n['State']})" for n in nats) or f"expected {exp_nat}x"
        cost = COST["nat_gw"] if nats else ""
        rows.append(Row(f"NAT Gateways ({len(nats)}/{exp_nat})", nat_status, nat_detail, cost, indent=True))
    except Exception as e:
        rows.append(Row("NAT Gateways", UNKNOWN, str(e), indent=True))

    # ── EIPs
    try:
        resp = ec2.describe_addresses(Filters=tag_filter(cfg))
        eips = resp.get("Addresses", [])
        rows.append(Row(f"Elastic IPs ({len(eips)})", OK if eips else PENDING,
                        "  ".join(a.get("PublicIp", "") for a in eips) or f"expected {cfg['expected_nat_count']}x",
                        indent=True))
    except Exception as e:
        rows.append(Row("Elastic IPs", UNKNOWN, str(e), indent=True))

    # ── Route tables
    try:
        resp = ec2.describe_route_tables(Filters=[
            {"Name": "vpc-id", "Values": [vpc_id]},
            *tag_filter(cfg),
        ])
        rts = resp.get("RouteTables", [])
        private_rt = [r for r in rts if "private" in name_tag(r).lower()]
        public_rt  = [r for r in rts if "public"  in name_tag(r).lower()]
        rows.append(Row(f"Private route tables ({len(private_rt)})", OK if private_rt else PENDING,
                        f"expected {len(cfg['private_subnet_cidrs'])}x", indent=True))
        rows.append(Row(f"Public route table ({len(public_rt)})", OK if public_rt else PENDING,
                        "expected 1x", indent=True))
    except Exception as e:
        rows.append(Row("Route tables", UNKNOWN, str(e), indent=True))

    return rows


def check_platform_confluent(cfg: dict) -> list[Row]:
    rows: list[Row] = []
    env_name = cfg["environment_name"]

    if not confluent_available():
        rows.append(Row("Confluent CLI", UNKNOWN,
                        "confluent CLI not found — install from https://docs.confluent.io/confluent-cli/"))
        return rows

    # ── Environment
    env_id = None
    envs = confluent("environment", "list")
    if envs is None:
        rows.append(Row("Confluent auth", UNKNOWN,
                        "CLI call failed — check CONFLUENT_CLOUD_API_KEY / _SECRET in .env"))
        return rows

    env_obj = next((e for e in envs if e.get("name") == env_name), None)
    if env_obj:
        env_id = env_obj["id"]
        sg_pkg = env_obj.get("stream_governance", {}).get("package", "none")
        rows.append(Row("Environment", OK,
                        f"{env_id}  {env_name}  (stream governance: {sg_pkg.lower()})"))
    else:
        rows.append(Row("Environment", PENDING,
                        f"display_name={env_name}  — not found"))
        for label in ("PrivateLink network", "PrivateLink access", "Kafka cluster",
                      "Schema Registry", "Service accounts", "API keys"):
            rows.append(Row(label, PENDING, "waiting for environment", indent=True))
        return rows

    # ── PrivateLink network
    cluster_id = None
    networks = confluent("network", "list", "--environment", env_id) or []
    if networks:
        net = networks[0]
        state = net.get("status", {}).get("phase", net.get("phase", "UNKNOWN"))
        net_status = OK if state == "READY" else CREATING
        rows.append(Row("PrivateLink network", net_status,
                        f"{net['id']}  ({state})", COST["confluent_network"] if net_status == OK else "", indent=True))
    else:
        rows.append(Row("PrivateLink network", PENDING, "not found", indent=True))

    # ── Kafka cluster
    clusters = confluent("kafka", "cluster", "list", "--environment", env_id) or []
    cluster_obj = next((c for c in clusters if c.get("name") == cfg["cluster_name"]), None)
    if cluster_obj:
        cluster_id = cluster_obj["id"]
        state = cluster_obj.get("status", "UNKNOWN")
        cku   = cluster_obj.get("spec", {}).get("kafka", {}).get("cku", cfg["cluster_cku"])
        avail = cluster_obj.get("spec", {}).get("availability", cfg["cluster_availability"])
        c_status = OK if state in ("UP", "READY") else CREATING
        rows.append(Row("Kafka cluster", c_status,
                        f"{cluster_id}  {state}  ({avail}, {cku} CKU)",
                        COST["confluent_note"] if c_status == OK else "", indent=True))
    else:
        rows.append(Row("Kafka cluster", PENDING,
                        f"{cfg['cluster_name']} — not found", indent=True))

    # ── Schema Registry (lazily provisioned — informational only)
    sr = confluent("schema-registry", "cluster", "describe", "--environment", env_id)
    if sr:
        sr_id = sr.get("id", "?")
        sr_ep = sr.get("endpoint_url", sr.get("httpEndpoint", ""))
        rows.append(Row("Schema Registry", OK,
                        f"{sr_id}  {sr_ep}", indent=True))
    else:
        rows.append(Row("Schema Registry", NA,
                        "activates on first schema registration (ESSENTIALS lazy provisioning)",
                        indent=True))

    # ── Service accounts
    all_sas = confluent("iam", "service-account", "list") or []
    platform_sas = [sa for sa in all_sas if sa.get("name", "").startswith(env_name)]
    expected_sas = {f"{env_name}-terraform-manager", f"{env_name}-cfk-connect", f"{env_name}-monitoring"}
    found_names  = {sa.get("name") for sa in platform_sas}
    sa_status    = OK if expected_sas == found_names else (CREATING if found_names else PENDING)
    sa_detail    = "  ".join(sorted(n.replace(f"{env_name}-", "") for n in found_names)) or "none found"
    rows.append(Row(f"Service accounts ({len(platform_sas)}/3)", sa_status, sa_detail, indent=True))

    # ── API keys
    all_keys = confluent("api-key", "list") or []
    platform_keys = [k for k in all_keys if env_name in k.get("description", "")]
    rows.append(Row(f"API keys ({len(platform_keys)} found)", OK if platform_keys else PENDING,
                    ", ".join(k.get("key", "?")[:8] + "…" for k in platform_keys) or "none found",
                    indent=True))

    return rows


def check_platform_aws(cfg: dict, ec2, r53, sm) -> list[Row]:
    rows: list[Row] = []
    env_name = cfg["environment_name"]

    # ── VPC Interface Endpoint
    try:
        resp = ec2.describe_vpc_endpoints(Filters=[
            {"Name": "tag:Environment", "Values": [env_name]},
            {"Name": "vpc-endpoint-type", "Values": ["Interface"]},
            {"Name": "tag:Platform",    "Values": ["data-streaming"]},
        ])
        eps = [e for e in resp.get("VpcEndpoints", []) if e.get("State") != "deleted"]
        if eps:
            ep = eps[0]
            ep_state = ep.get("State", "?")
            az_count  = len(ep.get("SubnetIds", []))
            ep_status = OK if ep_state == "available" else CREATING
            cost = f"{COST['vpc_endpoint_az']} × {az_count} AZ" if ep_status == OK else ""
            rows.append(Row("VPC endpoint (PrivateLink)", ep_status,
                            f"{ep['VpcEndpointId']}  {ep_state}  ({az_count} AZs)", cost))
        else:
            rows.append(Row("VPC endpoint (PrivateLink)", PENDING, "not found"))
    except Exception as e:
        rows.append(Row("VPC endpoint (PrivateLink)", UNKNOWN, str(e)))

    # ── Endpoint security group
    try:
        resp = ec2.describe_security_groups(Filters=[
            {"Name": "group-name", "Values": [f"{env_name}-confluent-endpoint"]},
            {"Name": "tag:Platform", "Values": ["data-streaming"]},
        ])
        sgs = resp.get("SecurityGroups", [])
        if sgs:
            rows.append(Row("Endpoint security group", OK,
                            f"{sgs[0]['GroupId']}  {sgs[0]['GroupName']}"))
        else:
            rows.append(Row("Endpoint security group", PENDING, "not found"))
    except Exception as e:
        rows.append(Row("Endpoint security group", UNKNOWN, str(e)))

    # ── Route53 PHZ
    phz_id = None
    try:
        resp = r53.list_hosted_zones()
        phzs = [z for z in resp.get("HostedZones", [])
                if z.get("Config", {}).get("PrivateZone") and "confluent.cloud" in z["Name"]]
        env_phzs = [z for z in phzs if True]  # all Confluent PHZs (cluster-id embedded in name)
        if env_phzs:
            phz = env_phzs[0]
            phz_id = phz["Id"].split("/")[-1]
            record_count = phz.get("ResourceRecordSetCount", "?")
            rows.append(Row("Route53 PHZ", OK,
                            f"{phz_id}  {phz['Name'].rstrip('.')}  ({record_count} records)",
                            COST["route53_phz"]))
        else:
            rows.append(Row("Route53 PHZ", PENDING, "no Confluent Cloud PHZ found"))
    except Exception as e:
        rows.append(Row("Route53 PHZ", UNKNOWN, str(e)))

    if phz_id:
        try:
            resp = r53.list_resource_record_sets(HostedZoneId=phz_id)
            records = resp.get("ResourceRecordSets", [])
            wildcard = [r for r in records if r["Name"].startswith("*") and r.get("Type") == "CNAME"]
            zonal    = [r for r in records if r.get("Type") == "CNAME" and r not in wildcard]
            rows.append(Row(f"Route53 records ({len(records)})", OK if wildcard else CREATING,
                            f"wildcard: {len(wildcard)}  zonal: {len(zonal)}", indent=True))
        except Exception as e:
            rows.append(Row("Route53 records", UNKNOWN, str(e), indent=True))

    # ── Secrets Manager
    try:
        paginator = sm.get_paginator("list_secrets")
        secrets = []
        for page in paginator.paginate(Filters=[{"Key": "name", "Values": [f"/{env_name}/confluent/"]}]):
            secrets.extend(page.get("SecretList", []))
        exp_secrets = {"terraform-manager-kafka", "cfk-connect-kafka", "monitoring-kafka", "cfk-connect-jaas"}
        found_names = {s["Name"].split("/")[-1] for s in secrets}
        sm_status = OK if exp_secrets == found_names else (CREATING if found_names else PENDING)
        detail = ", ".join(sorted(found_names)) if found_names else f"expected {len(exp_secrets)} secrets"
        cost = f"{COST['secrets_manager']} × {len(secrets)}" if secrets else ""
        rows.append(Row(f"Secrets Manager ({len(secrets)}/{len(exp_secrets)})", sm_status, detail, cost))
    except Exception as e:
        rows.append(Row("Secrets Manager", UNKNOWN, str(e)))

    return rows


def check_eks(cfg: dict, eks_client, iam_client) -> list[Row]:
    rows: list[Row] = []
    cluster_name = cfg["cluster_name"]
    env_name     = cfg["environment_name"]

    # ── EKS cluster
    cluster_exists = False
    oidc_url = None
    try:
        resp = eks_client.describe_cluster(name=cluster_name)
        cluster = resp["cluster"]
        state   = cluster["status"]
        version = cluster.get("version", "?")
        ep_access = "private-only" if not cluster.get("resourcesVpcConfig", {}).get("endpointPublicAccess") else "public+private"
        c_status = OK if state == "ACTIVE" else CREATING
        rows.append(Row("EKS cluster", c_status,
                        f"{cluster_name}  v{version}  {state}  ({ep_access})",
                        COST["eks_cluster"] if c_status == OK else ""))
        cluster_exists = True
        oidc_url = cluster.get("identity", {}).get("oidc", {}).get("issuer", "")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            rows.append(Row("EKS cluster", PENDING,
                            f"{cluster_name}  — not yet provisioned"))
        else:
            rows.append(Row("EKS cluster", UNKNOWN, str(e)))

    if not cluster_exists:
        instance_type = cfg["node_instance_types"][0] if cfg["node_instance_types"] else "m6i.xlarge"
        cost_key = "t3_large" if instance_type == "t3.large" else "m6i_xlarge"
        desired  = cfg["node_desired_size"]
        for label, detail in [
            ("Node group", f"{instance_type} ×{cfg['node_min_size']}-{cfg['node_max_size']}  (desired: {desired})"),
            ("EKS add-ons (4)", "vpc-cni, coredns, kube-proxy, aws-ebs-csi-driver"),
            ("OIDC provider",   f"{cluster_name}"),
            ("IRSA: vpc-cni",   f"eks-vpc-cni-{env_name}"),
            ("IRSA: cfk-connect", f"cfk-connect-{env_name}"),
            ("IRSA: csi-secrets-store", f"csi-secrets-store-{env_name}"),
        ]:
            rows.append(Row(label, PENDING, detail, indent=True))
        return rows

    # ── Node groups
    try:
        resp = eks_client.list_nodegroups(clusterName=cluster_name)
        ngs  = resp.get("nodegroups", [])
        for ng_name in ngs:
            ng = eks_client.describe_nodegroup(clusterName=cluster_name, nodegroupName=ng_name)["nodegroup"]
            state    = ng["status"]
            instance = ng.get("instanceTypes", ["?"])[0]
            scaling  = ng.get("scalingConfig", {})
            ng_status = OK if state == "ACTIVE" else CREATING
            cost_key  = "t3_large" if "t3.large" in instance else "m6i_xlarge"
            desired   = scaling.get("desiredSize", "?")
            cost = f"{COST[cost_key]} × {desired} nodes" if ng_status == OK else ""
            rows.append(Row(f"Node group: {ng_name}", ng_status,
                            f"{instance}  ×{scaling.get('minSize')}-{scaling.get('maxSize')}  (desired: {desired})  {state}",
                            cost, indent=True))
        if not ngs:
            rows.append(Row("Node group", PENDING, "no node groups found", indent=True))
    except Exception as e:
        rows.append(Row("Node groups", UNKNOWN, str(e), indent=True))

    # ── Add-ons
    try:
        resp    = eks_client.list_addons(clusterName=cluster_name)
        addons  = resp.get("addons", [])
        details = []
        for addon_name in addons:
            addon  = eks_client.describe_addon(clusterName=cluster_name, addonName=addon_name)["addon"]
            state  = addon["status"]
            ver    = addon.get("addonVersion", "?")
            details.append(f"{addon_name}={ver} ({state})")
        addon_status = OK if len(addons) == 4 else (CREATING if addons else PENDING)
        rows.append(Row(f"EKS add-ons ({len(addons)}/4)", addon_status,
                        "  ".join(details) or "none found", indent=True))
    except Exception as e:
        rows.append(Row("EKS add-ons", UNKNOWN, str(e), indent=True))

    # ── OIDC provider
    try:
        resp   = iam_client.list_open_id_connect_providers()
        oidc_arn = None
        if oidc_url:
            host = oidc_url.replace("https://", "")
            for p in resp.get("OpenIDConnectProviderList", []):
                try:
                    info = iam_client.get_open_id_connect_provider(OpenIDConnectProviderArn=p["Arn"])
                    if host in info.get("Url", ""):
                        oidc_arn = p["Arn"]
                        break
                except Exception:
                    pass
        rows.append(Row("OIDC provider", OK if oidc_arn else PENDING,
                        oidc_arn or f"for cluster {cluster_name}", indent=True))
    except Exception as e:
        rows.append(Row("OIDC provider", UNKNOWN, str(e), indent=True))

    # ── IRSA roles
    for role_suffix, label in [
        (f"eks-vpc-cni-{env_name}",        "IRSA: vpc-cni"),
        (f"cfk-connect-{env_name}",        "IRSA: cfk-connect"),
        (f"csi-secrets-store-{env_name}",  "IRSA: csi-secrets-store"),
    ]:
        try:
            role = iam_client.get_role(RoleName=role_suffix)["Role"]
            rows.append(Row(label, OK, role["Arn"], indent=True))
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchEntity":
                rows.append(Row(label, PENDING, f"{role_suffix}  — not found", indent=True))
            else:
                rows.append(Row(label, UNKNOWN, str(e), indent=True))

    return rows


# ── Rendering ─────────────────────────────────────────────────────────────────

def make_table(title: str, rows: list[Row]) -> tuple:
    t = Table(
        title=f"[bold]{title}[/]",
        box=box.SIMPLE_HEAD,
        show_header=True,
        header_style="bold dim",
        title_justify="left",
        expand=True,
    )
    t.add_column("Resource",  min_width=36, no_wrap=True)
    t.add_column("Status",    width=10, justify="center")
    t.add_column("Detail",    ratio=3)
    t.add_column("Cost / mo", width=30, justify="right", style="dim")

    counts = {OK: 0, CREATING: 0, PENDING: 0, ERROR: 0, UNKNOWN: 0, NA: 0}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
        prefix = "  " if row.indent else ""
        label_text = Text(prefix + row.label)
        status_text = Text(row.status, style=STATUS_STYLE.get(row.status, ""))
        t.add_row(label_text, status_text, row.detail or "—", row.cost or "")

    return t, counts


def print_cost_summary(all_rows: list[Row]) -> None:
    cost_rows = [(r.label, r.cost) for r in all_rows if r.cost and r.status == OK]
    if not cost_rows:
        return

    t = Table(box=box.SIMPLE_HEAD, show_header=True, header_style="bold dim",
              title="[bold]Cost Estimate — Running Resources (ap-southeast-2)[/]",
              title_justify="left", expand=True)
    t.add_column("Resource", min_width=40)
    t.add_column("Estimate / mo", justify="right")
    t.add_column("Notes", style="dim")

    for label, cost in cost_rows:
        t.add_row(label, cost, "")
    t.add_row("", "", "")
    t.add_row("[dim]Data transfer[/]", "[dim]variable[/]", "[dim]not included above[/]")
    t.add_row("[dim]EKS nodes (if not yet running)[/]", "[dim]see above per-node estimates[/]", "")
    console.print(t)
    console.print("[dim]  Estimates are On-Demand. Spot or Savings Plans reduce EC2 costs. "
                  "Confluent costs: see confluent.io/pricing/cloud[/]\n")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Check platform provisioning status")
    parser.add_argument("--env", required=True, choices=VALID_ENVS)
    args = parser.parse_args()

    cfg = load_config(args.env)
    region = cfg["aws_region"]

    console.print()
    console.print(Panel.fit(
        f"[bold]Platform Status — {cfg['environment_name']} ({args.env})[/]\n"
        f"[dim]Region: {region}    Account: {cfg['aws_account_id'] or 'unknown'}[/]",
        border_style="cyan",
    ))
    console.print()

    session      = boto3.Session(region_name=region)
    s3           = session.client("s3")
    ddb          = session.client("dynamodb")
    ec2          = session.client("ec2")
    r53          = session.client("route53")
    sm           = session.client("secretsmanager")
    eks_client   = session.client("eks")
    iam_client   = session.client("iam")

    all_rows: list[Row] = []
    total_counts = {OK: 0, CREATING: 0, PENDING: 0, ERROR: 0, UNKNOWN: 0, NA: 0}

    layers = [
        ("Bootstrap — Terraform State",             lambda: check_bootstrap(cfg, s3, ddb)),
        ("Networking — VPC",                         lambda: check_networking(cfg, ec2)),
        ("Platform — Confluent Cloud",               lambda: check_platform_confluent(cfg)),
        ("Platform — AWS (endpoint, DNS, secrets)",  lambda: check_platform_aws(cfg, ec2, r53, sm)),
        ("EKS",                                      lambda: check_eks(cfg, eks_client, iam_client)),
    ]

    for title, fn in layers:
        rows = fn()
        all_rows.extend(rows)
        table, counts = make_table(title, rows)
        console.print(table)
        for k, v in counts.items():
            total_counts[k] = total_counts.get(k, 0) + v

    # ── Summary bar
    console.print()
    summary_parts = []
    if total_counts[OK]:
        summary_parts.append(f"[bold green]{total_counts[OK]} OK[/]")
    if total_counts[CREATING]:
        summary_parts.append(f"[bold yellow]{total_counts[CREATING]} CREATING[/]")
    if total_counts[PENDING]:
        summary_parts.append(f"[dim]{total_counts[PENDING]} PENDING[/]")
    if total_counts[ERROR]:
        summary_parts.append(f"[bold red]{total_counts[ERROR]} ERROR[/]")
    if total_counts[UNKNOWN]:
        summary_parts.append(f"[dim yellow]{total_counts[UNKNOWN]} UNKNOWN[/]")
    console.print("  " + "  ·  ".join(summary_parts))
    console.print()

    print_cost_summary(all_rows)


if __name__ == "__main__":
    main()
