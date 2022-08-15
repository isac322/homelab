output "group_ocid" {
  value     = oci_identity_group.admin.id
  sensitive = true
}

output "peer_requesting_lpg_gateway_ocid" {
  value     = {for k, gateway in oci_core_local_peering_gateway.homelab_peering_requests : k => gateway.id}
  sensitive = true
}

output "node_public_ip" {
  value     = oci_core_public_ip.k8s_node.ip_address
  sensitive = true
}

output "node_private_ip" {
  value     = oci_core_private_ip.k8s_node.ip_address
  sensitive = true
}

output "node_hostname" {
  value     = var.instance_detail.host_name
  sensitive = true
}

#output "secret_name_cf_ca_api_key" {
#  value = oci_vault_secret.cloudflare_ca_api_key.secret_name
#}
#
#output "secret_name_external_dns_api_token" {
#  value = oci_vault_secret.external_dns_api_token.secret_name
#}