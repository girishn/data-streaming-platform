"""
One-time bootstrap: create S3 bucket + DynamoDB table for Terraform state.
Run once per AWS account before first terraform init.

Usage:
    uv run --project scripts scripts/bootstrap.py

Config is read from infra/environments/shared.json.
Override with env vars: PLATFORM_TF_BUCKET, PLATFORM_TF_TABLE, AWS_DEFAULT_REGION.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import json
import os
import boto3
from botocore.exceptions import ClientError
from _util import REPO_ROOT, console, step, ok, info, warn, die


def get_config() -> dict:
    shared_path = REPO_ROOT / "infra" / "environments" / "shared.json"
    if not shared_path.exists():
        die(f"Missing shared config: {shared_path}")
    shared = json.loads(shared_path.read_text())

    bucket = os.environ.get("PLATFORM_TF_BUCKET", shared["tf_bucket"])
    table  = os.environ.get("PLATFORM_TF_TABLE",  shared["tf_table"])
    region = os.environ.get("AWS_DEFAULT_REGION", shared.get("aws_region", "ap-southeast-2"))

    if "REPLACE_" in bucket:
        die(
            f"S3 bucket name has an unfilled placeholder: {bucket}\n"
            f"  Edit infra/environments/shared.json and set tf_bucket to a globally unique name,\n"
            f"  e.g. data-streaming-tfstate-<your-12-digit-aws-account-id>"
        )

    return {"bucket": bucket, "table": table, "region": region}


def bootstrap_s3(s3, bucket: str, region: str) -> None:
    step(f"S3 bucket: {bucket}")

    try:
        s3.head_bucket(Bucket=bucket)
        ok("Bucket already exists — skipping creation")
        return
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "403":
            die(
                f"Bucket '{bucket}' exists but access was denied (403).\n"
                f"  This usually means the name is taken by another AWS account.\n"
                f"  Update tf_bucket in infra/environments/shared.json to a unique name."
            )
        if code != "404":
            die(f"Unexpected S3 error ({code}): {e}")

    info("Creating bucket …")
    if region == "us-east-1":
        s3.create_bucket(Bucket=bucket)
    else:
        s3.create_bucket(
            Bucket=bucket,
            CreateBucketConfiguration={"LocationConstraint": region},
        )

    info("Enabling versioning …")
    s3.put_bucket_versioning(
        Bucket=bucket,
        VersioningConfiguration={"Status": "Enabled"},
    )

    info("Enabling server-side encryption …")
    s3.put_bucket_encryption(
        Bucket=bucket,
        ServerSideEncryptionConfiguration={
            "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
        },
    )

    info("Blocking public access …")
    s3.put_public_access_block(
        Bucket=bucket,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        },
    )

    info("Adding lifecycle rule to expire non-current state versions after 90 days …")
    s3.put_bucket_lifecycle_configuration(
        Bucket=bucket,
        LifecycleConfiguration={
            "Rules": [{
                "ID": "expire-old-state-versions",
                "Status": "Enabled",
                "Filter": {"Prefix": ""},
                "NoncurrentVersionExpiration": {"NoncurrentDays": 90},
            }]
        },
    )

    ok(f"Bucket created and configured: s3://{bucket}")


def bootstrap_dynamodb(ddb, table: str, region: str) -> None:
    step(f"DynamoDB table: {table}")

    try:
        ddb.describe_table(TableName=table)
        ok("Table already exists — skipping creation")
        return
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            die(f"Unexpected DynamoDB error: {e}")

    info("Creating table …")
    ddb.create_table(
        TableName=table,
        AttributeDefinitions=[{"AttributeName": "LockID", "AttributeType": "S"}],
        KeySchema=[{"AttributeName": "LockID", "KeyType": "HASH"}],
        BillingMode="PAY_PER_REQUEST",
    )
    waiter = ddb.get_waiter("table_exists")
    waiter.wait(TableName=table)
    ok(f"Table created: {table}")


def main() -> None:
    cfg = get_config()
    console.print(f"\n[bold]Bootstrapping Terraform state backend[/]  ({cfg['region']})\n")

    session = boto3.Session(region_name=cfg["region"])
    bootstrap_s3(session.client("s3"), cfg["bucket"], cfg["region"])
    bootstrap_dynamodb(session.client("dynamodb"), cfg["table"], cfg["region"])

    console.print()
    console.rule("[bold green]Bootstrap complete[/]")
    console.print(f"""
[bold]Next: provision the platform[/]

1. Fill in infra/environments/dev/platform.tfvars.json (and prod/ when ready)
2. Copy .env.example -> .env and add your Confluent API keys
3. Run:

    uv run --project scripts scripts/provision.py --env dev

Required env vars (secrets only — everything else is in tfvars.json):
    CONFLUENT_CLOUD_API_KEY      <org-level API key>
    CONFLUENT_CLOUD_API_SECRET   <org-level API secret>

State bucket : s3://{cfg['bucket']}
Lock table   : {cfg['table']}  (region: {cfg['region']})
""")


if __name__ == "__main__":
    main()
