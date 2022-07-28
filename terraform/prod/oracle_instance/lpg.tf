resource oci_core_internet_gateway "lpg" {
  compartment_id = var.compartment_ocid
  enabled        = "true"
  vcn_id         = oci_core_vcn.homelab.id
}

resource oci_core_local_peering_gateway "homelab_peering_requests" {
  for_each = nonsensitive(toset([for o in var.lpg_peer_requesters : o.alias]))

  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.homelab.id
}

resource oci_core_local_peering_gateway "homelab_to_peer" {
  for_each = nonsensitive({for o in var.lpg_peer_to_accepts : o.alias => o.gateway_ocid})

  compartment_id = var.compartment_ocid
  peer_id        = each.value
  vcn_id         = oci_core_vcn.homelab.id
}