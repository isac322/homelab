data oci_identity_availability_domain "domain" {
  compartment_id = var.compartment_ocid
  ad_number      = "1"
}

data oci_core_vnic_attachments "k8s_node" {
  compartment_id      = var.compartment_ocid
  availability_domain = data.oci_identity_availability_domain.domain.name
  instance_id         = oci_core_instance.k8s_node.id
}
