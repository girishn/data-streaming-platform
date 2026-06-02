locals {
  common_tags = merge(
    {
      environment = var.environment_name
      managed-by  = "terraform"
      platform    = "data-streaming"
    },
    var.tags,
  )
}
