terraform {
  backend "s3" {
    region  = "ap-southeast-2"
    encrypt = true
    # All config injected at init time — key is env-scoped:
    #   dev:  key = "dev/eks/terraform.tfstate"
    #   prod: key = "prod/eks/terraform.tfstate"
  }
}
