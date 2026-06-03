"""
Cluster pipeline: Confluent Cloud topics, ACLs, API keys, quotas, and secrets.

IMPORTANT — VPC REQUIREMENT:
  This script MUST run from inside the AWS VPC (bastion host, EKS job, or
  AWS CodeBuild in the private subnet). The Confluent Terraform provider
  validates each Kafka cluster API key by calling the cluster REST endpoint,
  which resolves to a PrivateLink private IP unreachable from outside the VPC.
  Running this from a developer laptop or CI runner outside the VPC will hang.

  Use --via-bastion to automate this from any machine.
  ADR: docs/adr/ADR-010-cluster-pipeline-in-vpc.md
  ADR: docs/adr/ADR-014-bastion-ssm-automation.md

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
    uv run --project scripts scripts/cluster_pipeline.py --env dev --via-bastion
    uv run --project scripts scripts/cluster_pipeline.py --env dev --via-bastion --activate-sr

Required env vars — same as provision.py (CONFLUENT_CLOUD_API_KEY / _SECRET).
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from rich.panel import Panel
from _util import (
    REPO_ROOT, Config, VALID_ENVS, console, step, ok, info, warn, die,
    check_tool, run,
    tf_init, tf_apply, tf_outputs,
)

_TF_VERSION = "1.9.8"
_GITHUB_REPO = "https://github.com/girishn/data-streaming-platform.git"


# ── In-VPC gate ───────────────────────────────────────────────────────────────

def check_vpc_warning() -> None:
    console.print()
    console.print(Panel.fit(
        "[bold yellow]VPC REQUIREMENT[/]\n\n"
        "This pipeline must run from inside the AWS VPC.\n"
        "The Confluent provider validates API keys against the cluster REST\n"
        "endpoint, which resolves to a PrivateLink private IP.\n\n"
        "If you are on a bastion host or EKS job inside the VPC, continue.\n"
        "If you are on a developer laptop or external CI, this will hang.\n\n"
        "Tip: use [bold]--via-bastion[/] to automate this from your laptop.",
        title="⚠ In-VPC execution required",
        border_style="yellow",
    ))
    console.print()


# ── Bastion helpers ───────────────────────────────────────────────────────────

def _write_org_creds_secret(cfg: Config) -> str:
    """Write org-level Confluent API key/secret to Secrets Manager. Returns the secret name."""
    import boto3
    sm = boto3.client("secretsmanager", region_name=cfg.aws_region)
    secret_name = f"/{cfg.environment_name}/pipeline/org-api-key"
    value = json.dumps({"key": cfg.confluent_api_key, "secret": cfg.confluent_api_secret})

    try:
        meta = sm.describe_secret(SecretId=secret_name)
        if meta.get("DeletedDate"):
            sm.restore_secret(SecretId=secret_name)
        sm.put_secret_value(SecretId=secret_name, SecretString=value)
        info(f"Updated ephemeral credential secret: {secret_name}")
    except sm.exceptions.ResourceNotFoundException:
        sm.create_secret(
            Name=secret_name,
            SecretString=value,
            Tags=[
                {"Key": "Platform", "Value": "data-streaming"},
                {"Key": "Ephemeral", "Value": "true"},
                {"Key": "ManagedBy", "Value": "cluster_pipeline.py"},
            ],
        )
        info(f"Created ephemeral credential secret: {secret_name}")
    return secret_name


def _delete_org_creds_secret(cfg: Config, secret_name: str) -> None:
    """Force-delete the ephemeral org credentials secret (no recovery window)."""
    import boto3
    sm = boto3.client("secretsmanager", region_name=cfg.aws_region)
    try:
        sm.delete_secret(SecretId=secret_name, ForceDeleteWithoutRecovery=True)
        ok(f"Deleted ephemeral credential secret: {secret_name}")
    except Exception as exc:
        warn(f"Could not delete credential secret {secret_name}: {exc}")


def _launch_bastion(cfg: Config, subnet_id: str, instance_profile: str) -> str:
    """Launch a t3.micro in subnet_id. Returns the instance ID."""
    import boto3
    ec2 = boto3.client("ec2", region_name=cfg.aws_region)
    ssm = boto3.client("ssm", region_name=cfg.aws_region)

    # Resolve latest Amazon Linux 2023 AMI via SSM public parameter — no describe_images sort needed
    ami_id = ssm.get_parameter(
        Name="/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
    )["Parameter"]["Value"]
    info(f"AMI: {ami_id}")

    resp = ec2.run_instances(
        ImageId=ami_id,
        InstanceType="t3.micro",
        MinCount=1,
        MaxCount=1,
        SubnetId=subnet_id,
        IamInstanceProfile={"Name": instance_profile},
        # 20 GB gp3 — default 8 GB is too small for Confluent TF provider + uv Python env
        BlockDeviceMappings=[{
            "DeviceName": "/dev/xvda",
            "Ebs": {"VolumeSize": 20, "VolumeType": "gp3", "DeleteOnTermination": True},
        }],
        TagSpecifications=[{
            "ResourceType": "instance",
            "Tags": [
                {"Key": "Name", "Value": f"{cfg.environment_name}-cluster-pipeline-bastion"},
                {"Key": "ManagedBy", "Value": "cluster_pipeline.py"},
                {"Key": "Platform", "Value": "data-streaming"},
            ],
        }],
    )
    instance_id = resp["Instances"][0]["InstanceId"]
    info(f"Launched bastion: {instance_id}")
    return instance_id


def _wait_ssm_ready(cfg: Config, instance_id: str, timeout: int = 300) -> None:
    """Block until the instance is running and SSM agent has registered."""
    import boto3
    ec2 = boto3.client("ec2", region_name=cfg.aws_region)
    ssm = boto3.client("ssm", region_name=cfg.aws_region)

    info("Waiting for instance running …")
    ec2.get_waiter("instance_running").wait(
        InstanceIds=[instance_id],
        WaiterConfig={"Delay": 10, "MaxAttempts": 30},
    )

    info("Waiting for SSM agent registration …")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = ssm.describe_instance_information(
            Filters=[{"Key": "InstanceIds", "Values": [instance_id]}]
        )
        if resp["InstanceInformationList"]:
            ok("SSM agent ready")
            return
        time.sleep(10)
    die(f"SSM agent not ready after {timeout}s — check instance profile and NAT gateway")


def _build_pipeline_script(cfg: Config, secret_name: str, activate_sr: bool, destroy: bool = False) -> str:
    extra_flags = "--activate-sr" if activate_sr else ""
    if destroy:
        pipeline_cmd = f"scripts/cluster_pipeline.py --env {cfg.env} --yes --destroy"
    else:
        pipeline_cmd = f"scripts/cluster_pipeline.py --env {cfg.env} --yes {extra_flags}"
    return f"""\
