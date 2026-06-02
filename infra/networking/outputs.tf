output "vpc_id" {
  description = "VPC ID"
  value       = aws_vpc.main.id
}

output "vpc_cidr" {
  description = "VPC CIDR block"
  value       = aws_vpc.main.cidr_block
}

output "private_subnet_ids" {
  description = "Private subnet IDs — one per AZ, for EKS nodes and PrivateLink ENIs"
  value       = aws_subnet.private[*].id
}

output "public_subnet_ids" {
  description = "Public subnet IDs — one per AZ, for NAT Gateways and load balancers"
  value       = aws_subnet.public[*].id
}

output "private_subnet_cidrs" {
  description = "Private subnet CIDR blocks — used to scope PrivateLink endpoint security group ingress"
  value       = aws_subnet.private[*].cidr_block
}

output "availability_zones" {
  description = "Availability zones used — passed to platform module to keep PrivateLink AZ alignment"
  value       = var.availability_zones
}

output "nat_gateway_ids" {
  description = "NAT Gateway IDs"
  value       = aws_nat_gateway.main[*].id
}
