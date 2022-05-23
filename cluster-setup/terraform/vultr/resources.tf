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
          interface_name   = var.wireguard_interface_name
          networkd_netdev  = var.wireguard_server_systemd_networkd_netdev
          networkd_network = var.wireguard_server_systemd_networkd_network
        },
      ),
      templatefile(
        "${path.module}/startup_scripts/k3s.sh",
        {
          k3s_token        = random_id.k3s_token.hex
          node_id          = var.wireguard_server_ip
          node_external_ip = ""
          interface_name   = var.wireguard_interface_name
        },
      ),
      file("${path.module}/startup_scripts/reboot.sh"),
    ],
  )))
}