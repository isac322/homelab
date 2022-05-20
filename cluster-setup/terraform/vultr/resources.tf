resource "vultr_ssh_key" "admin_ssh_key" {
  for_each = var.ssh_keys

  name    = each.key
  ssh_key = each.value
}

resource "vultr_instance" "backbone-master" {
  region    = var.backbone_master_instance.region
  plan      = var.backbone_master_instance.plan
  os_id     = 1743  # Ubuntu 22.04 LTS
  hostname  = var.backbone_master_instance.hostname
  label     = var.backbone_master_instance.hostname
  script_id = vultr_startup_script.init_ubuntu_22_04.id

  ssh_key_ids      = [for k in vultr_ssh_key.admin_ssh_key : k.id]
  backups          = 'disabled'
  enable_ipv6      = false
  ddos_protection  = false
  activation_email = false
}

resource "vultr_startup_script" "init_ubuntu_22_04" {
  name   = "init_ubuntu_22_04"
  script = base64encode(join(
    "\n",
    [
      file("${path.module}/startup_scripts/init_ubuntu_22_04.sh"),
      file("${path.module}/startup_scripts/ssh_hardening.sh")
    ],
  ))
}