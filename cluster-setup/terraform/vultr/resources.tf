resource "vultr_ssh_key" "admin_ssh_key" {
  for_each = var.initial_ssh_keys

  name    = each.key
  ssh_key = each.value
}

resource "random_id" "k3s_token" {
  keepers = {
    # Generate a new id each time we switch to a new AMI id
    ami_id = var.api_key
  }

  byte_length = 16
}

resource "wireguard_asymmetric_key" "backbone_master" {
  bind = var.api_key
}

resource "wireguard_preshared_key" "backbone" {
}

resource "vultr_instance" "backbone_master" {
  region    = var.backbone_master_instance.region
  plan      = var.backbone_master_instance.plan
  os_id     = 1743  # Ubuntu 22.04 LTS
  hostname  = var.backbone_master_instance.hostname
  label     = var.backbone_master_instance.hostname
  script_id = vultr_startup_script.init_ubuntu_22_04.id

  ssh_key_ids      = [for k in vultr_ssh_key.admin_ssh_key : k.id]
  backups          = "disabled"
  enable_ipv6      = false
  ddos_protection  = false
  activation_email = false
}

resource "vultr_startup_script" "init_ubuntu_22_04" {
  name   = "init_ubuntu_22_04"
  script = sensitive(base64encode(join(
    "\n",
    [
      file("${path.module}/startup_scripts/init_ubuntu_22_04.sh"),
      file("${path.module}/startup_scripts/ssh_hardening.sh"),
      templatefile(
        "${path.module}/startup_scripts/wireguard.sh",
        {
          interface_name = var.wireguard_interface_name
          subnet         = var.wireguard_ip_subnet
          port           = var.wireguard_master_port
          private_key    = wireguard_asymmetric_key.backbone_master.private_key
          public_key     = wireguard_asymmetric_key.backbone_master.public_key
          preshared_key  = wireguard_preshared_key.backbone.key
          ip             = cidrhost(var.wireguard_ip_subnet, 1)
        },
      ),
    ],
  )))
}