#!/bin/bash
set -euo pipefail

echo "=== Install system packages ==="
dnf install -y git unzip

echo "=== Install Terraform {_TF_VERSION} ==="
curl -fsSL https://releases.hashicorp.com/terraform/{_TF_VERSION}/terraform_{_TF_VERSION}_linux_amd64.zip \\
  -o /tmp/tf.zip
unzip -q /tmp/tf.zip terraform -d /usr/local/bin
rm /tmp/tf.zip
terraform version

echo "=== Install uv ==="
curl -fsSL https://astral.sh/uv/install.sh | INSTALLER_NO_MODIFY_PATH=1 sh
UV=/root/.local/bin/uv

echo "=== Clone repo ==="
git clone --depth 1 {_GITHUB_REPO} /opt/platform
cd /opt/platform

echo "=== Read credentials from Secrets Manager ==="
CREDS_JSON=$(aws secretsmanager get-secret-value \\
  --secret-id {secret_name} \\
  --region {cfg.aws_region} \\
  --query SecretString \\
  --output text)
export CONFLUENT_CLOUD_API_KEY=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['key'])" "$CREDS_JSON")
export CONFLUENT_CLOUD_API_SECRET=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['secret'])" "$CREDS_JSON")
export AWS_DEFAULT_REGION={cfg.aws_region}

