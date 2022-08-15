resource oci_core_instance "k8s_node" {
  agent_config {
    are_all_plugins_disabled = "true"
    is_management_disabled   = "true"
    is_monitoring_disabled   = "true"
  }
  availability_config {
    #is_live_migration_preferred = <<Optional value not found in discovery>>
    recovery_action = "RESTORE_INSTANCE"
  }
  availability_domain = data.oci_identity_availability_domain.domain.name
  compartment_id      = var.compartment_ocid
  create_vnic_details {
    assign_public_ip       = "true"
    display_name           = "homelab"
    hostname_label         = var.instance_detail.host_name
    skip_source_dest_check = "true"
    subnet_id              = oci_core_subnet.homelab.id
  }
  display_name = var.instance_detail.host_name
  instance_options {
    are_legacy_imds_endpoints_disabled = "false"
  }
  launch_options {
    boot_volume_type        = "PARAVIRTUALIZED"
    firmware                = "UEFI_64"
    #    is_consistent_volume_naming_enabled = "true"
    #    is_pv_encryption_in_transit_enabled = "true"
    network_type            = "PARAVIRTUALIZED"
    remote_data_volume_type = "PARAVIRTUALIZED"
  }
  metadata = {
    "ssh_authorized_keys" = var.instance_detail.ssh_authorized_keys
  }
  shape = "VM.Standard.A1.Flex"
  shape_config {
    baseline_ocpu_utilization = "BASELINE_1_1"
    memory_in_gbs             = "24"
    nvmes                     = "0"
    ocpus                     = "4"
  }
  #  source_details {
  #    boot_volume_size_in_gbs = "200"
  #    boot_volume_vpus_per_gb = "120"
  #    #kms_key_id = <<Optional value not found in discovery>>
  #    source_id               = var.instance_image_ocid
  #    source_type             = "image"
  #  }
  state = "RUNNING"
}

resource oci_core_public_ip "k8s_node" {
  compartment_id = var.compartment_ocid
  display_name   = "k8s_node"
  private_ip_id  = oci_core_private_ip.k8s_node.id
  lifetime       = "RESERVED"
}

resource oci_core_private_ip "k8s_node" {
  ip_address = oci_core_instance.k8s_node.private_ip
  vnic_id    = data.oci_core_vnic_attachments.k8s_node.vnic_attachments[0].vnic_id
}
