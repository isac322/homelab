resource oci_core_vcn "homelab" {
  cidr_blocks = [
    var.homelab_cidr_block,
  ]
  compartment_id          = var.compartment_ocid
  ipv6private_cidr_blocks = [
  ]
}

resource oci_core_subnet "homelab" {
  cidr_block                 = var.homelab_cidr_block
  compartment_id             = var.compartment_ocid
  dhcp_options_id            = oci_core_vcn.homelab.default_dhcp_options_id
  prohibit_internet_ingress  = "false"
  prohibit_public_ip_on_vnic = "false"
  route_table_id             = oci_core_vcn.homelab.default_route_table_id
  vcn_id                     = oci_core_vcn.homelab.id
}


locals {
  route_rules = merge(
    { (oci_core_internet_gateway.lpg.id) : "0.0.0.0/0" },
    {for o in var.lpg_peer_requesters : oci_core_local_peering_gateway.homelab_peering_requests[o.alias].id => o.destination_cidr},
    {for o in var.lpg_peer_to_accepts : oci_core_local_peering_gateway.homelab_to_peer[o.alias].id => o.destination_cidr},
  )
}

resource oci_core_route_table "homelab" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.homelab.id

  dynamic "route_rules" {
    for_each = nonsensitive(local.route_rules)

    content {
      destination       = route_rules.value
      destination_type  = "CIDR_BLOCK"
      network_entity_id = route_rules.key
    }
  }
}