echo "=== Run cluster pipeline ==="
$UV run --project scripts {pipeline_cmd}
"""


def _cw_log_group(cfg: Config) -> str:
    return f"/data-streaming/{cfg.env}/cluster-pipeline"


def _send_ssm_command(
    cfg: Config,
    instance_id: str,
    secret_name: str,
    activate_sr: bool,
    log_prefix: str,
    destroy: bool = False,
) -> str:
    """Send the pipeline shell script via SSM. Returns the command ID."""
    import boto3
    ssm = boto3.client("ssm", region_name=cfg.aws_region)
    log_group = _cw_log_group(cfg)

    resp = ssm.send_command(
        InstanceIds=[instance_id],
        DocumentName="AWS-RunShellScript",
        Parameters={
            "commands": [_build_pipeline_script(cfg, secret_name, activate_sr, destroy=destroy)],
            "executionTimeout": ["1800"],
        },
        # S3 for archival; CloudWatch for live tailing
        OutputS3BucketName=cfg.tf_bucket,
        OutputS3KeyPrefix=log_prefix,
        CloudWatchOutputConfig={
            "CloudWatchLogGroupName": log_group,
            "CloudWatchOutputEnabled": True,
        },
        Comment=f"cluster-pipeline-{cfg.env}",
    )
    command_id = resp["Command"]["CommandId"]
    info(f"SSM command ID:  {command_id}")
    info(f"CloudWatch logs: {log_group}")
    info(f"S3 archive:      s3://{cfg.tf_bucket}/{log_prefix}/{command_id}/")
    return command_id


def _tail_and_wait(cfg: Config, ssm, command_id: str, instance_id: str) -> None:
    """
    Stream CloudWatch Logs output in near-real-time until the SSM command
    reaches a terminal state. Falls back to status-only polling if the log
    stream doesn't appear within 2 minutes.
    """
    import boto3
    logs = boto3.client("logs", region_name=cfg.aws_region)
    log_group = _cw_log_group(cfg)
    terminal = {"Success", "Failed", "TimedOut", "Cancelled", "DeliveryTimedOut"}

    # SSM creates the CW log stream just before first output — wait for it
    info("Waiting for CloudWatch log stream …")
    stdout_stream: str | None = None
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            resp = logs.describe_log_streams(
                logGroupName=log_group,
                logStreamNamePrefix=f"{command_id}/{instance_id}",
            )
            streams = [
                s["logStreamName"]
                for s in resp.get("logStreams", [])
                if "stdout" in s["logStreamName"]
            ]
            if streams:
                stdout_stream = streams[0]
                break
        except Exception:
            pass
        time.sleep(5)

    if stdout_stream is None:
        warn("CW log stream not found — falling back to status polling (no live output)")
        _status_only_wait(ssm, command_id, instance_id, terminal)
        return

    console.print(f"  [dim]Streaming: {stdout_stream}[/]\n")

    next_token: str | None = None
    status_ticks = 0

    while True:
        time.sleep(3)

        # Drain any new log events
        try:
            kwargs: dict = {
                "logGroupName": log_group,
                "logStreamName": stdout_stream,
                "startFromHead": True,
            }
            if next_token:
                kwargs["nextToken"] = next_token
            cw_resp = logs.get_log_events(**kwargs)
            for event in cw_resp["events"]:
                console.print(f"  {event['message'].rstrip()}")
            # Only advance the token when events were returned; otherwise CW
            # returns the same token and we'd loop without making progress.
            if cw_resp["events"]:
                next_token = cw_resp["nextForwardToken"]
        except Exception as exc:
            warn(f"CW read error: {exc}")

        # Check SSM terminal state every ~30 s (every 10th tick at 3 s)
        status_ticks += 1
        if status_ticks % 10 != 0:
            continue

        try:
            inv = ssm.get_command_invocation(CommandId=command_id, InstanceId=instance_id)
        except ssm.exceptions.InvocationDoesNotExist:
            continue

        status = inv["Status"]
        if status not in terminal:
            continue

        # Drain any remaining log events before exiting
        time.sleep(5)
        try:
            kwargs = {
                "logGroupName": log_group,
                "logStreamName": stdout_stream,
                "startFromHead": True,
            }
            if next_token:
                kwargs["nextToken"] = next_token
            cw_resp = logs.get_log_events(**kwargs)
            for event in cw_resp["events"]:
                console.print(f"  {event['message'].rstrip()}")
        except Exception:
            pass

        console.print()
        if status != "Success":
            stderr = inv.get("StandardErrorContent", "")
            if stderr:
                console.print("\n[red]STDERR (truncated):[/]")
                for line in stderr.splitlines():
                    console.print(f"  [red]{line}[/]")
            die(
                f"Pipeline {status}. Full log: "
                f"s3://{cfg.tf_bucket}/logs/cluster-pipeline/{cfg.env}/{command_id}/"
            )
        ok("Pipeline completed successfully")
        return


def _status_only_wait(ssm, command_id: str, instance_id: str, terminal: set) -> None:
    while True:
        time.sleep(15)
        try:
            inv = ssm.get_command_invocation(CommandId=command_id, InstanceId=instance_id)
        except ssm.exceptions.InvocationDoesNotExist:
            continue
        status = inv["Status"]
        console.print(f"  [dim]SSM status: {status}[/]", end="\r")
        if status in terminal:
            console.print()
            if status != "Success":
                die(f"Pipeline {status}")
            ok("Pipeline completed")
            return


def _terminate_bastion(cfg: Config, instance_id: str) -> None:
    import boto3
    boto3.client("ec2", region_name=cfg.aws_region).terminate_instances(
        InstanceIds=[instance_id]
    )
    ok(f"Terminating bastion: {instance_id}")


def run_via_bastion(cfg: Config, activate_sr: bool, destroy: bool = False) -> None:
    """
    Launch a temporary EC2 t3.micro in the platform VPC private subnet,
    run the cluster pipeline (or destroy) on it via SSM, then terminate the
    instance and delete the ephemeral credential secret.
    Safe to call from outside the VPC.
    """
    action = "destroy" if destroy else "pipeline"
    step(f"Cluster {action} via SSM bastion")
    check_tool("aws")

    secret_name = _write_org_creds_secret(cfg)
    instance_id: str | None = None

    try:
        tf_init("infra/networking", cfg, cfg.networking_backend_key)
        networking_out = tf_outputs("infra/networking", cfg.networking_tf_env())
        subnet_id = networking_out["private_subnet_ids"][0]

        instance_profile = f"{cfg.cluster_name}-cluster-pipeline-bastion"
        info(f"Instance profile: {instance_profile}")

        instance_id = _launch_bastion(cfg, subnet_id, instance_profile)
        _wait_ssm_ready(cfg, instance_id)

        import boto3 as _boto3
        ssm = _boto3.client("ssm", region_name=cfg.aws_region)
        log_prefix = f"logs/cluster-pipeline/{cfg.env}"
        command_id = _send_ssm_command(cfg, instance_id, secret_name, activate_sr, log_prefix, destroy=destroy)
        _tail_and_wait(cfg, ssm, command_id, instance_id)

    finally:
        if instance_id:
            _terminate_bastion(cfg, instance_id)
        _delete_org_creds_secret(cfg, secret_name)


# ── Core pipeline ─────────────────────────────────────────────────────────────

def destroy_cluster(cfg: Config, platform_out: dict) -> None:
    step("Destroying cluster pipeline (infra/cluster)")
    env = cfg.cluster_tf_env(platform_out)
    tf_init("infra/cluster", cfg, cfg.cluster_backend_key)
    from _util import tf_destroy
    tf_destroy("infra/cluster", env)
    ok("Cluster pipeline resources destroyed")


def provision_cluster(cfg: Config, platform_out: dict, schema_registry_active: bool) -> dict:
    step("Applying cluster pipeline (infra/cluster)")

    env = cfg.cluster_tf_env(platform_out)

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
    sr_endpoint = cluster_out.get("schema_registry_endpoint", "")
    if not sr_endpoint:
        warn("No SR endpoint in cluster outputs — skipping Connect SR activation")
        return

    step("Activating Schema Registry block in Connect CR")
    info(f"SR endpoint: {sr_endpoint}")

    from provision import apply_connect
    platform_out_with_sr = {**platform_out, "schema_registry_endpoint": sr_endpoint}

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
                        help="Skip VPC confirmation prompt (used automatically by --via-bastion)")
    parser.add_argument("--via-bastion", action="store_true",
                        help="Launch a temporary SSM-managed EC2 bastion in the VPC and run the "
                             "pipeline from inside. Safe to call from a developer laptop.")
    parser.add_argument("--destroy", action="store_true",
                        help="Destroy cluster pipeline resources (topics/ACLs/keys/secrets). "
                             "Must run from inside the VPC or with --via-bastion.")
    args = parser.parse_args()

    cfg = Config.load(args.env)
    console.print(f"\n[bold]Cluster pipeline — environment:[/] [cyan]{args.env}[/]  "
                  f"({cfg.environment_name})\n")

    # Bastion path short-circuits BEFORE the VPC gate — the calling machine is outside the VPC
    if args.via_bastion:
        run_via_bastion(cfg, activate_sr=args.activate_sr, destroy=args.destroy)
        return

    for tool in ["terraform", "aws"]:
        check_tool(tool)

    check_vpc_warning()

    if not args.yes:
        answer = input("Running from inside the VPC? Type 'yes' to continue: ").strip()
        if answer.lower() != "yes":
            console.print("[yellow]Aborted.[/]")
            sys.exit(0)

    warn("Reading existing Terraform outputs from infra pipelines …")
    tf_init("infra/networking", cfg, cfg.networking_backend_key)
    networking_out = tf_outputs("infra/networking", cfg.networking_tf_env())

    tf_init("infra/platform", cfg, cfg.platform_backend_key)
    platform_out = tf_outputs("infra/platform", cfg.platform_tf_env(networking_out))

    if args.destroy:
        destroy_cluster(cfg, platform_out)
        return

    cluster_out = provision_cluster(cfg, platform_out, schema_registry_active=args.activate_sr)

    if args.activate_sr and cluster_out.get("schema_registry_endpoint"):
        activate_connect_sr(platform_out, cluster_out, cfg)

    print_summary(cluster_out, schema_registry_active=args.activate_sr)


if __name__ == "__main__":
    main()
