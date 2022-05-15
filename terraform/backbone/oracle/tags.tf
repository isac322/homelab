resource "oci_identity_tag_namespace" "backbone" {
  compartment_id = var.tenancy_ocid
  description    = "Backbone Kubernetes cluster of homelab"
  name           = "k8s_backbone"
}

resource "oci_identity_tag" "managed_by_terraform" {
  description      = "Indicate that the resource are managed by terraform"
  name             = "ManagedByTerraform"
  tag_namespace_id = oci_identity_tag_namespace.backbone.id

  is_cost_tracking = true
  validator {
    validator_type = "ENUM"
    values         = ["TRUE", "FALSE"]
  }
}