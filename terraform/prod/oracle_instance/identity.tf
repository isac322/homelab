resource oci_identity_group admin {
  compartment_id = var.compartment_ocid
  description    = "Administrators"
  name           = "Administrators"
}


resource oci_identity_policy "accept_lpg" {
  for_each = nonsensitive(var.lpg_acceptor_tenancy_ocids)

  compartment_id = var.compartment_ocid
  description    = "accept_lpg_of_${each.key}"
  name           = "accept_lpg_of_${each.key}"

  statements = [
    "Define tenancy Requestor as ${each.value.tenancy_ocid}",
    "Define group RequestorGrp as ${each.value.group_ocid}",
    "Admit group RequestorGrp of tenancy Requestor to manage local-peering-to in compartment id ${var.compartment_ocid}",
    "Admit group RequestorGrp of tenancy Requestor to associate local-peering-gateways in tenancy Requestor with local-peering-gateways in compartment id ${var.compartment_ocid}",
  ]
}

resource oci_identity_policy "request_lpg" {
  for_each = nonsensitive(var.lpg_requester_tenancy_ocids)

  compartment_id = var.compartment_ocid
  description    = "request_lpg_to_${each.key}"
  name           = "request_lpg_to_${each.key}"

  statements = [
    "Define tenancy Acceptor as ${each.value}",
    "Allow group id ${oci_identity_group.admin.id} to manage local-peering-from in compartment id ${var.compartment_ocid}",
    "Endorse group id ${oci_identity_group.admin.id} to manage local-peering-to in tenancy Acceptor",
    "Endorse group id ${oci_identity_group.admin.id} to associate local-peering-gateways in compartment id ${var.compartment_ocid} with local-peering-gateways in tenancy Acceptor",
  ]
}