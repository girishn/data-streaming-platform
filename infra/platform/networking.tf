# ── VPC Endpoint Security Group ───────────────────────────────────────────────

resource "aws_security_group" "confluent_endpoint" {
  name        = "${var.environment_name}-confluent-endpoint"
  description = "Controls access to the Confluent Cloud PrivateLink VPC endpoint"
  vpc_id      = var.vpc_id

  ingress {
    description = "Kafka (SASL_SSL) from private subnets"
    from_port   = 9092
    to_port     = 9092
    protocol    = "tcp"
    cidr_blocks = var.private_subnet_cidrs
  }

  ingress {
    description = "Schema Registry + REST API from private subnets"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = var.private_subnet_cidrs
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, { Name = "${var.environment_name}-confluent-endpoint" })
}

# ── VPC Interface Endpoint ────────────────────────────────────────────────────
# Confluent exposes the Dedicated cluster as a VPC Endpoint Service.
# private_dns_enabled = false — DNS is managed via Route 53 PHZ below.

resource "aws_vpc_endpoint" "confluent" {
  vpc_id              = var.vpc_id
  service_name        = confluent_network.main.aws[0].private_link_endpoint_service
  vpc_endpoint_type   = "Interface"
  subnet_ids          = var.private_subnet_ids
  security_group_ids  = [aws_security_group.confluent_endpoint.id]
  private_dns_enabled = false

  tags = merge(local.common_tags, { Name = "${var.environment_name}-confluent-pl" })

  depends_on = [confluent_private_link_access.main]
}

# ── Route 53 Private Hosted Zone ──────────────────────────────────────────────
# Broker hostnames (*.{cluster-id}.{region}.aws.confluent.cloud) must resolve
# to the PrivateLink endpoint IPs within the VPC.
# The wildcard CNAME points to the endpoint's regional DNS name.

resource "aws_route53_zone" "confluent" {
  name    = "${confluent_kafka_cluster.main.id}.${var.aws_region}.aws.confluent.cloud"
  comment = "Private DNS for Confluent Cloud cluster ${confluent_kafka_cluster.main.id}"

  vpc {
    vpc_id = var.vpc_id
  }

  tags = local.common_tags
}

resource "aws_route53_record" "confluent_wildcard" {
  zone_id = aws_route53_zone.confluent.zone_id
  name    = "*.${confluent_kafka_cluster.main.id}.${var.aws_region}.aws.confluent.cloud"
  type    = "CNAME"
  ttl     = 60
  records = [aws_vpc_endpoint.confluent.dns_entry[0].dns_name]
}

# Zonal DNS entries — one per AZ — required when clients use per-broker connections
resource "aws_route53_record" "confluent_zonal" {
  for_each = toset(var.availability_zones)

  zone_id = aws_route53_zone.confluent.zone_id
  name    = "*.${each.value}.${confluent_kafka_cluster.main.id}.${var.aws_region}.aws.confluent.cloud"
  type    = "CNAME"
  ttl     = 60
  records = [aws_vpc_endpoint.confluent.dns_entry[0].dns_name]
}
