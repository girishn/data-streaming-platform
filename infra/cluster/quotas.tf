# [KB_GAP: confluent_kafka_client_quota principal format in provider 2.73.0]
#
# confluent_kafka_client_quota resources have been disabled because the
# Confluent Terraform provider 2.73.0 returns:
#   400 Bad Request: invalid principal format. expected sa-xxx
# even when the principal IS in sa-xxx format (e.g. "sa-2rj352y").
#
# Investigation needed before re-enabling:
#   - Compare the HTTP request body sent by the provider vs what the API expects
#   - Check if the Confluent Cloud Quotas API endpoint changed its format
#   - Test with a standalone confluent_kafka_client_quota resource using a fixed
#     principal to isolate whether the issue is in provider serialisation or
#     the API endpoint version being called
#
# Quotas are throughput rate-limiting only — the platform functions correctly
# without them. Re-enable once the principal format issue is resolved.
#
# Original quota sizing (preserved for when this is re-enabled):
#   1 CKU ≈ 250 MB/s aggregate; 10 MB/s per principal leaves headroom.
#   principals: sa_terraform_manager_id, sa_cfk_connect_id, sa_monitoring_id
