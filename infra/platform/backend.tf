terraform {
  backend "s3" {
    region  = "ap-southeast-2"
    encrypt = true
    # All config injected at init time — key is env-scoped:
    #   dev:  key = "dev/platform/terraform.tfstate"
    #   prod: key = "prod/platform/terraform.tfstate"
    # terraform init -backend-config=bucket=... -backend-config=key=dev/platform/terraform.tfstate ...
  }
}
