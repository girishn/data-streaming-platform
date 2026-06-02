# Kafka API key secrets are created in the cluster pipeline (infra/cluster/).
# They require the cluster-scoped API keys which cannot be created from outside
# the VPC due to PrivateLink DNS resolution — see confluent.tf for details.
#
# Secret paths follow the pattern: /{environment_name}/confluent/{key-name}
# The cluster pipeline writes:
#   terraform-manager-kafka
#   cfk-connect-kafka
#   monitoring-kafka
#   cfk-connect-jaas   (SASL/PLAIN JAAS config for CFK Connect)
